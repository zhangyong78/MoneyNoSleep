from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.intraday_resample import can_resample_timeframe, resample_kline_frame
from mns.data.local_data import LocalMarketData
from mns.data.market_scope import filter_stock_codes_by_market_groups, normalize_market_groups
from mns.data.parquet_store import ParquetStore
from mns.data.providers.baostock_provider import BaoStockProvider
from mns.data.sync import DailyKlineSyncService
from mns.data.timeframes import normalize_timeframe, timeframe_aliases


@dataclass
class StockSummary:
    phase: str
    timeframe: str
    stock_code: str
    status: str
    rows_written: int
    quality_issue_count: int
    parquet_file_count: int
    latest_trade_date: str | None
    message: str


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _print(message: str) -> None:
    print(f"[{_now_text()}] {message}", flush=True)


def _normalize_stock_code(value: str) -> str:
    raw = str(value).strip()
    if not raw:
        raise ValueError("stock code cannot be empty")
    uppered = raw.upper()
    if uppered.endswith((".SH", ".SZ", ".BJ")) and "." in uppered:
        return uppered
    lowered = raw.lower()
    if lowered.startswith(("sh.", "sz.", "bj.")) and len(lowered) >= 9:
        return f"{lowered[3:9]}.{lowered[:2].upper()}"

    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 6:
        return uppered
    if digits.startswith(("5", "6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _parse_text_list(text: str) -> list[str]:
    if not text.strip():
        return []
    return [item.strip() for item in text.replace("\n", ",").split(",") if item.strip()]


def _load_stock_codes(*, stock_codes_text: str, stock_file: str, sync_all: bool, provider: BaoStockProvider) -> list[str]:
    return _load_stock_codes_with_market_groups(
        stock_codes_text=stock_codes_text,
        stock_file=stock_file,
        sync_all=sync_all,
        market_groups=[],
        provider=provider,
    )


def _load_stock_codes_with_market_groups(
    *,
    stock_codes_text: str,
    stock_file: str,
    sync_all: bool,
    market_groups: list[str],
    provider: BaoStockProvider,
) -> list[str]:
    normalized_groups = normalize_market_groups(market_groups)
    if sync_all or normalized_groups:
        stock_frame = provider.get_stock_list()
        available_codes = stock_frame["stock_code"].dropna().astype(str).map(_normalize_stock_code).tolist()
        if normalized_groups:
            return sorted(filter_stock_codes_by_market_groups(available_codes, normalized_groups))
        return sorted(filter_stock_codes_by_market_groups(available_codes, ["all_a"]))

    items = _parse_text_list(stock_codes_text)
    if stock_file.strip():
        items.extend(_parse_text_list(Path(stock_file).read_text(encoding="utf-8")))
    return sorted(dict.fromkeys(_normalize_stock_code(item) for item in items))


def _load_or_create_state(state_path: Path, *, run_config: dict, reset_state: bool = False) -> tuple[dict, bool]:
    if reset_state and state_path.exists():
        state_path.unlink()

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        config_mismatch = state.get("run_config") != run_config
        if config_mismatch:
            previous_run_config = state.get("run_config", {})
            history = state.setdefault("run_config_history", [])
            if previous_run_config:
                history.append(
                    {
                        "migrated_at": _now_text(),
                        "run_config": previous_run_config,
                    }
                )
                state["run_config_history"] = history[-20:]
            state["run_config"] = run_config
            state["completed"] = False
        return state, config_mismatch

    state = {
        "created_at": _now_text(),
        "updated_at": _now_text(),
        "run_config": run_config,
        "phases": {},
        "completed": False,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")
    return state, False


def _save_state(state_path: Path, state: dict) -> None:
    state["updated_at"] = _now_text()
    state_path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def _phase_state(state: dict, *, phase: str, timeframe: str) -> dict:
    return state.setdefault("phases", {}).setdefault(phase, {}).setdefault(
        timeframe,
        {
            "completed_stock_codes": [],
            "summaries": [],
            "completed": False,
        },
    )


def _append_summary(phase_state: dict, summary: StockSummary, *, completed: bool) -> None:
    phase_state.setdefault("summaries", []).append(asdict(summary))
    if completed:
        phase_state.setdefault("completed_stock_codes", []).append(summary.stock_code)


def _ordered_codes(stock_codes: list[str], selected: set[str]) -> list[str]:
    return [stock_code for stock_code in stock_codes if stock_code in selected]


def _latest_phase_status_by_stock(phase_state: dict, *, valid_stock_codes: list[str]) -> dict[str, str]:
    valid_set = set(valid_stock_codes)
    statuses: dict[str, str] = {}
    for item in phase_state.get("summaries", []):
        stock_code = str(item.get("stock_code") or "").strip()
        if stock_code and stock_code in valid_set:
            statuses[stock_code] = str(item.get("status") or "")
    return statuses


def _inspect_local_timeframe_coverage(
    *,
    store: DuckDBStore,
    timeframe: str,
    stock_codes: list[str],
    start_time: datetime,
    end_time: datetime,
) -> dict[str, dict[str, object]]:
    if not stock_codes:
        return {}

    start_date = pd.Timestamp(start_time).date()
    end_date = pd.Timestamp(end_time).date()
    frame = store.query_frame(
        """
        SELECT
            stock_code,
            COUNT(*) AS total_rows,
            SUM(CASE WHEN trade_date >= ? AND trade_date <= ? THEN 1 ELSE 0 END) AS range_rows,
            MIN(trade_date) AS first_trade_date,
            MAX(trade_date) AS latest_trade_date
        FROM kline_bars
        WHERE timeframe IN (SELECT UNNEST(?))
          AND stock_code IN (SELECT UNNEST(?))
        GROUP BY stock_code
        """,
        (start_date, end_date, list(timeframe_aliases(timeframe)), stock_codes),
    )
    coverage: dict[str, dict[str, object]] = {}
    for _, row in frame.iterrows():
        first_trade_date = pd.to_datetime(row.get("first_trade_date"), errors="coerce")
        latest_trade_date = pd.to_datetime(row.get("latest_trade_date"), errors="coerce")
        has_full_range = (
            int(row.get("range_rows") or 0) > 0
            and not pd.isna(first_trade_date)
            and not pd.isna(latest_trade_date)
            and first_trade_date.date() <= start_date
            and latest_trade_date.date() >= end_date
        )
        stock_code = str(row["stock_code"])
        coverage[stock_code] = {
            "has_full_range": has_full_range,
            "total_rows": int(row.get("total_rows") or 0),
            "range_rows": int(row.get("range_rows") or 0),
            "first_trade_date": None if pd.isna(first_trade_date) else first_trade_date.strftime("%Y-%m-%d"),
            "latest_trade_date": None if pd.isna(latest_trade_date) else latest_trade_date.strftime("%Y-%m-%d"),
        }
    return coverage


def _reconcile_phase_progress(
    *,
    phase_state: dict,
    phase: str,
    timeframe: str,
    stock_codes: list[str],
    store: DuckDBStore,
    start_time: datetime,
    end_time: datetime,
) -> tuple[list[str], set[str], set[str]]:
    existing_completed = {
        str(stock_code)
        for stock_code in phase_state.get("completed_stock_codes", [])
        if str(stock_code) in set(stock_codes)
    }
    local_coverage = _inspect_local_timeframe_coverage(
        store=store,
        timeframe=timeframe,
        stock_codes=stock_codes,
        start_time=start_time,
        end_time=end_time,
    )
    local_completed = {
        stock_code for stock_code, payload in local_coverage.items() if bool(payload.get("has_full_range"))
    }

    preserved_state_only: set[str] = set()
    if phase == "fetch":
        latest_statuses = _latest_phase_status_by_stock(phase_state, valid_stock_codes=stock_codes)
        preserved_state_only = {
            stock_code
            for stock_code, status in latest_statuses.items()
            if stock_code in existing_completed and status in {"empty", "skipped"}
        }

    completed = local_completed | preserved_state_only
    phase_state["completed_stock_codes"] = _ordered_codes(stock_codes, completed)
    phase_state["completed"] = len(completed) >= len(stock_codes)
    pending = [stock_code for stock_code in stock_codes if stock_code not in completed]
    return pending, local_completed, preserved_state_only


def _write_kline_frame(
    *,
    frame: pd.DataFrame,
    timeframe: str,
    store: DuckDBStore,
    parquet_store: ParquetStore,
) -> tuple[int, int]:
    if frame.empty:
        return 0, 0
    store.initialize()
    rows_written = store.replace_kline_bars(frame)
    parquet_files = 0
    for trade_date, daily in frame.groupby("trade_date"):
        parquet_store.write_kline(daily.reset_index(drop=True), timeframe=timeframe, trade_date=str(trade_date))
        parquet_files += 1
    return rows_written, parquet_files


def _summarize_sync_result(*, phase: str, timeframe: str, stock_code: str, result) -> StockSummary:
    if getattr(result, "failed_stock_codes", []):
        status = "failed"
        message = "sync failed"
    elif getattr(result, "skipped_stock_codes", []):
        status = "skipped"
        message = "already completed in prior run"
    elif getattr(result, "empty_stock_codes", []):
        status = "empty"
        message = "no data returned"
    else:
        status = "synced"
        message = "ok"
    return StockSummary(
        phase=phase,
        timeframe=timeframe,
        stock_code=stock_code,
        status=status,
        rows_written=int(getattr(result, "rows_written", 0) or 0),
        quality_issue_count=int(getattr(result, "quality_issue_count", 0) or 0),
        parquet_file_count=len(getattr(result, "parquet_files", []) or []),
        latest_trade_date=getattr(result, "latest_trade_date", None),
        message=message,
    )


def _sync_raw_timeframe(
    *,
    stock_code: str,
    timeframe: str,
    start_time: datetime,
    end_time: datetime,
    db_path: str,
    parquet_root: str,
    adjustflag: str,
    user_id: str,
    password: str,
    max_retries: int,
    allow_quality_issues: bool,
) -> StockSummary:
    last_event: dict[str, str] = {"status": "", "message": ""}

    def _capture_progress(event) -> None:
        last_event["status"] = str(event.status)
        last_event["message"] = str(event.message or "")

    service = DailyKlineSyncService(
        provider=BaoStockProvider(
            adjustflag=adjustflag,
            user_id=user_id,
            password=password,
        ),
        provider_factory=lambda: BaoStockProvider(
            adjustflag=adjustflag,
            user_id=user_id,
            password=password,
        ),
        duckdb_store=DuckDBStore(db_path),
        parquet_store=ParquetStore(parquet_root),
        strict_quality=not allow_quality_issues,
        max_workers=1,
        max_retries=max_retries,
    )
    result = service.sync(
        stock_codes=[stock_code],
        start_time=start_time,
        end_time=end_time,
        timeframe=timeframe,
        resume_from_latest_local=False,
        progress_callback=_capture_progress,
    )
    summary = _summarize_sync_result(phase="fetch", timeframe=timeframe, stock_code=stock_code, result=result)
    if summary.status == "failed" and last_event["message"]:
        summary.message = last_event["message"]
    elif summary.status == "synced" and last_event["message"]:
        summary.message = last_event["message"]
    return summary


def _derive_timeframe(
    *,
    stock_code: str,
    source_timeframe: str,
    target_timeframe: str,
    start_time: datetime,
    end_time: datetime,
    db_path: str,
    parquet_root: str,
) -> StockSummary:
    store = DuckDBStore(db_path)
    frame = LocalMarketData(store).get_kline(
        timeframe=source_timeframe,
        start_date=start_time.date(),
        end_date=end_time.date(),
        stock_codes=[stock_code],
    )
    if frame.empty:
        return StockSummary(
            phase="derive",
            timeframe=target_timeframe,
            stock_code=stock_code,
            status="empty",
            rows_written=0,
            quality_issue_count=0,
            parquet_file_count=0,
            latest_trade_date=None,
            message=f"source timeframe {source_timeframe} not found locally",
        )

    frame["bar_time"] = pd.to_datetime(frame["bar_time"], errors="coerce")
    frame = frame.loc[(frame["bar_time"] >= pd.Timestamp(start_time)) & (frame["bar_time"] <= pd.Timestamp(end_time))].reset_index(drop=True)
    if frame.empty:
        return StockSummary(
            phase="derive",
            timeframe=target_timeframe,
            stock_code=stock_code,
            status="empty",
            rows_written=0,
            quality_issue_count=0,
            parquet_file_count=0,
            latest_trade_date=None,
            message="source bars outside requested time range",
        )

    resampled = resample_kline_frame(
        frame,
        source_timeframe=source_timeframe,
        target_timeframe=target_timeframe,
        source_label=f"baostock_resampled_from_{normalize_timeframe(source_timeframe)}",
    )
    rows_written, parquet_file_count = _write_kline_frame(
        frame=resampled,
        timeframe=target_timeframe,
        store=store,
        parquet_store=ParquetStore(parquet_root),
    )
    latest_trade_date = None if resampled.empty else str(pd.to_datetime(resampled["trade_date"], errors="coerce").max().date())
    return StockSummary(
        phase="derive",
        timeframe=target_timeframe,
        stock_code=stock_code,
        status="synced" if rows_written else "empty",
        rows_written=rows_written,
        quality_issue_count=0,
        parquet_file_count=parquet_file_count,
        latest_trade_date=latest_trade_date,
        message=f"derived from {source_timeframe}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bulk sync BaoStock K-line data with resumable stock-level checkpoints and local timeframe derivation."
    )
    parser.add_argument("--db", default="data/duckdb/mns.duckdb")
    parser.add_argument("--parquet-root", default="data/parquet")
    parser.add_argument("--stock-codes", default="", help="Comma-separated stock codes, e.g. 600000.SH,000001.SZ.")
    parser.add_argument("--stock-file", default="", help="Optional UTF-8 text file with comma-separated or line-separated stock codes.")
    parser.add_argument("--sync-all", action="store_true", help="Use BaoStock stock list and sync all available A-shares.")
    parser.add_argument("--market-groups", default="", help="Optional market groups, e.g. all_a,sh_a,sz_a,sh_etf,sz_etf.")
    parser.add_argument("--start", required=True, help="Start time, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")
    parser.add_argument("--end", required=True, help="End time, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")
    parser.add_argument("--fetch-timeframes", default="5m,1d", help="Raw BaoStock timeframes to fetch from the server.")
    parser.add_argument("--derive-source-timeframe", default="5m", help="Lower timeframe used as the source for local resampling.")
    parser.add_argument("--derive-timeframes", default="15m,30m,1h", help="Higher timeframes derived from the source timeframe.")
    parser.add_argument("--adjustflag", default="2", help="BaoStock adjustment flag: 1 back adjusted, 2 front adjusted, 3 raw.")
    parser.add_argument("--user-id", default=os.getenv("MNS_BAOSTOCK_USER_ID", ""), help="Optional BaoStock user id. Leave blank for anonymous login.")
    parser.add_argument("--password", default=os.getenv("MNS_BAOSTOCK_PASSWORD", ""), help="Optional BaoStock password. Leave blank for anonymous login.")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--state-path", default="data/logs/baostock_bulk_sync_state.json")
    parser.add_argument("--reset-state", action="store_true", help="Delete the existing state file first and start this sync from scratch.")
    parser.add_argument("--log-stock-sample", type=int, default=10)
    parser.add_argument("--allow-quality-issues", action="store_true")
    args = parser.parse_args(argv)

    start_time = datetime.fromisoformat(args.start)
    end_time = datetime.fromisoformat(args.end)
    state_path = Path(args.state_path)
    source_timeframe = normalize_timeframe(args.derive_source_timeframe)
    fetch_timeframes = [normalize_timeframe(item) for item in _parse_text_list(args.fetch_timeframes)]
    derive_timeframes = [normalize_timeframe(item) for item in _parse_text_list(args.derive_timeframes)]
    if derive_timeframes and source_timeframe not in fetch_timeframes:
        fetch_timeframes.insert(0, source_timeframe)
    derive_timeframes = [timeframe for timeframe in derive_timeframes if timeframe not in fetch_timeframes]

    for target_timeframe in derive_timeframes:
        if not can_resample_timeframe(source_timeframe, target_timeframe):
            raise ValueError(f"Cannot derive {target_timeframe} from {source_timeframe}")

    provider = BaoStockProvider(
        adjustflag=args.adjustflag,
        user_id=args.user_id,
        password=args.password,
    )
    market_groups = normalize_market_groups(_parse_text_list(args.market_groups))
    stock_codes = _load_stock_codes_with_market_groups(
        stock_codes_text=args.stock_codes,
        stock_file=args.stock_file,
        sync_all=args.sync_all,
        market_groups=market_groups,
        provider=provider,
    )
    provider.logout()
    if not stock_codes:
        raise RuntimeError("No stock codes found. Use --stock-codes, --stock-file, or --sync-all.")

    explicit_selection = not args.sync_all and not market_groups
    run_config = {
        "db": args.db,
        "parquet_root": args.parquet_root,
        "stock_selection_mode": "explicit" if explicit_selection else "market_groups",
        "stock_codes": stock_codes if explicit_selection else [],
        "sync_all": bool(args.sync_all),
        "market_groups": market_groups,
        "start": args.start,
        "end": args.end,
        "fetch_timeframes": fetch_timeframes,
        "derive_source_timeframe": source_timeframe,
        "derive_timeframes": derive_timeframes,
        "adjustflag": args.adjustflag,
        "user_id": args.user_id,
        "has_password": bool(str(args.password).strip()),
        "max_retries": args.max_retries,
    }
    state, config_mismatch = _load_or_create_state(state_path, run_config=run_config, reset_state=bool(args.reset_state))
    store = DuckDBStore(args.db)
    if config_mismatch:
        _print("State file config changed. The current run will reconcile progress from local DuckDB data before resuming.")
        for phase_sections in state.get("phases", {}).values():
            for phase_state in phase_sections.values():
                phase_state["completed"] = False
        _save_state(state_path, state)

    _print(f"BaoStock stock count: {len(stock_codes)}")
    _print(f"Stock sample: {', '.join(stock_codes[: max(args.log_stock_sample, 1)])}")
    _print(f"Date range: {args.start} -> {args.end}")
    _print(f"Fetch timeframes: {', '.join(fetch_timeframes) if fetch_timeframes else '(none)'}")
    _print(f"Derive source timeframe: {source_timeframe}")
    _print(f"Derive timeframes: {', '.join(derive_timeframes) if derive_timeframes else '(none)'}")
    _print(f"State file: {state_path}")

    for timeframe in fetch_timeframes:
        phase_state = _phase_state(state, phase="fetch", timeframe=timeframe)
        pending, local_completed, preserved_state_only = _reconcile_phase_progress(
            phase_state=phase_state,
            phase="fetch",
            timeframe=timeframe,
            stock_codes=stock_codes,
            store=store,
            start_time=start_time,
            end_time=end_time,
        )
        _save_state(state_path, state)
        _print(
            f"[resume][fetch][{timeframe}] local_complete={len(local_completed)} "
            f"state_empty_or_skipped={len(preserved_state_only)} pending={len(pending)}"
        )
        if not pending:
            phase_state["completed"] = True
            _save_state(state_path, state)
            _print(f"Skip fetch {timeframe}: already completed.")
            continue

        _print(f"Start fetch timeframe {timeframe}")
        for index, stock_code in enumerate(pending, start=1):
            _print(f"[fetch][{timeframe}] {index}/{len(pending)} {stock_code}")
            summary = _sync_raw_timeframe(
                stock_code=stock_code,
                timeframe=timeframe,
                start_time=start_time,
                end_time=end_time,
                db_path=args.db,
                parquet_root=args.parquet_root,
                adjustflag=args.adjustflag,
                user_id=args.user_id,
                password=args.password,
                max_retries=args.max_retries,
                allow_quality_issues=args.allow_quality_issues,
            )
            completed_flag = summary.status != "failed"
            _append_summary(phase_state, summary, completed=completed_flag)
            _save_state(state_path, state)
            _print(
                f"[fetch][{timeframe}] {stock_code} status={summary.status} rows={summary.rows_written} "
                f"parquet={summary.parquet_file_count} latest={summary.latest_trade_date or '-'}"
            )

        phase_state["completed"] = len(set(phase_state.get("completed_stock_codes", []))) >= len(stock_codes)
        _save_state(state_path, state)
        _print(f"Finished fetch timeframe {timeframe}")

    for timeframe in derive_timeframes:
        phase_state = _phase_state(state, phase="derive", timeframe=timeframe)
        source_phase_state = _phase_state(state, phase="fetch", timeframe=source_timeframe)
        eligible = [stock_code for stock_code in stock_codes if stock_code in set(source_phase_state.get("completed_stock_codes", []))]
        pending, local_completed, _ = _reconcile_phase_progress(
            phase_state=phase_state,
            phase="derive",
            timeframe=timeframe,
            stock_codes=eligible,
            store=store,
            start_time=start_time,
            end_time=end_time,
        )
        _save_state(state_path, state)
        _print(f"[resume][derive][{timeframe}] local_complete={len(local_completed)} pending={len(pending)}")
        if not pending:
            phase_state["completed"] = len(set(phase_state.get("completed_stock_codes", []))) >= len(eligible)
            _save_state(state_path, state)
            _print(f"Skip derive {timeframe}: already completed.")
            continue

        _print(f"Start derive timeframe {timeframe} from {source_timeframe}")
        for index, stock_code in enumerate(pending, start=1):
            _print(f"[derive][{timeframe}] {index}/{len(pending)} {stock_code}")
            try:
                summary = _derive_timeframe(
                    stock_code=stock_code,
                    source_timeframe=source_timeframe,
                    target_timeframe=timeframe,
                    start_time=start_time,
                    end_time=end_time,
                    db_path=args.db,
                    parquet_root=args.parquet_root,
                )
            except Exception as exc:
                summary = StockSummary(
                    phase="derive",
                    timeframe=timeframe,
                    stock_code=stock_code,
                    status="failed",
                    rows_written=0,
                    quality_issue_count=0,
                    parquet_file_count=0,
                    latest_trade_date=None,
                    message=str(exc),
                )

            completed_flag = summary.status != "failed"
            _append_summary(phase_state, summary, completed=completed_flag)
            _save_state(state_path, state)
            _print(
                f"[derive][{timeframe}] {stock_code} status={summary.status} rows={summary.rows_written} "
                f"parquet={summary.parquet_file_count} latest={summary.latest_trade_date or '-'}"
            )

        phase_state["completed"] = len(set(phase_state.get("completed_stock_codes", []))) >= len(eligible)
        _save_state(state_path, state)
        _print(f"Finished derive timeframe {timeframe}")

    state["completed"] = all(
        section.get("completed", False)
        for phase_sections in state.get("phases", {}).values()
        for section in phase_sections.values()
    )
    _save_state(state_path, state)
    _print("BaoStock bulk sync completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
