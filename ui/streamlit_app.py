from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence
from uuid import uuid4

import pandas as pd
import streamlit as st

from mns.data.duckdb_store import DuckDBStore
from mns.data.local_data import LocalMarketData
from mns.data.market_scope import MARKET_GROUP_LABELS
from mns.data.parquet_store import ParquetStore
from mns.data.providers.baostock_provider import BaoStockProvider
from mns.data.providers.qmt_provider import QMTProvider
from mns.data.sync import DailyKlineSyncService
from mns.data.timeframes import normalize_timeframe, timeframe_aliases
from mns.pipelines.daily_review import DailyReviewConfig, DailyReviewRunner
from mns.pipelines.intraday_pullback_review import IntradayPullbackReviewConfig, IntradayPullbackReviewRunner
from mns.review.chart_indicators import (
    ChartIndicatorSpec,
    add_price_overlay_indicators,
    available_price_overlay_indicators,
    indicator_display_names,
    load_default_price_overlay_indicators,
    resolve_price_overlay_indicators,
)
from mns.review.chart_style import DOWN_COLOR, LIMIT_UP_COLOR, UP_COLOR, build_kline_colors, build_limit_up_mask
from mns.review.problem_analyzer import count_problem_tags
from mns.review.screenshot_exporter import ScreenshotExporter
from mns.review.trade_reviewer import TradeReview
from mns.review.trade_pairs import pair_trade_actions


BAOSTOCK_FIXED_SYNC_WORKERS = 1


REVIEW_STATUS_OPTIONS = {
    "待复核": "PENDING_REVIEW",
    "合理": "APPROVED",
    "可疑": "QUESTIONABLE",
    "不合理": "REJECTED",
    "需要优化": "NEED_OPTIMIZATION",
}

BUY_RATING_OPTIONS = {
    "好买点": "GOOD",
    "可接受": "ACCEPTABLE",
    "买早了": "TOO_EARLY",
    "买晚了": "TOO_LATE",
    "追高": "CHASE_HIGH",
    "板块不支持": "WEAK_SECTOR",
    "不是核心": "NOT_LEADER",
}

SELL_RATING_OPTIONS = {
    "好卖点": "GOOD",
    "卖早了": "TOO_EARLY",
    "卖晚了": "TOO_LATE",
    "止损合理": "STOP_REASONABLE",
    "止损设计有问题": "STOP_BAD",
}

RATING_OPTIONS = {
    "优秀": "GOOD",
    "可接受": "ACCEPTABLE",
    "可疑": "QUESTIONABLE",
    "有问题": "BAD",
}

PROBLEM_TAG_OPTIONS = ["追高", "买早", "买晚", "卖早", "卖晚", "板块退潮", "非龙头", "止损过紧", "止损过宽", "市场环境过滤不足"]

COLUMN_LABELS = {
    "run_id": "复盘批次",
    "trade_id": "交易编号",
    "signal_id": "信号编号",
    "stock_code": "股票代码",
    "stock_name": "股票名称",
    "exchange": "交易所",
    "strategy_name": "策略名称",
    "action": "动作",
    "timeframe": "周期",
    "trade_date": "交易日期",
    "bar_time": "K线时间",
    "signal_time": "信号时间",
    "buy_time": "买入时间",
    "buy_price": "买入价",
    "sell_time": "卖出时间",
    "sell_price": "卖出价",
    "price": "价格",
    "quantity": "数量",
    "open": "开盘",
    "high": "最高",
    "low": "最低",
    "close": "收盘",
    "volume": "成交量",
    "amount": "成交额",
    "turnover": "换手率",
    "score": "评分",
    "candidate_reason": "候选理由",
    "reason": "理由",
    "status": "状态",
    "entry_price": "参考入场价",
    "stop_loss": "止损价",
    "take_profit": "止盈价",
    "pnl": "盈亏",
    "return_pct": "收益率",
    "snapshot_time": "快照时间",
    "total_equity": "总权益",
    "cash": "现金",
    "available_cash": "可用现金",
    "market_value": "持仓市值",
    "daily_pnl": "当日盈亏",
    "cumulative_return": "累计收益",
    "drawdown": "回撤",
    "review_id": "复核编号",
    "review_status": "复核状态",
    "buy_point_rating": "买点评级",
    "sell_point_rating": "卖点评级",
    "risk_control_rating": "风控评价",
    "market_context_rating": "市场环境",
    "sector_context_rating": "板块环境",
    "manual_note": "复核笔记",
    "problem_tags": "问题标签",
    "reviewed_by": "复核人",
    "review_time": "复核时间",
    "image_path": "图片路径",
    "chart_timeframe": "图表周期",
    "start_time": "开始时间",
    "end_time": "结束时间",
    "created_time": "创建时间",
    "problem_tag": "问题标签",
    "count": "次数",
}

BAOSTOCK_CREDENTIALS_PATH = Path("data/config/baostock_credentials.json")
BAOSTOCK_DEFAULT_USER_ID = ""
BAOSTOCK_DEFAULT_PASSWORD = ""
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
BAOSTOCK_BULK_SYNC_SCRIPT = WORKSPACE_ROOT / "tools" / "baostock_bulk_sync.py"
BAOSTOCK_BULK_SYNC_DEFAULT_STATE_PATH = "data/logs/baostock_bulk_sync_state.json"
BAOSTOCK_BULK_MARKET_GROUP_ORDER = ["all_a", "sh_a", "sz_a", "bj_a", "all_etf", "sh_etf", "sz_etf"]


def _get_store(db_path: str) -> DuckDBStore | None:
    path = Path(db_path)
    if not path.exists():
        return None
    return DuckDBStore(path)


def _load_baostock_credentials() -> tuple[str, str]:
    if BAOSTOCK_CREDENTIALS_PATH.exists():
        try:
            payload = json.loads(BAOSTOCK_CREDENTIALS_PATH.read_text(encoding="utf-8"))
            user_id = str(payload.get("user_id", "") or "")
            password = str(payload.get("password", "") or "")
            if user_id and password:
                return user_id, password
        except Exception:
            pass
    return BAOSTOCK_DEFAULT_USER_ID, BAOSTOCK_DEFAULT_PASSWORD


def _save_baostock_credentials(*, user_id: str, password: str) -> None:
    BAOSTOCK_CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    BAOSTOCK_CREDENTIALS_PATH.write_text(
        json.dumps({"user_id": user_id, "password": password}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_json_file(path: str | Path) -> dict | None:
    try:
        file_path = Path(path)
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _summarize_baostock_bulk_state(state_path: str) -> tuple[dict | None, pd.DataFrame]:
    state = _load_json_file(state_path)
    if not state:
        return None, pd.DataFrame()

    rows: list[dict[str, object]] = []
    for phase, phase_sections in (state.get("phases") or {}).items():
        for timeframe, section in (phase_sections or {}).items():
            summaries = section.get("summaries", []) or []
            rows.append(
                {
                    "phase": phase,
                    "timeframe": timeframe,
                    "completed": bool(section.get("completed", False)),
                    "completed_stock_count": len(set(section.get("completed_stock_codes", []) or [])),
                    "summary_count": len(summaries),
                    "rows_written": sum(int(item.get("rows_written", 0) or 0) for item in summaries),
                    "failed_count": sum(1 for item in summaries if str(item.get("status", "")) == "failed"),
                    "empty_count": sum(1 for item in summaries if str(item.get("status", "")) == "empty"),
                    "synced_count": sum(1 for item in summaries if str(item.get("status", "")) == "synced"),
                    "last_stock_code": summaries[-1].get("stock_code") if summaries else None,
                    "last_message": summaries[-1].get("message") if summaries else None,
                }
            )
    return state, pd.DataFrame(rows)


def _resolve_baostock_timeframe_plan(selected_timeframes: Sequence[str]) -> tuple[str, str, str]:
    normalized = [normalize_timeframe(item) for item in selected_timeframes if str(item).strip()]
    ordered: list[str] = []
    for timeframe in normalized:
        if timeframe not in ordered:
            ordered.append(timeframe)
    if not ordered:
        raise ValueError("请至少选择一个同步周期。")

    fetch: list[str] = []
    derive: list[str] = []
    intraday_selected = any(timeframe in {"5m", "15m", "30m", "1h"} for timeframe in ordered)
    if intraday_selected:
        fetch.append("5m")
        derive.extend([timeframe for timeframe in ordered if timeframe in {"15m", "30m", "1h"}])
    if "1d" in ordered:
        fetch.append("1d")

    fetch_text = ",".join(dict.fromkeys(fetch))
    derive_text = ",".join(dict.fromkeys(timeframe for timeframe in derive if timeframe != "5m"))
    return fetch_text, "5m", derive_text


def _run_baostock_bulk_sync_tool(
    *,
    db_path: str,
    stock_codes_text: str,
    stock_file: str,
    sync_all: bool,
    market_groups: Sequence[str],
    sync_start,
    sync_end,
    fetch_timeframes: str,
    derive_source_timeframe: str,
    derive_timeframes: str,
    adjustflag: str,
    sync_retries: int,
    user_id: str,
    password: str,
    state_path: str,
    reset_state: bool,
    allow_quality_issues: bool,
    host=None,
) -> subprocess.CompletedProcess[str]:
    if not BAOSTOCK_BULK_SYNC_SCRIPT.exists():
        raise FileNotFoundError(f"BaoStock bulk sync script not found: {BAOSTOCK_BULK_SYNC_SCRIPT}")

    command = [
        sys.executable,
        str(BAOSTOCK_BULK_SYNC_SCRIPT),
        "--db",
        db_path,
        "--parquet-root",
        "data/parquet",
        "--start",
        pd.Timestamp(sync_start).strftime("%Y-%m-%dT09:30:00"),
        "--end",
        pd.Timestamp(sync_end).strftime("%Y-%m-%dT15:00:00"),
        "--fetch-timeframes",
        fetch_timeframes,
        "--derive-source-timeframe",
        derive_source_timeframe,
        "--derive-timeframes",
        derive_timeframes,
        "--adjustflag",
        adjustflag,
        "--max-retries",
        str(int(sync_retries)),
        "--state-path",
        state_path,
    ]
    if reset_state:
        command.append("--reset-state")
    if sync_all:
        command.append("--sync-all")
    elif stock_codes_text.strip():
        command.extend(["--stock-codes", stock_codes_text.strip()])
    market_group_values = [str(value).strip() for value in market_groups if str(value).strip()]
    if market_group_values:
        command.extend(["--market-groups", ",".join(market_group_values)])
    if stock_file.strip():
        command.extend(["--stock-file", stock_file.strip()])
    if allow_quality_issues:
        command.append("--allow-quality-issues")

    env = os.environ.copy()
    env["MNS_BAOSTOCK_USER_ID"] = user_id
    env["MNS_BAOSTOCK_PASSWORD"] = password

    host = host or st.empty()
    if hasattr(host, "empty"):
        host.empty()
    panel = host.container() if hasattr(host, "container") else host
    panel.info("正在启动 BaoStock 断点同步工具。低周期先拉到本地，再本地转高周期。")
    with panel.expander("运行参数", expanded=False):
        st.code(" ".join(command), language="bash")

    result = subprocess.run(
        command,
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    if result.returncode == 0:
        panel.success("BaoStock 断点同步工具执行完成。")
    else:
        panel.error(f"BaoStock 断点同步工具执行失败，退出码 {result.returncode}。")
    if combined_output:
        with panel.expander("工具输出", expanded=True):
            st.code(combined_output, language="text")

    state, summary = _summarize_baostock_bulk_state(state_path)
    if state is not None:
        panel.caption(
            f"状态文件：{state_path} | 更新时间：{state.get('updated_at', '-')} | 总完成：{state.get('completed', False)}"
        )
    if not summary.empty:
        panel.dataframe(summary, use_container_width=True, hide_index=True)
    return result


def _load_kline(db_path: str, timeframe: str = "1d") -> pd.DataFrame:
    store = _get_store(db_path)
    if store is None:
        return pd.DataFrame()
    try:
        return LocalMarketData(store).get_kline(timeframe=timeframe)
    except Exception:
        return pd.DataFrame()


def _list_kline_timeframes(db_path: str) -> list[str]:
    store = _get_store(db_path)
    if store is None:
        return []
    try:
        df = store.query_frame(
            """
            SELECT DISTINCT timeframe
            FROM kline_bars
            ORDER BY timeframe
            """
        )
    except Exception:
        return []
    if df.empty or "timeframe" not in df.columns:
        return []
    values = [normalize_timeframe(value) for value in df["timeframe"].dropna().astype(str).tolist() if value]
    return sorted(set(values))


def _get_latest_trade_date(db_path: str, timeframe: str) -> str | None:
    store = _get_store(db_path)
    if store is None:
        return None
    try:
        df = store.query_frame(
            """
            SELECT MAX(trade_date) AS latest_trade_date
            FROM kline_bars
            WHERE timeframe IN (SELECT UNNEST(?))
            """,
            (list(timeframe_aliases(timeframe)),),
        )
    except Exception:
        return None
    if df.empty or "latest_trade_date" not in df.columns:
        return None
    value = df.iloc[0]["latest_trade_date"]
    if value is None or pd.isna(value):
        return None
    return str(pd.Timestamp(value).date())


def _list_export_runs(export_root: str) -> list[str]:
    root = Path(export_root)
    if not root.exists():
        return []
    run_ids = set()
    for path in root.glob("*_trades.csv"):
        run_ids.add(path.name.removesuffix("_trades.csv"))
    for path in root.glob("*_candidates.csv"):
        run_ids.add(path.name.removesuffix("_candidates.csv"))
    return sorted(run_ids, reverse=True)


def _read_export(export_root: str, run_id: str, name: str) -> pd.DataFrame:
    path = Path(export_root) / f"{run_id}_{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _metric_value(value, default: str = "-") -> str:
    if value is None or pd.isna(value):
        return default
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _today_date() -> date:
    return pd.Timestamp.today().date()


def _build_sync_feedback(sync_result) -> tuple[str, str]:
    base = f"已写入 {sync_result.rows_written} 行，{len(sync_result.parquet_files)} 个分区"
    if getattr(sync_result, "quality_issue_count", 0):
        base += f"，{sync_result.quality_issue_count} 个质量问题"
    if getattr(sync_result, "requested_stock_count", 0):
        base += (
            f"；股票结果 同步成功 {getattr(sync_result, 'synced_stock_count', 0)} / "
            f"请求 {getattr(sync_result, 'requested_stock_count', 0)}"
        )
    empty_stock_codes = getattr(sync_result, "empty_stock_codes", []) or []
    failed_stock_codes = getattr(sync_result, "failed_stock_codes", []) or []
    skipped_stock_codes = getattr(sync_result, "skipped_stock_codes", []) or []
    if empty_stock_codes:
        base += f"，空数据 {len(empty_stock_codes)}"
    if failed_stock_codes:
        base += f"，失败 {len(failed_stock_codes)}"
    if skipped_stock_codes:
        base += f"，已是最新跳过 {len(skipped_stock_codes)}"

    latest_trade_date = getattr(sync_result, "latest_trade_date", None)
    expected_latest_trade_date = getattr(sync_result, "expected_latest_trade_date", None)
    lagging_stock_codes = getattr(sync_result, "lagging_stock_codes", []) or []

    if sync_result.rows_written == 0:
        if skipped_stock_codes and not failed_stock_codes and not empty_stock_codes:
            if expected_latest_trade_date:
                return "success", f"本次没有新增写入；{len(skipped_stock_codes)} 只股票已覆盖到目标最新交易日 {expected_latest_trade_date}。"
            return "success", f"本次没有新增写入；{len(skipped_stock_codes)} 只股票已经是最新。"
        if expected_latest_trade_date:
            return "info", f"本次没有写入任何数据。目标最新交易日是 {expected_latest_trade_date}。"
        return "info", "本次没有写入任何数据。"

    if expected_latest_trade_date and lagging_stock_codes:
        sample_codes = "、".join(lagging_stock_codes[:5])
        more_text = f" 等 {len(lagging_stock_codes)} 只股票" if len(lagging_stock_codes) > 5 else ""
        return (
            "warning",
            f"{base}。但数据还没有覆盖到目标最新交易日 {expected_latest_trade_date}，当前最新仅到 {latest_trade_date}。"
            f"未覆盖股票: {sample_codes}{more_text}。",
        )

    if expected_latest_trade_date and latest_trade_date:
        return "success", f"{base}。最新交易日 {latest_trade_date}，已覆盖目标最新交易日 {expected_latest_trade_date}。"

    if latest_trade_date:
        return "success", f"{base}。当前最新交易日 {latest_trade_date}。"
    return "success", f"{base}。"


def _build_feature_refresh_feedback(sync_result) -> tuple[str, str] | None:
    if not getattr(sync_result, "feature_refresh_attempted", False):
        return None

    feature_rows_written = int(getattr(sync_result, "feature_rows_written", 0) or 0)
    followup_rows_written = int(getattr(sync_result, "followup_rows_written", 0) or 0)
    feature_refresh_message = str(getattr(sync_result, "feature_refresh_message", "") or "").strip()

    if getattr(sync_result, "feature_refresh_success", None) is False:
        text = "特征库刷新失败，行情数据已写入。"
        if feature_refresh_message:
            text += f" {feature_refresh_message}"
        return "warning", text

    text = (
        f"特征库刷新成功：写入 {feature_rows_written:,} 行日特征，"
        f"{followup_rows_written:,} 行后续表现。"
    )
    if feature_refresh_message:
        text += f" {feature_refresh_message}"
    return "success", text


def _render_sync_result_details(sync_result) -> None:
    empty_stock_codes = getattr(sync_result, "empty_stock_codes", []) or []
    failed_stock_codes = getattr(sync_result, "failed_stock_codes", []) or []
    lagging_stock_codes = getattr(sync_result, "lagging_stock_codes", []) or []
    skipped_stock_codes = getattr(sync_result, "skipped_stock_codes", []) or []
    feature_refresh_attempted = bool(getattr(sync_result, "feature_refresh_attempted", False))
    feature_refresh_success = getattr(sync_result, "feature_refresh_success", None)
    feature_refresh_message = str(getattr(sync_result, "feature_refresh_message", "") or "").strip()
    feature_rows_written = int(getattr(sync_result, "feature_rows_written", 0) or 0)
    followup_rows_written = int(getattr(sync_result, "followup_rows_written", 0) or 0)
    detail_items: list[str] = []
    if failed_stock_codes:
        detail_items.append(f"失败 {len(failed_stock_codes)} 只")
    if empty_stock_codes:
        detail_items.append(f"空数据 {len(empty_stock_codes)} 只")
    if skipped_stock_codes:
        detail_items.append(f"已是最新 {len(skipped_stock_codes)} 只")
    if lagging_stock_codes:
        detail_items.append(f"未覆盖最新交易日 {len(lagging_stock_codes)} 只")
    if feature_refresh_attempted:
        if feature_refresh_success is False:
            detail_items.append("特征库刷新失败")
        else:
            detail_items.append(f"特征库 {feature_rows_written} 行 / 后续表现 {followup_rows_written} 行")
    if not detail_items:
        return

    with st.expander("查看同步明细", expanded=False):
        if feature_refresh_attempted:
            if feature_refresh_success is False:
                st.warning(feature_refresh_message or "特征库刷新失败，行情数据已写入。")
            else:
                st.caption(
                    "特征库刷新结果："
                    f"日特征 {feature_rows_written:,} 行，"
                    f"后续表现 {followup_rows_written:,} 行。"
                )
        if failed_stock_codes:
            st.error(f"失败股票：{'、'.join(failed_stock_codes[:30])}")
        if empty_stock_codes:
            st.caption(f"空数据股票：{'、'.join(empty_stock_codes[:20])}")
        if skipped_stock_codes:
            st.caption(f"已是最新跳过：{'、'.join(skipped_stock_codes[:30])}")
        if lagging_stock_codes:
            st.warning(f"未覆盖目标最新交易日：{'、'.join(lagging_stock_codes[:30])}")


def _resolve_sync_stock_codes(provider, manual_codes: str, *, sync_all: bool) -> list[str]:
    if sync_all:
        stock_list = provider.get_stock_list()
        if stock_list.empty or "stock_code" not in stock_list.columns:
            raise ValueError("未能从数据源获取股票列表。")
        codes = stock_list["stock_code"].dropna().astype(str).str.strip()
        resolved = [code for code in codes.tolist() if code]
        if not resolved:
            raise ValueError("数据源返回的股票列表为空。")
        return sorted(set(resolved))

    resolved = [code.strip() for code in manual_codes.split(",") if code.strip()]
    if not resolved:
        raise ValueError("请输入至少一个股票代码，或勾选同步全部股票。")
    return resolved


def _build_sync_progress_callback(sync_label: str, total_count: int, *, host=None):
    host = host or st
    summary_text = host.empty()
    label_text = host.empty()
    progress_bar = host.progress(0.0)
    counts = {"synced": 0, "empty": 0, "failed": 0, "skipped": 0}

    def _render_metrics(percent: int = 0) -> None:
        completed = counts["synced"] + counts["empty"] + counts["failed"] + counts["skipped"]
        summary_text.markdown(
            f"<span style='color:#2e7d32'>{percent}%</span> | {completed:,}/{total_count:,} | 失败 {counts['failed']:,}",
            unsafe_allow_html=True,
        )
        label_text.markdown(f"{sync_label}：{percent}%")

    def _on_progress(event) -> None:
        if event.status == "synced":
            counts["synced"] += 1
            current_step = counts["synced"] + counts["empty"] + counts["failed"] + counts["skipped"]
        elif event.status == "empty":
            counts["empty"] += 1
            current_step = counts["synced"] + counts["empty"] + counts["failed"] + counts["skipped"]
        elif event.status == "failed":
            counts["failed"] += 1
            current_step = counts["synced"] + counts["empty"] + counts["failed"] + counts["skipped"]
        elif event.status == "skipped":
            counts["skipped"] += 1
            current_step = counts["synced"] + counts["empty"] + counts["failed"] + counts["skipped"]
        elif event.status == "running":
            current_step = min(max(event.current, 0), event.total)
        else:
            current_step = event.current

        ratio = current_step / event.total if event.total else 1.0
        percent = int(ratio * 100)
        progress_bar.progress(ratio)
        _render_metrics(percent)

    _render_metrics()
    return _on_progress, progress_bar, summary_text, label_text


def _run_baostock_sync(
    *,
    db_path: str,
    stock_codes: list[str],
    sync_start,
    sync_end,
    sync_timeframe: str,
    sync_workers: int,
    sync_retries: int,
    user_id: str,
    password: str,
    adjustflag: str = "2",
    resume_from_latest_local: bool = True,
    host=None,
):
    provider = BaoStockProvider(adjustflag=adjustflag, user_id=user_id, password=password)
    try:
        sync_workers = BAOSTOCK_FIXED_SYNC_WORKERS
        host = host or st.empty()
        if hasattr(host, "empty"):
            host.empty()
        panel = host.container() if hasattr(host, "container") else host
        panel.info(f"本次准备同步 {len(stock_codes)} 只股票。")
        _on_progress, progress_bar, progress_summary, progress_label = _build_sync_progress_callback("BaoStock 同步", len(stock_codes), host=panel)
        sync_result = DailyKlineSyncService(
            provider=provider,
            duckdb_store=DuckDBStore(db_path),
            parquet_store=ParquetStore("data/parquet"),
            provider_factory=lambda: BaoStockProvider(
                adjustflag=adjustflag,
                user_id=user_id,
                password=password,
            ),
            max_workers=int(sync_workers),
            max_retries=int(sync_retries),
        ).sync(
            stock_codes=stock_codes,
            start_time=pd.Timestamp(sync_start).to_pydatetime(),
            end_time=pd.Timestamp(sync_end).to_pydatetime(),
            timeframe=sync_timeframe,
            resume_from_latest_local=resume_from_latest_local,
            progress_callback=_on_progress,
        )
        progress_bar.progress(1.0)
        final_failed = len(getattr(sync_result, "failed_stock_codes", []) or [])
        progress_summary.markdown(
            f"<span style='color:#2e7d32'>100%</span> | {len(stock_codes):,}/{len(stock_codes):,} | 失败 {final_failed:,}",
            unsafe_allow_html=True,
        )
        progress_label.markdown("BaoStock 同步：100%")
        feedback_level, feedback_text = _build_sync_feedback(sync_result)
        getattr(panel, feedback_level)(f"同步完成。{feedback_text}")
        feature_feedback = _build_feature_refresh_feedback(sync_result)
        if feature_feedback is not None:
            feature_level, feature_text = feature_feedback
            getattr(panel, feature_level)(feature_text)
        with panel.container():
            _render_sync_result_details(sync_result)
        st.session_state["baostock_last_failed_codes"] = list(getattr(sync_result, "failed_stock_codes", []) or [])
        st.session_state["baostock_last_sync_config"] = {
            "sync_start": str(pd.Timestamp(sync_start).date()),
            "sync_end": str(pd.Timestamp(sync_end).date()),
            "sync_timeframe": sync_timeframe,
            "sync_workers": int(sync_workers),
            "sync_retries": int(sync_retries),
            "user_id": user_id,
            "password": password,
            "adjustflag": adjustflag,
        }
    except Exception as exc:
        st.error(f"同步失败：{exc}")
    finally:
        provider.logout()


def _post_close_sync_start_date() -> date:
    return date(2020, 1, 1)


def _run_baostock_post_close_bundle(
    *,
    db_path: str,
    user_id: str,
    password: str,
    adjustflag: str = "2",
    sync_workers: int = BAOSTOCK_FIXED_SYNC_WORKERS,
    sync_retries: int = 1,
    host=None,
):
    sync_workers = BAOSTOCK_FIXED_SYNC_WORKERS
    provider = BaoStockProvider(adjustflag=adjustflag, user_id=user_id, password=password)
    try:
        stock_codes = _resolve_sync_stock_codes(provider, "", sync_all=True)
    finally:
        provider.logout()

    host = host or st.empty()
    if hasattr(host, "empty"):
        host.empty()
    panel = host.container() if hasattr(host, "container") else host

    start_date = _post_close_sync_start_date()
    end_date = _today_date()
    panel.info(
        "准备执行收盘后一键回补："
        f"{len(stock_codes)} 只股票，范围 {start_date} -> {end_date}，周期 15m / 30m / 1h / 1d。"
    )

    results: dict[str, object] = {}
    for timeframe in ("15m", "30m", "1h", "1d"):
        panel.divider()
        panel.subheader(f"BaoStock {timeframe} 同步")
        results[timeframe] = _run_baostock_sync(
            db_path=db_path,
            stock_codes=stock_codes,
            sync_start=start_date,
            sync_end=end_date,
            sync_timeframe=timeframe,
            sync_workers=sync_workers,
            sync_retries=sync_retries,
            user_id=user_id,
            password=password,
            adjustflag=adjustflag,
            resume_from_latest_local=False,
            host=panel.container(),
        )

    panel.success("收盘后一键回补已全部执行完成。")
    return results


def _run_qmt_sync(
    *,
    db_path: str,
    stock_codes: list[str],
    sync_start,
    sync_end,
    sync_timeframe: str,
    qmt_dividend_type: str,
    resume_from_latest_local: bool = True,
    host=None,
):
    provider = QMTProvider(dividend_type=qmt_dividend_type)
    host = host or st.empty()
    if hasattr(host, "empty"):
        host.empty()
    panel = host.container() if hasattr(host, "container") else host
    panel.info(f"本次准备同步 {len(stock_codes)} 只股票。")
    _on_progress, progress_bar, progress_summary, progress_label = _build_sync_progress_callback(
        f"miniQMT {sync_timeframe} 同步",
        len(stock_codes),
        host=panel,
    )
    sync_result = DailyKlineSyncService(
        provider=provider,
        duckdb_store=DuckDBStore(db_path),
        parquet_store=ParquetStore("data/parquet"),
    ).sync(
        stock_codes=stock_codes,
        start_time=pd.Timestamp(sync_start).to_pydatetime(),
        end_time=pd.Timestamp(sync_end).to_pydatetime(),
        timeframe=sync_timeframe,
        resume_from_latest_local=resume_from_latest_local,
        progress_callback=_on_progress,
    )
    progress_bar.progress(1.0)
    final_failed = len(getattr(sync_result, "failed_stock_codes", []) or [])
    progress_summary.markdown(
        f"<span style='color:#2e7d32'>100%</span> | {len(stock_codes):,}/{len(stock_codes):,} | 失败 {final_failed:,}",
        unsafe_allow_html=True,
    )
    progress_label.markdown(f"miniQMT {sync_timeframe} 同步：100%")
    feedback_level, feedback_text = _build_sync_feedback(sync_result)
    getattr(panel, feedback_level)(f"miniQMT {sync_timeframe} 同步完成。{feedback_text}")
    feature_feedback = _build_feature_refresh_feedback(sync_result)
    if feature_feedback is not None:
        feature_level, feature_text = feature_feedback
        getattr(panel, feature_level)(feature_text)
    with panel.container():
        _render_sync_result_details(sync_result)
    return sync_result
def _run_qmt_post_close_bundle(
    *,
    db_path: str,
    qmt_dividend_type: str,
    host=None,
):
    provider = QMTProvider(dividend_type=qmt_dividend_type)
    stock_codes = _resolve_sync_stock_codes(provider, "", sync_all=True)

    host = host or st.empty()
    if hasattr(host, "empty"):
        host.empty()
    panel = host.container() if hasattr(host, "container") else host

    start_date = _post_close_sync_start_date()
    end_date = _today_date()
    panel.info(
        "准备执行收盘后一键回补："
        f"{len(stock_codes)} 只股票，范围 {start_date} -> {end_date}，周期 15m / 30m / 1h / 1d。"
    )

    results: dict[str, object] = {}
    for timeframe in ("15m", "30m", "1h", "1d"):
        panel.divider()
        panel.subheader(f"miniQMT {timeframe} 同步")
        results[timeframe] = _run_qmt_sync(
            db_path=db_path,
            stock_codes=stock_codes,
            sync_start=start_date,
            sync_end=end_date,
            sync_timeframe=timeframe,
            qmt_dividend_type=qmt_dividend_type,
            resume_from_latest_local=False,
            host=panel.container(),
        )

    panel.success("收盘后一键回补已全部执行完成。")
    return results


def render_sync_controls(db_path: str) -> None:
    st.subheader("同步 BaoStock 行情")
    baostock_output = st.empty()
    default_baostock_user_id, default_baostock_password = _load_baostock_credentials()
    sync_all_baostock = st.checkbox("同步全部股票", value=True, key="sync_all_baostock")
    with st.form("baostock_sync_form"):
        baostock_login_col1, baostock_login_col2 = st.columns(2)
        baostock_user_id = baostock_login_col1.text_input(
            "BaoStock 账号",
            value=default_baostock_user_id,
            key="baostock_user_id",
        )
        baostock_password = baostock_login_col2.text_input(
            "BaoStock 密码",
            value=default_baostock_password,
            type="password",
            key="baostock_password",
        )
        st.caption("BaoStock 账号和密码留空时，将自动使用匿名登录。")
        sync_codes = st.text_input("股票代码", "588000.SH", disabled=sync_all_baostock)
        sync_col1, sync_col2 = st.columns(2)
        sync_start = sync_col1.date_input("开始日期", value=date(2024, 1, 2), key="sync_start")
        sync_end = sync_col2.date_input("结束日期", value=_today_date(), key="sync_end")
        sync_col3, sync_col4, sync_col5, sync_col6 = st.columns(4)
        sync_timeframe = sync_col3.selectbox("K线周期", ["1d", "5m", "15m", "30m", "1h"])
        sync_workers = sync_col4.number_input(
            "并发数",
            min_value=BAOSTOCK_FIXED_SYNC_WORKERS,
            max_value=BAOSTOCK_FIXED_SYNC_WORKERS,
            value=BAOSTOCK_FIXED_SYNC_WORKERS,
            step=1,
            disabled=True,
            help="BaoStock 并发数已固定为 1，不可修改。",
        )
        sync_retries = sync_col5.number_input("重试次数", min_value=0, max_value=5, value=1, step=1, help="单只股票同步失败后的自动重试次数。")
        baostock_adjustflag = sync_col6.selectbox(
            "复权方式",
            ["2", "1", "3"],
            format_func=lambda value: {"2": "前复权", "1": "后复权", "3": "不复权"}[value],
            key="baostock_adjustflag",
        )
        st.caption("默认同步全部股票；如需补单只或少量股票，可取消勾选后手动输入代码。")
        sync_submitted = st.form_submit_button("同步到结束日期")
    if sync_submitted:
        provider = None
        try:
            _save_baostock_credentials(user_id=baostock_user_id, password=baostock_password)
            provider = BaoStockProvider(
                adjustflag=baostock_adjustflag,
                user_id=baostock_user_id,
                password=baostock_password,
            )
            stock_codes = _resolve_sync_stock_codes(provider, sync_codes, sync_all=sync_all_baostock)
            _run_baostock_sync(
                db_path=db_path,
                stock_codes=stock_codes,
                sync_start=sync_start,
                sync_end=sync_end,
                sync_timeframe=sync_timeframe,
                sync_workers=int(sync_workers),
                sync_retries=int(sync_retries),
                user_id=baostock_user_id,
                password=baostock_password,
                adjustflag=baostock_adjustflag,
                host=baostock_output.container(),
            )
        except Exception as exc:
            st.error(f"同步失败：{exc}")
        finally:
            if provider is not None:
                provider.logout()

    failed_codes = st.session_state.get("baostock_last_failed_codes", []) or []
    last_sync_config = st.session_state.get("baostock_last_sync_config")
    if failed_codes and last_sync_config:
        retry_cols = st.columns([1.2, 3.8])
        if retry_cols[0].button(f"仅重试失败股票 ({len(failed_codes)})", key="retry_failed_baostock_button", use_container_width=True):
            _run_baostock_sync(
                db_path=db_path,
                stock_codes=failed_codes,
                sync_start=last_sync_config["sync_start"],
                sync_end=last_sync_config["sync_end"],
                sync_timeframe=last_sync_config["sync_timeframe"],
                sync_workers=int(last_sync_config["sync_workers"]),
                sync_retries=int(last_sync_config["sync_retries"]),
                user_id=str(last_sync_config.get("user_id", default_baostock_user_id)),
                password=str(last_sync_config.get("password", default_baostock_password)),
                adjustflag=str(last_sync_config.get("adjustflag", "2")),
                host=baostock_output.container(),
            )
        retry_cols[1].caption(f"失败股票示例：{'、'.join(failed_codes[:10])}")

    st.caption("收盘后如果想从 2020-01-01 开始回补全 A 股历史，而不是只续传后面的新数据，可直接点击下面这个按钮。")
    if st.button(
        "收盘后一键回补 BaoStock（全A股 自2020-01-01 15m/30m/1h/1d）",
        key="baostock_post_close_bundle_button",
        use_container_width=True,
    ):
        try:
            _save_baostock_credentials(user_id=baostock_user_id, password=baostock_password)
            _run_baostock_post_close_bundle(
                db_path=db_path,
                user_id=baostock_user_id,
                password=baostock_password,
                adjustflag=baostock_adjustflag,
                sync_workers=int(sync_workers),
                sync_retries=int(sync_retries),
                host=baostock_output.container(),
            )
        except Exception as exc:
            st.error(f"收盘后一键同步失败：{exc}")

    st.divider()
    st.subheader("BaoStock 断点同步工具")
    st.caption("适合长时间补历史分钟线。你只需要选市场和输出周期，工具会自动决定先抓哪些低周期数据，再在本地升周期。")
    baostock_bulk_output = st.empty()
    with st.form("baostock_bulk_sync_form"):
        bulk_scope_mode = st.radio("范围选择", ["市场筛选", "指定股票"], horizontal=True, key="baostock_bulk_scope_mode")
        bulk_market_groups = st.multiselect(
            "市场",
            BAOSTOCK_BULK_MARKET_GROUP_ORDER,
            default=["all_a"],
            format_func=lambda value: MARKET_GROUP_LABELS.get(value, value),
            disabled=bulk_scope_mode != "市场筛选",
            key="baostock_bulk_market_groups",
        )
        bulk_codes = st.text_input("股票代码", "600000.SH,000001.SZ", disabled=bulk_scope_mode != "指定股票")
        bulk_stock_file = st.text_input("股票文件", "", help="可选：UTF-8 文本文件，支持按行或逗号分隔股票代码。", disabled=bulk_scope_mode != "指定股票")
        bulk_col1, bulk_col2 = st.columns(2)
        bulk_start = bulk_col1.date_input("断点工具开始日期", value=date(2020, 1, 2), key="baostock_bulk_start")
        bulk_end = bulk_col2.date_input("断点工具结束日期", value=_today_date(), key="baostock_bulk_end")
        bulk_selected_timeframes = st.multiselect(
            "输出周期",
            ["5m", "15m", "30m", "1h", "1d"],
            default=["5m", "15m", "30m", "1h", "1d"],
            help="选择你最终想写入本地库的周期。15m / 30m / 1h 会优先从 5m 本地派生。",
            key="baostock_bulk_output_timeframes",
        )
        planned_fetch_timeframes, planned_derive_source, planned_derive_timeframes = _resolve_baostock_timeframe_plan(bulk_selected_timeframes)
        st.caption(
            f"自动方案：直接抓取 `{planned_fetch_timeframes or '-'}`；"
            f" 派生源 `{planned_derive_source}`；"
            f" 本地派生 `{planned_derive_timeframes or '-'}`"
        )
        bulk_col6, bulk_col7 = st.columns(2)
        bulk_state_path = bulk_col6.text_input("状态文件", BAOSTOCK_BULK_SYNC_DEFAULT_STATE_PATH, key="baostock_bulk_state_path")
        bulk_allow_quality_issues = bulk_col7.checkbox("允许质量问题继续写入", value=False, key="baostock_bulk_allow_quality")
        bulk_reset_state = st.checkbox("重置状态文件后重新开始", value=False, key="baostock_bulk_reset_state")
        bulk_submitted = st.form_submit_button("启动 BaoStock 断点同步工具")

    bulk_state, bulk_summary = _summarize_baostock_bulk_state(bulk_state_path)
    if bulk_state is not None:
        st.caption(
            f"当前状态文件：{bulk_state_path} | 更新时间：{bulk_state.get('updated_at', '-')} | 总完成：{bulk_state.get('completed', False)}"
        )
        if not bulk_summary.empty:
            st.dataframe(bulk_summary, use_container_width=True, hide_index=True)

    if bulk_submitted:
        try:
            _save_baostock_credentials(user_id=baostock_user_id, password=baostock_password)
            if bulk_scope_mode == "市场筛选" and not bulk_market_groups:
                raise ValueError("请至少选择一个市场。")
            if bulk_scope_mode == "指定股票" and not bulk_codes.strip() and not bulk_stock_file.strip():
                raise ValueError("请至少填写股票代码，或提供股票文件。")
            _run_baostock_bulk_sync_tool(
                db_path=db_path,
                stock_codes_text=bulk_codes,
                stock_file=bulk_stock_file,
                sync_all=False,
                market_groups=bulk_market_groups if bulk_scope_mode == "市场筛选" else [],
                sync_start=bulk_start,
                sync_end=bulk_end,
                fetch_timeframes=planned_fetch_timeframes,
                derive_source_timeframe=planned_derive_source,
                derive_timeframes=planned_derive_timeframes,
                adjustflag=baostock_adjustflag,
                sync_retries=int(sync_retries),
                user_id=baostock_user_id,
                password=baostock_password,
                state_path=bulk_state_path,
                reset_state=bulk_reset_state,
                allow_quality_issues=bulk_allow_quality_issues,
                host=baostock_bulk_output.container(),
            )
        except Exception as exc:
            st.error(f"BaoStock 断点同步工具启动失败：{exc}")

    st.subheader("同步 miniQMT 行情")
    if st.button("测试 miniQMT 连接", key="qmt_connection_test_button"):
        try:
            info = QMTProvider().connection_info()
            st.success(
                "miniQMT 已连接："
                f"{info.get('peer_addr', '-')}"
                f" | 数据目录 {info.get('data_dir', '-')}"
            )
        except Exception as exc:
            st.error(f"miniQMT 连接失败：{exc}")

    sync_all_qmt = st.checkbox("同步全部股票", value=True, key="sync_all_qmt")
    with st.form("qmt_sync_form"):
        qmt_codes = st.text_input("股票代码", "600000.SH,000001.SZ", key="qmt_codes", disabled=sync_all_qmt)
        qmt_col1, qmt_col2 = st.columns(2)
        qmt_start = qmt_col1.date_input("开始日期", value=date(2026, 3, 1), key="qmt_sync_start")
        qmt_end = qmt_col2.date_input("结束日期", value=_today_date(), key="qmt_sync_end")
        qmt_col3, qmt_col4 = st.columns(2)
        qmt_timeframe = qmt_col3.selectbox("K线周期", ["1d", "1m", "5m", "15m", "30m", "1h"], key="qmt_timeframe")
        qmt_dividend_type = qmt_col4.selectbox(
            "复权方式",
            ["front", "back", "none"],
            format_func=lambda value: {"front": "前复权", "back": "后复权", "none": "不复权"}[value],
            key="qmt_dividend_type",
        )
        st.caption("默认同步全部股票；如需补单只或少量股票，可取消勾选后手动输入代码。")
        qmt_submitted = st.form_submit_button("同步 miniQMT 到结束日期")
    if qmt_submitted:
        try:
            provider = QMTProvider(dividend_type=qmt_dividend_type)
            stock_codes = _resolve_sync_stock_codes(provider, qmt_codes, sync_all=sync_all_qmt)
            _run_qmt_sync(
                db_path=db_path,
                stock_codes=stock_codes,
                sync_start=qmt_start,
                sync_end=qmt_end,
                sync_timeframe=qmt_timeframe,
                qmt_dividend_type=qmt_dividend_type,
                resume_from_latest_local=True,
            )
        except Exception as exc:
            st.error(f"miniQMT 同步失败：{exc}")

    st.caption("收盘后如果想从 2020-01-01 开始回补全 A 股历史，而不是只续后面的新数据，可直接点击下面这个按钮。")
    if st.button(
        "收盘后一键回补 miniQMT（全A股 自2020-01-01 15m/30m/1h/1d）",
        key="qmt_post_close_bundle_button",
        use_container_width=True,
    ):
        try:
            _run_qmt_post_close_bundle(
                db_path=db_path,
                qmt_dividend_type=qmt_dividend_type,
            )
        except Exception as exc:
            st.error(f"收盘后一键同步失败：{exc}")


def _display_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.rename(columns={column: COLUMN_LABELS.get(column, column) for column in df.columns})


def _load_db_runs(db_path: str) -> pd.DataFrame:
    store = _get_store(db_path)
    if store is None:
        return pd.DataFrame()
    try:
        return store.list_backtest_runs()
    except Exception:
        return pd.DataFrame()


def _selected_run_row(runs: pd.DataFrame, run_id: str | None) -> pd.Series | None:
    if run_id is None or runs.empty:
        return None
    matched = runs[runs["run_id"].astype(str) == str(run_id)]
    if matched.empty:
        return None
    return matched.iloc[0]


def _load_db_portfolio(db_path: str, run_id: str) -> pd.DataFrame:
    store = _get_store(db_path)
    if store is None:
        return pd.DataFrame()
    try:
        return store.get_run_portfolio_snapshots(run_id)
    except Exception:
        return pd.DataFrame()


def _load_db_trade_actions(db_path: str, run_id: str) -> pd.DataFrame:
    store = _get_store(db_path)
    if store is None:
        return pd.DataFrame()
    try:
        return store.get_run_trades(run_id)
    except Exception:
        return pd.DataFrame()


def _load_db_signals(db_path: str, run_id: str) -> pd.DataFrame:
    store = _get_store(db_path)
    if store is None:
        return pd.DataFrame()
    try:
        return store.get_run_signals(run_id)
    except Exception:
        return pd.DataFrame()


def _load_db_candidates(db_path: str, run_id: str) -> pd.DataFrame:
    store = _get_store(db_path)
    if store is None:
        return pd.DataFrame()
    try:
        return store.get_run_candidates(run_id)
    except Exception:
        return pd.DataFrame()


def _load_db_reviews(db_path: str, run_id: str) -> pd.DataFrame:
    store = _get_store(db_path)
    if store is None:
        return pd.DataFrame()
    try:
        return store.get_run_trade_reviews(run_id)
    except Exception:
        return pd.DataFrame()


def _load_db_screenshots(db_path: str, run_id: str) -> pd.DataFrame:
    store = _get_store(db_path)
    if store is None:
        return pd.DataFrame()
    try:
        return store.get_run_trade_screenshots(run_id)
    except Exception:
        return pd.DataFrame()


def _merge_primary_with_export(
    primary: pd.DataFrame,
    export_frame: pd.DataFrame,
    *,
    key_columns: Sequence[str],
) -> pd.DataFrame:
    if export_frame.empty:
        return primary
    if primary.empty:
        return export_frame.copy()

    merge_keys = [column for column in key_columns if column in primary.columns and column in export_frame.columns]
    if not merge_keys:
        return primary

    left = primary.copy()
    right = export_frame.copy()
    for frame in (left, right):
        for column in merge_keys:
            if "time" in column:
                frame[column] = pd.to_datetime(frame[column], errors="coerce")

    extra_columns = [column for column in right.columns if column not in left.columns and column not in merge_keys]
    fill_columns = [
        column
        for column in right.columns
        if column in left.columns and column not in merge_keys and left[column].isna().any()
    ]
    payload_columns = merge_keys + [column for column in [*extra_columns, *fill_columns] if column not in merge_keys]
    merged = left.merge(
        right[payload_columns].drop_duplicates(subset=merge_keys),
        on=merge_keys,
        how="left",
        suffixes=("", "__export"),
    )
    for column in fill_columns:
        export_column = f"{column}__export"
        if export_column not in merged.columns:
            continue
        merged[column] = merged[column].where(merged[column].notna(), merged[export_column])
        merged = merged.drop(columns=[export_column])
    return merged


def _build_strategy_event_frame(signals: pd.DataFrame, trade_actions: pd.DataFrame) -> pd.DataFrame:
    event_rows: list[dict[str, object]] = []

    if not signals.empty:
        signal_frame = signals.copy()
        if "signal_id" not in signal_frame.columns:
            signal_frame["signal_id"] = [f"signal_{idx + 1:04d}" for idx in range(len(signal_frame))]
        signal_frame["signal_time"] = pd.to_datetime(signal_frame.get("signal_time"), errors="coerce")
        if "entry_time" in signal_frame.columns:
            signal_frame["entry_time"] = pd.to_datetime(signal_frame["entry_time"], errors="coerce")
        signal_frame["entry_price"] = pd.to_numeric(signal_frame.get("entry_price"), errors="coerce")
        signal_frame["stop_loss"] = pd.to_numeric(signal_frame.get("stop_loss"), errors="coerce")

        for row in signal_frame.itertuples(index=False):
            event_rows.append(
                {
                    "event_id": getattr(row, "signal_id", None) or f"signal_{len(event_rows) + 1:04d}",
                    "event_type": "SIGNAL",
                    "stock_code": getattr(row, "stock_code", None),
                    "strategy_name": getattr(row, "strategy_name", None),
                    "timeframe": getattr(row, "timeframe", None),
                    "event_time": getattr(row, "signal_time", None),
                    "marker_price": getattr(row, "entry_price", None),
                    "stop_loss": getattr(row, "stop_loss", None),
                    "label": getattr(row, "reason", None),
                    "status": getattr(row, "status", None),
                }
            )

    if not trade_actions.empty:
        action_frame = trade_actions.copy()
        action_frame["trade_time"] = pd.to_datetime(action_frame.get("trade_time"), errors="coerce")
        action_frame["price"] = pd.to_numeric(action_frame.get("price"), errors="coerce")
        for row in action_frame.itertuples(index=False):
            action = str(getattr(row, "action", "") or "").upper()
            if action not in {"BUY", "SELL"}:
                continue
            event_rows.append(
                {
                    "event_id": f"{getattr(row, 'trade_id', '')}_{action}_{pd.Timestamp(getattr(row, 'trade_time')).strftime('%Y%m%d%H%M%S') if pd.notna(getattr(row, 'trade_time', None)) else len(event_rows)}",
                    "event_type": action,
                    "stock_code": getattr(row, "stock_code", None),
                    "strategy_name": getattr(row, "strategy_name", None),
                    "timeframe": getattr(row, "timeframe", None),
                    "event_time": getattr(row, "trade_time", None),
                    "marker_price": getattr(row, "price", None),
                    "stop_loss": None,
                    "label": getattr(row, "reason", None),
                    "status": None,
                }
            )

    if not event_rows:
        return pd.DataFrame(
            columns=[
                "event_id",
                "event_type",
                "stock_code",
                "strategy_name",
                "timeframe",
                "event_time",
                "marker_price",
                "stop_loss",
                "label",
                "status",
            ]
        )

    events = pd.DataFrame(event_rows)
    events["event_time"] = pd.to_datetime(events["event_time"], errors="coerce")
    events["marker_price"] = pd.to_numeric(events["marker_price"], errors="coerce")
    return events.dropna(subset=["stock_code", "event_time"]).sort_values(["event_time", "event_type"]).reset_index(drop=True)


def _format_strategy_event_label(event: pd.Series) -> str:
    event_time = pd.to_datetime(event.get("event_time"), errors="coerce")
    time_text = event_time.strftime("%Y-%m-%d %H:%M") if pd.notna(event_time) else "-"
    label = str(event.get("label", "") or "").strip()
    if len(label) > 24:
        label = label[:24] + "..."
    return f"{time_text} | {event.get('event_type', '-') } | {label or '-'}"


def _plot_strategy_run_chart(
    selected: pd.DataFrame,
    *,
    signal_events: pd.DataFrame,
    trade_events: pd.DataFrame,
    focus_time: pd.Timestamp | None = None,
    focus_stop_loss: float | None = None,
    bars_before: int = 120,
    bars_after: int = 60,
    indicators: Sequence[ChartIndicatorSpec] | None = None,
    chart_key: str = "strategy_run_chart",
) -> pd.DataFrame:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    indicators = tuple(indicators) if indicators is not None else load_default_price_overlay_indicators()
    frame = selected.sort_values("bar_time").copy()
    frame["bar_time"] = pd.to_datetime(frame["bar_time"], errors="coerce")
    frame = frame.dropna(subset=["bar_time"]).reset_index(drop=True)
    frame = add_price_overlay_indicators(frame, indicators)

    if frame.empty:
        return frame

    if focus_time is not None and pd.notna(focus_time):
        distances = (frame["bar_time"] - pd.Timestamp(focus_time)).abs()
        focus_index = int(distances.idxmin())
        start_index = max(0, focus_index - int(bars_before))
        end_index = min(len(frame), focus_index + int(bars_after) + 1)
        view = frame.iloc[start_index:end_index].copy()
    else:
        view = frame.tail(max(int(bars_before) + int(bars_after), 240)).copy()

    x_values = pd.to_datetime(view["bar_time"])
    volume_colors = build_kline_colors(view)
    view_start = x_values.min()
    view_end = x_values.max()

    def _clip_events(events: pd.DataFrame) -> pd.DataFrame:
        if events.empty:
            return events
        clipped = events.copy()
        clipped["event_time"] = pd.to_datetime(clipped["event_time"], errors="coerce")
        clipped["marker_price"] = pd.to_numeric(clipped["marker_price"], errors="coerce")
        return clipped.loc[
            clipped["event_time"].between(view_start, view_end, inclusive="both")
            & clipped["marker_price"].notna()
        ].copy()

    visible_signal_events = _clip_events(signal_events)
    visible_trade_events = _clip_events(trade_events)
    visible_buy_events = visible_trade_events[visible_trade_events["event_type"] == "BUY"].copy()
    visible_sell_events = visible_trade_events[visible_trade_events["event_type"] == "SELL"].copy()

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.76, 0.24],
    )
    fig.add_trace(
        go.Candlestick(
            x=x_values,
            open=view["open"],
            high=view["high"],
            low=view["low"],
            close=view["close"],
            name="K线",
            increasing_line_color=UP_COLOR,
            increasing_fillcolor=UP_COLOR,
            decreasing_line_color=DOWN_COLOR,
            decreasing_fillcolor=DOWN_COLOR,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=x_values,
            y=view["volume"],
            name="成交量",
            marker={"color": volume_colors},
            opacity=0.75,
        ),
        row=2,
        col=1,
    )
    for indicator in indicators:
        if indicator.column_name not in view.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=view[indicator.column_name],
                mode="lines",
                name=indicator.display_name,
                line={"color": indicator.color, "width": indicator.width},
            ),
            row=1,
            col=1,
        )

    if not visible_signal_events.empty:
        fig.add_trace(
            go.Scatter(
                x=visible_signal_events["event_time"],
                y=visible_signal_events["marker_price"],
                mode="markers",
                name="开仓信号",
                marker={"color": "#0ea5e9", "size": 12, "symbol": "star"},
                text=visible_signal_events["label"].fillna(""),
                hovertemplate="信号<br>%{x}<br>价格=%{y:.4f}<br>%{text}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    if not visible_buy_events.empty:
        fig.add_trace(
            go.Scatter(
                x=visible_buy_events["event_time"],
                y=visible_buy_events["marker_price"],
                mode="markers",
                name="开仓",
                marker={"color": "#dc2626", "size": 11, "symbol": "triangle-up"},
                text=visible_buy_events["label"].fillna(""),
                hovertemplate="开仓<br>%{x}<br>价格=%{y:.4f}<br>%{text}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    if not visible_sell_events.empty:
        fig.add_trace(
            go.Scatter(
                x=visible_sell_events["event_time"],
                y=visible_sell_events["marker_price"],
                mode="markers",
                name="平仓",
                marker={"color": "#16a34a", "size": 11, "symbol": "triangle-down"},
                text=visible_sell_events["label"].fillna(""),
                hovertemplate="平仓<br>%{x}<br>价格=%{y:.4f}<br>%{text}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    if focus_stop_loss is not None and pd.notna(focus_stop_loss):
        fig.add_hline(
            y=float(focus_stop_loss),
            line_dash="dash",
            line_color="#7c3aed",
            line_width=1.2,
            annotation_text="止损",
            annotation_position="top right",
            row=1,
            col=1,
        )

    fig.update_layout(
        height=760,
        margin={"l": 20, "r": 20, "t": 30, "b": 10},
        dragmode="pan",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "left", "x": 0},
    )
    fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        rangeslider_visible=False,
        row=1,
        col=1,
    )
    fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        rangeslider_visible=True,
        row=2,
        col=1,
    )
    fig.update_yaxes(title_text="价格", side="right", fixedrange=False, row=1, col=1)
    fig.update_yaxes(title_text="成交量", side="right", fixedrange=False, row=2, col=1, showgrid=False)
    st.plotly_chart(fig, width="stretch", key=chart_key)
    return view


def _plot_trade_chart(selected: pd.DataFrame, trade: pd.Series) -> None:
    import plotly.graph_objects as go
    return

    selected = selected.sort_values("bar_time").copy()
    x_values = pd.to_datetime(selected["bar_time"]).dt.strftime("%Y-%m-%d")
    volume_colors = [
        "#d14a61" if close_price >= open_price else "#1a9b5f"
        for open_price, close_price in zip(selected["open"], selected["close"])
    ]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=x_values,
            y=selected["volume"],
            name="成交量",
            marker={"color": volume_colors},
            yaxis="y2",
            opacity=0.75,
        )
    )
    fig.add_trace(
        go.Candlestick(
            x=x_values,
            open=selected["open"],
            high=selected["high"],
            low=selected["low"],
            close=selected["close"],
            name="日K",
            increasing_line_color="#d14a61",
            increasing_fillcolor="#d14a61",
            decreasing_line_color="#1a9b5f",
            decreasing_fillcolor="#1a9b5f",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[pd.Timestamp(trade["buy_time"]).strftime("%Y-%m-%d")],
            y=[trade["buy_price"]],
            mode="markers",
            name="买入",
            marker={"color": "#d14a61", "size": 12, "symbol": "triangle-up"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[pd.Timestamp(trade["sell_time"]).strftime("%Y-%m-%d")],
            y=[trade["sell_price"]],
            mode="markers",
            name="卖出",
            marker={"color": "#1a9b5f", "size": 12, "symbol": "triangle-down"},
        )
    )
    fig.update_layout(
        height=520,
        margin={"l": 20, "r": 20, "t": 30, "b": 20},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        xaxis={"title": "交易日", "type": "category", "rangeslider": {"visible": False}},
        yaxis={"title": "价格", "domain": [0.26, 1.0], "side": "right", "fixedrange": False},
        yaxis2={"title": "成交量", "domain": [0.0, 0.18], "side": "right", "fixedrange": False, "showgrid": False},
        bargap=0.12,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")


def _plot_kline_chart(
    selected: pd.DataFrame,
    *,
    display_points: int = 200,
    indicators: Sequence[ChartIndicatorSpec] | None = None,
) -> None:
    import plotly.graph_objects as go
    import streamlit as st

    indicators = tuple(indicators) if indicators is not None else load_default_price_overlay_indicators()
    selected = add_price_overlay_indicators(selected, indicators)
    if display_points > 0:
        selected = selected.tail(display_points).copy()
    else:
        selected = selected.copy()
    selected = selected.sort_values("bar_time")
    x_values = pd.to_datetime(selected["bar_time"]).dt.strftime("%Y-%m-%d")
    selected["is_limit_up"] = build_limit_up_mask(selected)
    volume_colors = build_kline_colors(selected)
    normal_bars = selected[~selected["is_limit_up"]]
    limit_up_bars = selected[selected["is_limit_up"]]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=x_values,
            y=selected["volume"],
            name="成交量",
            marker={"color": volume_colors},
            yaxis="y2",
            opacity=0.75,
        )
    )
    fig.add_trace(
        go.Candlestick(
            x=pd.to_datetime(normal_bars["bar_time"]).dt.strftime("%Y-%m-%d"),
            open=normal_bars["open"],
            high=normal_bars["high"],
            low=normal_bars["low"],
            close=normal_bars["close"],
            name="日K",
            increasing_line_color=UP_COLOR,
            increasing_fillcolor=UP_COLOR,
            decreasing_line_color=DOWN_COLOR,
            decreasing_fillcolor=DOWN_COLOR,
        )
    )
    if not limit_up_bars.empty:
        fig.add_trace(
            go.Candlestick(
                x=pd.to_datetime(limit_up_bars["bar_time"]).dt.strftime("%Y-%m-%d"),
                open=limit_up_bars["open"],
                high=limit_up_bars["high"],
                low=limit_up_bars["low"],
                close=limit_up_bars["close"],
                name="涨停",
                increasing_line_color=LIMIT_UP_COLOR,
                increasing_fillcolor=LIMIT_UP_COLOR,
                decreasing_line_color=LIMIT_UP_COLOR,
                decreasing_fillcolor=LIMIT_UP_COLOR,
            )
        )
    for indicator in indicators:
        if indicator.column_name not in selected.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=selected[indicator.column_name],
                mode="lines",
                name=indicator.display_name,
                line={"color": indicator.color, "width": indicator.width},
            )
        )
    fig.update_layout(
        height=520,
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
        xaxis={"title": "交易日期", "type": "category", "rangeslider": {"visible": False}},
        yaxis={"title": "价格", "domain": [0.26, 1.0], "side": "right", "fixedrange": False},
        yaxis2={"title": "成交量", "domain": [0.0, 0.18], "side": "right", "fixedrange": False, "showgrid": False},
        bargap=0.12,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")


def _selected_trade(trades: pd.DataFrame, label: str = "交易编号") -> pd.Series | None:
    import streamlit as st

    if trades.empty:
        return None
    trade_ids = trades["trade_id"].astype(str).tolist()
    selected_trade_id = st.selectbox(label, trade_ids)
    return trades[trades["trade_id"].astype(str) == selected_trade_id].iloc[0]


def _label_for_value(options: dict[str, str], value: str | None, default: str) -> str:
    for label, option_value in options.items():
        if option_value == value:
            return label
    return default


def _render_sidebar_help() -> None:
    import streamlit as st

    st.subheader("帮助与导航")
    st.caption("优先用这里，不用管系统默认英文按钮。")

    if hasattr(st, "page_link"):
        st.markdown("**主工作台**：当前页")
        st.page_link("pages/01_使用说明.py", label="使用说明")
        st.page_link("pages/02_数据同步.py", label="数据同步")
        st.page_link("pages/03_条件选股.py", label="条件选股")
        st.page_link("pages/04_连续复盘.py", label="连续复盘")
        st.page_link("pages/05_交易复核.py", label="交易复核")
        st.page_link("pages/06_问题归因.py", label="问题归因")

    with st.expander("推荐使用顺序", expanded=False):
        st.markdown(
            """
            1. 先做 `miniQMT 连接测试`
            2. 再做 `miniQMT 行情同步`
            3. 到 `条件选股` 页面先跑组合筛选
            4. 需要连续验证时，再运行日线复盘或 5 分钟复盘
            5. 最后到 `K线复核`、`人工验证` 做人工检查
            """
        )


def _build_navigation():
    return st.navigation(
        [
            st.Page(main, title="主工作台", default=True),
            st.Page("pages/01_使用说明.py", title="使用说明"),
            st.Page("pages/02_数据同步.py", title="数据同步"),
            st.Page("pages/03_条件选股.py", title="条件选股"),
            st.Page("pages/04_连续复盘.py", title="连续复盘"),
            st.Page("pages/05_交易复核.py", title="交易复核"),
            st.Page("pages/06_问题归因.py", title="问题归因"),
            st.Page("pages/07_自选观察.py", title="自选观察"),
        ],
        position="sidebar",
    )


def main() -> None:
    try:
        import streamlit as st
    except ModuleNotFoundError as exc:
        raise RuntimeError("streamlit is required for the UI. Run `pip install -e .`.") from exc

    st.set_option("client.toolbarMode", "minimal")
    st.set_page_config(page_title="Moneynosleep", layout="wide")
    st.title("主工作台")
    st.caption("复盘选股、快速回测、K线验证、人工复核。第一阶段不做真实自动交易。")

    with st.expander("这套界面怎么用"):
        st.markdown(
            """
            - 左侧 `streamlit app` 是主工作台，复盘、复核和结果查看主要都在这里
            - `数据同步` 页面负责执行行情同步，其余中文菜单负责解释每一块是什么、怎么使用
            - 推荐顺序：先连接和同步行情，再运行复盘，最后看交易和人工复核
            - 一键启动方式：双击项目根目录里的 `启动Moneynosleep.cmd`
            """
        )

    with st.container():
        pass
        pass
        st.header("数据面板")
        db_path = st.text_input("DuckDB", "data/duckdb/mns.duckdb")
        export_root = st.text_input("复盘导出目录", "data/reports/exports")
        db_runs = _load_db_runs(db_path)
        export_runs = _list_export_runs(export_root)
        run_options = db_runs["run_id"].astype(str).tolist() if not db_runs.empty else export_runs
        run_id = st.selectbox("复盘批次", run_options, index=0 if run_options else None, placeholder="暂无复盘结果")
        available_timeframes = _list_kline_timeframes(db_path)
        default_timeframe = "1d" if "1d" in available_timeframes else (available_timeframes[0] if available_timeframes else "1d")
        kline_timeframe = st.selectbox("行情展示周期", available_timeframes or [default_timeframe], index=0 if not available_timeframes or default_timeframe == (available_timeframes or [default_timeframe])[0] else (available_timeframes or [default_timeframe]).index(default_timeframe))
        st.caption("同步入口已移动到左侧 `数据同步` 页面；这里会自动读取本地同步结果。")

        with st.expander("运行快速复盘"):
            with st.form("daily_review_form"):
                review_col1, review_col2 = st.columns(2)
                review_start = review_col1.date_input("开始日期", value=date(2024, 1, 2), key="review_start")
                review_end = review_col2.date_input("结束日期", value=date(2024, 6, 28), key="review_end")
                as_of_date = st.date_input("选股日期", value=date(2024, 3, 26), key="as_of_date")
                volume_ratio_min = st.number_input("最低量比", min_value=0.0, value=0.0, step=0.1)
                hold_days = st.number_input("持有天数", min_value=1, max_value=60, value=5, step=1)
                fee_col1, fee_col2 = st.columns(2)
                commission_rate = fee_col1.number_input("佣金率", min_value=0.0, value=0.0003, step=0.0001, format="%.4f")
                stamp_tax_rate = fee_col2.number_input("印花税率", min_value=0.0, value=0.0010, step=0.0001, format="%.4f")
                fee_col3, fee_col4 = st.columns(2)
                transfer_fee_rate = fee_col3.number_input("过户费率", min_value=0.0, value=0.00001, step=0.00001, format="%.5f")
                slippage_rate = fee_col4.number_input("滑点率", min_value=0.0, value=0.0005, step=0.0001, format="%.4f")
                review_submitted = st.form_submit_button("运行复盘")
            if review_submitted:
                try:
                    with st.spinner("正在运行快速复盘..."):
                        result = DailyReviewRunner(
                            DailyReviewConfig(
                                db_path=db_path,
                                start_date=str(review_start),
                                end_date=str(review_end),
                                as_of_date=str(as_of_date),
                                volume_ratio_min=float(volume_ratio_min),
                                hold_days=int(hold_days),
                                commission_rate=float(commission_rate),
                                stamp_tax_rate=float(stamp_tax_rate),
                                transfer_fee_rate=float(transfer_fee_rate),
                                slippage_rate=float(slippage_rate),
                                export_root=export_root,
                            )
                        ).run()
                    st.success(
                        f"复盘完成：{len(result['candidates'])} 个候选，{len(result['signals'])} 条信号，{len(result['trades'])} 笔交易。"
                    )
                except Exception as exc:
                    st.error(f"复盘失败：{exc}")

        with st.expander("运行 5分钟回踩复盘"):
            with st.form("intraday_pullback_review_form"):
                intraday_codes = st.text_input("股票代码过滤", "600000.SH", key="intraday_codes")
                intraday_col1, intraday_col2 = st.columns(2)
                intraday_start = intraday_col1.date_input("开始日期", value=date(2026, 3, 2), key="intraday_review_start")
                intraday_end = intraday_col2.date_input("结束日期", value=date(2026, 3, 5), key="intraday_review_end")
                intraday_as_of = st.date_input("信号日期", value=date(2026, 3, 2), key="intraday_as_of")
                intraday_col3, intraday_col4 = st.columns(2)
                pullback_tolerance = intraday_col3.number_input("回踩容差", min_value=0.0, value=0.0030, step=0.0005, format="%.4f")
                atr_stop_multiple = intraday_col4.number_input("ATR止损倍数", min_value=0.1, value=1.0, step=0.1, format="%.1f")
                intraday_col5, intraday_col6 = st.columns(2)
                reward_multiple = intraday_col5.number_input("止盈倍数", min_value=0.5, value=2.0, step=0.5, format="%.1f")
                max_hold_bars = intraday_col6.number_input("最多持有K数", min_value=1, max_value=120, value=12, step=1)
                intraday_col7, intraday_col8 = st.columns(2)
                risk_per_trade = intraday_col7.number_input("单笔风险预算", min_value=0.0, value=5000.0, step=500.0)
                intraday_per_trade_cash = intraday_col8.number_input("单笔资金上限", min_value=1000.0, value=100000.0, step=1000.0)
                intraday_submitted = st.form_submit_button("运行 5分钟回踩复盘")
            if intraday_submitted:
                try:
                    with st.spinner("正在运行 5分钟回踩复盘..."):
                        result = IntradayPullbackReviewRunner(
                            IntradayPullbackReviewConfig(
                                db_path=db_path,
                                start_date=str(intraday_start),
                                end_date=str(intraday_end),
                                as_of_date=str(intraday_as_of),
                                stock_codes=[code.strip() for code in intraday_codes.split(",") if code.strip()] or None,
                                pullback_tolerance=float(pullback_tolerance),
                                atr_stop_multiple=float(atr_stop_multiple),
                                reward_multiple=float(reward_multiple),
                                max_hold_bars=int(max_hold_bars),
                                per_trade_cash=float(intraday_per_trade_cash),
                                risk_per_trade=float(risk_per_trade),
                                export_root=export_root,
                            )
                        ).run()
                    st.success(f"5分钟回踩复盘完成：{len(result['signals'])} 条信号，{len(result['trades'])} 笔交易。")
                except Exception as exc:
                    st.error(f"5分钟回踩复盘失败：{exc}")

    kline = _load_kline(db_path, timeframe=kline_timeframe)
    candidates = _load_db_candidates(db_path, run_id) if run_id else pd.DataFrame()
    if candidates.empty and run_id:
        candidates = _read_export(export_root, run_id, "candidates")
    signals = _load_db_signals(db_path, run_id) if run_id else pd.DataFrame()
    export_signals = _read_export(export_root, run_id, "signals") if run_id else pd.DataFrame()
    if signals.empty:
        signals = export_signals
    else:
        signals = _merge_primary_with_export(
            signals,
            export_signals,
            key_columns=("stock_code", "signal_time", "strategy_name", "action", "timeframe"),
        )
    trade_actions = _load_db_trade_actions(db_path, run_id) if run_id else pd.DataFrame()
    trades = pair_trade_actions(trade_actions)
    export_trades = _read_export(export_root, run_id, "trades") if run_id else pd.DataFrame()
    if trades.empty:
        trades = export_trades
    else:
        trades = _merge_primary_with_export(trades, export_trades, key_columns=("trade_id",))
    portfolio = _load_db_portfolio(db_path, run_id) if run_id else pd.DataFrame()
    if portfolio.empty and run_id:
        portfolio = _read_export(export_root, run_id, "portfolio")
    problems = _read_export(export_root, run_id, "problems") if run_id else pd.DataFrame()
    reviews = _load_db_reviews(db_path, run_id) if run_id else pd.DataFrame()
    screenshots = _load_db_screenshots(db_path, run_id) if run_id else pd.DataFrame()
    if problems.empty and not reviews.empty:
        problems = count_problem_tags(reviews)
    selected_run = _selected_run_row(db_runs, run_id)

    latest_trade_date = _get_latest_trade_date(db_path, kline_timeframe)

    metric_cols = st.columns(6)
    metric_cols[0].metric("行情行数", f"{len(kline):,}")
    metric_cols[1].metric("数据最新日期", latest_trade_date or "-")
    metric_cols[2].metric("候选股", f"{len(candidates):,}")
    metric_cols[3].metric("信号", f"{len(signals):,}")
    metric_cols[4].metric("交易", f"{len(trades):,}")
    final_equity = portfolio["total_equity"].iloc[-1] if not portfolio.empty and "total_equity" in portfolio else None
    metric_cols[5].metric("期末权益", _metric_value(final_equity))

    tabs = st.tabs(["行情数据", "资金复盘", "候选与信号", "交易列表", "策略图谱", "人工验证", "问题归因"])

    with tabs[0]:
        if kline.empty:
            st.info("暂无本地行情。可先运行 `mns sync-qmt-kline ...`、`mns sync-baostock-kline ...` 或 `mns sync-csv-kline ...`。")
        else:
            left, right = st.columns([1, 2])
            codes = sorted(kline["stock_code"].dropna().unique().tolist())
            selected_code = left.selectbox("股票代码", codes)
            left.caption(f"当前周期：{kline_timeframe}")
            available_chart_indicators = available_price_overlay_indicators()
            default_chart_indicators = load_default_price_overlay_indicators()
            selected_indicator_names = left.multiselect(
                "显示指标",
                options=indicator_display_names(available_chart_indicators),
                default=indicator_display_names(default_chart_indicators),
                key="main_kline_chart_indicators",
            )
            chart_indicators = resolve_price_overlay_indicators(selected_indicator_names)
            selected = kline[kline["stock_code"] == selected_code].sort_values("bar_time")
            with right:
                _plot_kline_chart(selected, display_points=200, indicators=chart_indicators)
            st.dataframe(_display_df(selected.tail(200)), use_container_width=True)

    with tabs[1]:
        if portfolio.empty:
            if selected_run is not None:
                result_json = str(selected_run.get("result_json", ""))
                config_json = str(selected_run.get("config_json", ""))
                if '"trade_count": 0' in result_json:
                    st.info("当前批次没有形成成交，因此不会生成资金曲线。常见原因是选股日太靠近数据末尾，后面没有足够K线完成持有期。")
                    st.caption(f"当前批次：{selected_run['run_id']} | 结束日期：{selected_run['end_date']} | 配置：{config_json}")
                else:
                    st.info("当前批次暂无资金曲线数据。")
            else:
                st.info("暂无资金曲线。运行 `mns run-daily-review ...` 后展示。")
        else:
            st.line_chart(portfolio, x="snapshot_time", y="total_equity")
            st.dataframe(_display_df(portfolio), use_container_width=True)

    with tabs[2]:
        st.subheader("候选股")
        st.dataframe(_display_df(candidates), use_container_width=True)
        st.subheader("策略信号")
        st.dataframe(_display_df(signals), use_container_width=True)

    with tabs[3]:
        if trades.empty:
            if selected_run is not None:
                st.info("当前批次暂无交易明细。若已有候选股和信号，通常表示选股日后没有足够未来K线完成回测持有期。")
            else:
                st.info("暂无交易明细。")
        else:
            if not db_runs.empty and run_id:
                run_row = db_runs[db_runs["run_id"].astype(str) == str(run_id)]
                if not run_row.empty:
                    st.caption(
                        f"回测类型={run_row.iloc[0]['run_type']}  开始={run_row.iloc[0]['start_date']}  结束={run_row.iloc[0]['end_date']}"
                    )
            st.dataframe(_display_df(trades), use_container_width=True)

    with tabs[4]:
        event_frame = _build_strategy_event_frame(signals, trade_actions)
        if event_frame.empty or kline.empty:
            st.info("有本地 K 线和回测信号后，这里会展示可拖动的策略图谱，包括开仓信号、开仓成交和平仓成交。")
        else:
            signal_events = event_frame[event_frame["event_type"] == "SIGNAL"].copy()
            trade_events = event_frame[event_frame["event_type"].isin(["BUY", "SELL"])].copy()
            if signal_events.empty and trade_events.empty:
                st.info("当前批次还没有可展示的策略事件。")
            else:
                available_codes = sorted(event_frame["stock_code"].dropna().astype(str).unique().tolist())
                if not available_codes:
                    st.info("当前批次没有可展示的股票代码。")
                else:
                    selector_col1, selector_col2, selector_col3 = st.columns([1.2, 1.2, 1.6])
                    default_code = None
                    if not signal_events.empty:
                        default_code = str(signal_events.iloc[0]["stock_code"])
                    elif not trade_events.empty:
                        default_code = str(trade_events.iloc[0]["stock_code"])
                    default_index = available_codes.index(default_code) if default_code in available_codes else 0
                    selected_code = selector_col1.selectbox("股票代码", available_codes, index=default_index, key="strategy_chart_code")
                    event_mode = selector_col2.selectbox(
                        "事件视图",
                        ["全部", "开仓信号", "仅看开仓", "仅看平仓"],
                        key="strategy_chart_event_mode",
                    )

                    code_signal_events = signal_events[signal_events["stock_code"].astype(str) == selected_code].copy()
                    code_trade_events = trade_events[trade_events["stock_code"].astype(str) == selected_code].copy()
                    code_kline = kline[kline["stock_code"].astype(str) == selected_code].sort_values("bar_time").copy()

                    signal_timeframe = None
                    if not code_signal_events.empty and "timeframe" in code_signal_events.columns:
                        timeframe_values = code_signal_events["timeframe"].dropna().astype(str).unique().tolist()
                        if timeframe_values:
                            signal_timeframe = timeframe_values[0]
                    selector_col3.caption(
                        f"当前K线周期: {kline_timeframe}" + (f" | 信号周期: {signal_timeframe}" if signal_timeframe else "")
                    )
                    if signal_timeframe and str(signal_timeframe) != str(kline_timeframe):
                        st.warning(f"当前页面 K 线周期是 {kline_timeframe}，这批信号记录周期是 {signal_timeframe}，建议切到一致周期后再看图。")

                    if event_mode == "开仓信号":
                        focus_candidates = code_signal_events.copy()
                    elif event_mode == "仅看开仓":
                        focus_candidates = code_trade_events[code_trade_events["event_type"] == "BUY"].copy()
                    elif event_mode == "仅看平仓":
                        focus_candidates = code_trade_events[code_trade_events["event_type"] == "SELL"].copy()
                    else:
                        focus_candidates = pd.concat([code_signal_events, code_trade_events], ignore_index=True)
                    focus_candidates = focus_candidates.sort_values("event_time").reset_index(drop=True)

                    if code_kline.empty:
                        st.info("当前股票在本地还没有对应周期的 K 线数据。")
                    elif focus_candidates.empty and event_mode != "全部":
                        st.info("当前筛选条件下没有事件。")
                    else:
                        focus_options = ["最新窗口"]
                        focus_index = 0
                        if not focus_candidates.empty:
                            focus_options.extend([_format_strategy_event_label(row) for _, row in focus_candidates.iterrows()])
                            focus_index = len(focus_options) - 1
                        selected_focus = st.selectbox(
                            "聚焦事件",
                            focus_options,
                            index=focus_index,
                            key="strategy_chart_focus_event",
                        )

                        window_col1, window_col2 = st.columns(2)
                        bars_before = window_col1.slider("前看K线数", min_value=40, max_value=400, value=120, step=20, key="strategy_chart_bars_before")
                        bars_after = window_col2.slider("后看K线数", min_value=20, max_value=240, value=60, step=10, key="strategy_chart_bars_after")

                        available_chart_indicators = available_price_overlay_indicators()
                        default_chart_indicators = load_default_price_overlay_indicators()
                        selected_indicator_names = st.multiselect(
                            "叠加指标",
                            options=indicator_display_names(available_chart_indicators),
                            default=indicator_display_names(default_chart_indicators),
                            key="strategy_run_chart_indicators",
                        )
                        chart_indicators = resolve_price_overlay_indicators(selected_indicator_names)

                        focus_time = None
                        focus_stop_loss = None
                        if selected_focus != "最新窗口" and not focus_candidates.empty:
                            selected_idx = focus_options.index(selected_focus) - 1
                            focus_event = focus_candidates.iloc[selected_idx]
                            focus_time = pd.to_datetime(focus_event.get("event_time"), errors="coerce")
                            focus_stop_loss = pd.to_numeric(focus_event.get("stop_loss"), errors="coerce")

                        visible_frame = _plot_strategy_run_chart(
                            code_kline,
                            signal_events=code_signal_events,
                            trade_events=code_trade_events,
                            focus_time=focus_time,
                            focus_stop_loss=focus_stop_loss if pd.notna(focus_stop_loss) else None,
                            bars_before=bars_before,
                            bars_after=bars_after,
                            indicators=chart_indicators,
                            chart_key=f"strategy_run_chart_{selected_code}_{kline_timeframe}",
                        )

                        if not visible_frame.empty:
                            visible_start = pd.to_datetime(visible_frame["bar_time"]).min()
                            visible_end = pd.to_datetime(visible_frame["bar_time"]).max()
                            visible_signal_events = code_signal_events[
                                pd.to_datetime(code_signal_events["event_time"], errors="coerce").between(visible_start, visible_end, inclusive="both")
                            ].copy()
                            visible_trade_events = code_trade_events[
                                pd.to_datetime(code_trade_events["event_time"], errors="coerce").between(visible_start, visible_end, inclusive="both")
                            ].copy()

                            metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
                            metric_col1.metric("当前窗口K线", f"{len(visible_frame):,}")
                            metric_col2.metric("开仓信号", f"{len(visible_signal_events):,}")
                            metric_col3.metric("开仓成交", f"{len(visible_trade_events[visible_trade_events['event_type'] == 'BUY']):,}")
                            metric_col4.metric("平仓成交", f"{len(visible_trade_events[visible_trade_events['event_type'] == 'SELL']):,}")

                            detail_tabs = st.tabs(["可见信号", "可见成交", "当前K线"])
                            with detail_tabs[0]:
                                st.dataframe(_display_df(visible_signal_events), use_container_width=True)
                            with detail_tabs[1]:
                                st.dataframe(_display_df(visible_trade_events), use_container_width=True)
                            with detail_tabs[2]:
                                st.dataframe(_display_df(visible_frame), use_container_width=True)

                    if not screenshots.empty:
                        st.subheader("已导出截图")
                        st.dataframe(_display_df(screenshots), use_container_width=True)

    with tabs[5]:
        if not run_id or trades.empty:
            st.info("暂无可复核交易。")
        else:
            trade = _selected_trade(trades, "复核交易")
            existing = pd.DataFrame()
            if not reviews.empty:
                existing = reviews[reviews["trade_id"].astype(str) == str(trade["trade_id"])]
            existing_row = existing.iloc[0] if not existing.empty else None

            with st.form("trade_review_form"):
                col1, col2, col3 = st.columns(3)
                status_label = col1.selectbox(
                    "复核状态",
                    list(REVIEW_STATUS_OPTIONS.keys()),
                    index=list(REVIEW_STATUS_OPTIONS.keys()).index(
                        _label_for_value(
                            REVIEW_STATUS_OPTIONS,
                            existing_row["review_status"] if existing_row is not None else None,
                            "待复核",
                        )
                    ),
                )
                buy_label = col2.selectbox(
                    "买点评级",
                    list(BUY_RATING_OPTIONS.keys()),
                    index=list(BUY_RATING_OPTIONS.keys()).index(
                        _label_for_value(
                            BUY_RATING_OPTIONS,
                            existing_row["buy_point_rating"] if existing_row is not None else None,
                            "可接受",
                        )
                    ),
                )
                sell_label = col3.selectbox(
                    "卖点评级",
                    list(SELL_RATING_OPTIONS.keys()),
                    index=list(SELL_RATING_OPTIONS.keys()).index(
                        _label_for_value(
                            SELL_RATING_OPTIONS,
                            existing_row["sell_point_rating"] if existing_row is not None else None,
                            "好卖点",
                        )
                    ),
                )
                col4, col5, col6 = st.columns(3)
                risk_label = col4.selectbox("风控评价", list(RATING_OPTIONS.keys()))
                market_label = col5.selectbox("市场环境", list(RATING_OPTIONS.keys()))
                sector_label = col6.selectbox("板块环境", list(RATING_OPTIONS.keys()))
                existing_tags = []
                if existing_row is not None and pd.notna(existing_row["problem_tags"]):
                    existing_tags = [tag.strip() for tag in str(existing_row["problem_tags"]).split(",") if tag.strip()]
                problem_tags = st.multiselect("问题标签", PROBLEM_TAG_OPTIONS, default=existing_tags)
                reviewed_by = st.text_input(
                    "复核人",
                    value=str(existing_row["reviewed_by"]) if existing_row is not None and pd.notna(existing_row["reviewed_by"]) else "trader",
                )
                manual_note = st.text_area(
                    "人工复核笔记",
                    value=str(existing_row["manual_note"]) if existing_row is not None and pd.notna(existing_row["manual_note"]) else "",
                )
                submitted = st.form_submit_button("保存复核")

            if submitted:
                store = _get_store(db_path)
                if store is None:
                    st.error("找不到 DuckDB 数据库。")
                else:
                    review = TradeReview(
                        trade_id=str(trade["trade_id"]),
                        run_id=str(run_id),
                        stock_code=str(trade["stock_code"]),
                        review_status=REVIEW_STATUS_OPTIONS[status_label],
                        buy_point_rating=BUY_RATING_OPTIONS[buy_label],
                        sell_point_rating=SELL_RATING_OPTIONS[sell_label],
                        risk_control_rating=RATING_OPTIONS[risk_label],
                        market_context_rating=RATING_OPTIONS[market_label],
                        sector_context_rating=RATING_OPTIONS[sector_label],
                        manual_note=manual_note,
                        problem_tags=",".join(problem_tags),
                        reviewed_by=reviewed_by,
                    )
                    store.replace_trade_review(review.to_record())
                    st.success("复核已保存。")

            if not reviews.empty:
                st.subheader("已保存复核")
                st.dataframe(_display_df(reviews), use_container_width=True)

    with tabs[6]:
        if problems.empty:
            st.info("暂无问题归因数据。人工复核数据落库后展示统计。")
        else:
            st.dataframe(_display_df(problems), use_container_width=True)


if __name__ == "__main__":
    main()
