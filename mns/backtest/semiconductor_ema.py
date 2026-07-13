from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import requests

from mns.data.duckdb_store import DuckDBStore
from mns.data.local_data import LocalMarketData


DEFAULT_PARAM_GRID = [
    {"name": "A_strict_1atr", "pullback_atr_buffer": 0.0, "atr_stop_multiple": 1.0, "use_ema55_slope_filter": False},
    {"name": "B_strict_1_5atr", "pullback_atr_buffer": 0.0, "atr_stop_multiple": 1.5, "use_ema55_slope_filter": False},
    {"name": "C_buffer_1atr", "pullback_atr_buffer": 0.2, "atr_stop_multiple": 1.0, "use_ema55_slope_filter": False},
    {"name": "D_buffer_1_5atr", "pullback_atr_buffer": 0.2, "atr_stop_multiple": 1.5, "use_ema55_slope_filter": False},
    {"name": "E_slope_strict_1atr", "pullback_atr_buffer": 0.0, "atr_stop_multiple": 1.0, "use_ema55_slope_filter": True},
    {"name": "F_slope_buffer_1_5atr", "pullback_atr_buffer": 0.2, "atr_stop_multiple": 1.5, "use_ema55_slope_filter": True},
]


@dataclass(frozen=True)
class SemiconductorEmaBaseConfig:
    db_path: str = "data/duckdb/mns.duckdb"
    timeframe: str = "1d"
    start_date: str | None = None
    end_date: str | None = None
    board_name: str = "半导体"
    board_code: str | None = None
    output_root: str = "data/reports/semiconductor_ema"
    initial_cash: float = 1_000_000
    risk_pct: float = 0.01
    ema55_slope_days: int = 5
    lot_size: int = 100
    commission_rate: float = 0.0
    slippage_rate: float = 0.0
    current_constituents_ok: bool = True
    constituent_source: str = "ths_live"
    sector_source: str = ""
    sector_type: str = "industry"


def _normalize_mns_code(code: str) -> str:
    raw = str(code).strip()
    if raw.endswith((".SH", ".SZ", ".BJ")):
        return raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 6:
        return raw
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _atr(group: pd.DataFrame, window: int = 10) -> pd.Series:
    prev_close = group["close"].shift(1)
    tr = pd.concat(
        [
            group["high"] - group["low"],
            (group["high"] - prev_close).abs(),
            (group["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=window, min_periods=window).mean()


def _fetch_ths_board_code(board_name: str) -> str:
    import akshare as ak

    names = ak.stock_board_industry_name_ths()
    match = names.loc[names["name"] == board_name]
    if match.empty:
        raise ValueError(f"THS board not found: {board_name}")
    return str(match.iloc[0]["code"])


def _ths_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/89.0.4389.90 Safari/537.36"
        ),
    }


def fetch_ths_board_constituents(*, board_name: str, board_code: str | None = None) -> pd.DataFrame:
    code = board_code or _fetch_ths_board_code(board_name)
    headers = _ths_headers()
    first_url = f"http://q.10jqka.com.cn/thshy/detail/code/{code}/"
    first_response = requests.get(first_url, headers=headers, timeout=20)
    first_response.raise_for_status()

    page_info = "1/1"
    if "page_info" in first_response.text:
        start = first_response.text.find('page_info">')
        if start >= 0:
            start += len('page_info">')
            end = first_response.text.find("<", start)
            if end > start:
                page_info = first_response.text[start:end].strip()
    total_pages = int(str(page_info).split("/")[-1])

    all_parts: list[pd.DataFrame] = []
    for page in range(1, total_pages + 1):
        url = (
            f"http://q.10jqka.com.cn/thshy/detail/code/{code}/"
            if page == 1
            else f"http://q.10jqka.com.cn/thshy/detail/page/{page}/code/{code}/"
        )
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        try:
            tables = pd.read_html(StringIO(response.text))
        except ValueError:
            break
        if not tables:
            break
        part = tables[0].copy()
        all_parts.append(part)

    if not all_parts:
        return pd.DataFrame(columns=["board_name", "board_code", "stock_code", "stock_name"])

    frame = pd.concat(all_parts, ignore_index=True)
    frame = frame.rename(columns={"代码": "raw_code", "名称": "stock_name"})
    frame["stock_code"] = frame["raw_code"].map(_normalize_mns_code)
    frame["board_name"] = board_name
    frame["board_code"] = code
    frame = frame.drop_duplicates(subset=["stock_code"]).reset_index(drop=True)
    keep = ["board_name", "board_code", "stock_code", "stock_name"]
    extra = [col for col in frame.columns if col not in keep]
    return frame[keep + extra]


def add_semiconductor_ema_factors(kline: pd.DataFrame, *, ema55_slope_days: int) -> pd.DataFrame:
    enriched = kline.sort_values(["stock_code", "trade_date", "bar_time"]).copy()
    enriched["trade_date"] = pd.to_datetime(enriched["trade_date"]).dt.date
    enriched["bar_time"] = pd.to_datetime(enriched["bar_time"])
    grouped = enriched.groupby("stock_code", group_keys=False)
    enriched["ema21"] = grouped["close"].transform(lambda s: _ema(s, 21))
    enriched["ema55"] = grouped["close"].transform(lambda s: _ema(s, 55))
    atr_parts = [_atr(group, 10) for _, group in enriched.groupby("stock_code", sort=False)]
    enriched["atr10"] = pd.concat(atr_parts).sort_index()
    enriched["ema55_prev"] = enriched.groupby("stock_code", group_keys=False)["ema55"].shift(ema55_slope_days)
    enriched["ema55_slope_ok"] = enriched["ema55"] > enriched["ema55_prev"]
    enriched["next_trade_date"] = grouped["trade_date"].shift(-1)
    enriched["next_open"] = grouped["open"].shift(-1)
    enriched["bar_index"] = grouped.cumcount()
    return enriched


def build_signal_log(enriched: pd.DataFrame, *, params: dict[str, Any]) -> pd.DataFrame:
    signal_rows: list[dict[str, Any]] = []
    for _, row in enriched.iterrows():
        entry_date = row["next_trade_date"]
        entry_open = row["next_open"]
        trend_ok = pd.notna(row["ema21"]) and pd.notna(row["ema55"]) and row["ema21"] > row["ema55"]
        slope_ok = True if not params["use_ema55_slope_filter"] else bool(row["ema55_slope_ok"])
        atr10 = row["atr10"]
        pullback_limit = row["ema55"] + params["pullback_atr_buffer"] * atr10 if pd.notna(row["ema55"]) and pd.notna(atr10) else float("nan")
        pullback_ok = pd.notna(pullback_limit) and float(row["low"]) <= float(pullback_limit)
        hold_ok = pd.notna(row["ema55"]) and float(row["close"]) >= float(row["ema55"])
        entry_signal = trend_ok and slope_ok and pullback_ok and hold_ok and pd.notna(entry_date) and pd.notna(entry_open)
        stop_price = float(row["ema55"] - params["atr_stop_multiple"] * atr10) if pd.notna(row["ema55"]) and pd.notna(atr10) else float("nan")
        signal_rows.append(
            {
                "code": row["stock_code"],
                "stock_name": row.get("stock_name"),
                "signal_date": row["trade_date"],
                "entry_date": entry_date,
                "entry_open": entry_open,
                "entry_signal": bool(entry_signal),
                "signal_status": "READY" if entry_signal else "REJECTED",
                "trend_ok": bool(trend_ok),
                "slope_ok": bool(slope_ok),
                "pullback_ok": bool(pullback_ok),
                "hold_ok": bool(hold_ok),
                "entry_ema21": row["ema21"],
                "entry_ema55": row["ema55"],
                "entry_atr10": atr10,
                "entry_signal_low": row["low"],
                "entry_signal_close": row["close"],
                "stop_price": stop_price,
                "pullback_limit": pullback_limit,
                "risk_per_share_est": float(entry_open - stop_price) if pd.notna(entry_open) and pd.notna(stop_price) else float("nan"),
                "use_ema55_slope_filter": params["use_ema55_slope_filter"],
                "pullback_atr_buffer": params["pullback_atr_buffer"],
                "atr_stop_multiple": params["atr_stop_multiple"],
            }
        )
    return pd.DataFrame(signal_rows)


def _build_stock_index_maps(enriched: pd.DataFrame) -> tuple[dict[tuple[str, Any], int], dict[str, set[Any]]]:
    index_map: dict[tuple[str, Any], int] = {}
    date_sets: dict[str, set[Any]] = {}
    for _, row in enriched[["stock_code", "trade_date", "bar_index"]].iterrows():
        code = str(row["stock_code"])
        trade_date = row["trade_date"]
        index_map[(code, trade_date)] = int(row["bar_index"])
        date_sets.setdefault(code, set()).add(trade_date)
    return index_map, date_sets


def run_single_param_backtest(
    enriched: pd.DataFrame,
    *,
    params: dict[str, Any],
    config: SemiconductorEmaBaseConfig,
) -> dict[str, Any]:
    signal_log = build_signal_log(enriched, params=params)
    ready_signals = signal_log.loc[signal_log["entry_signal"]].copy()
    ready_signals["entry_date"] = pd.to_datetime(ready_signals["entry_date"]).dt.date
    signal_map = {
        trade_date: frame.sort_values("code").reset_index(drop=True)
        for trade_date, frame in ready_signals.groupby("entry_date")
    }

    stock_bar_index_map, stock_date_sets = _build_stock_index_maps(enriched)
    daily_groups = {trade_date: frame.copy() for trade_date, frame in enriched.groupby("trade_date")}
    trade_dates = sorted(daily_groups)
    open_positions: dict[str, dict[str, Any]] = {}
    trade_records: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    cash = float(config.initial_cash)
    trade_seq = 0

    for trade_date in trade_dates:
        daily_bars = daily_groups[trade_date].sort_values("stock_code").reset_index(drop=True)
        daily_index = {str(row["stock_code"]): row for _, row in daily_bars.iterrows()}

        for stock_code in list(open_positions.keys()):
            position = open_positions[stock_code]
            if position.get("scheduled_exit_date") != trade_date:
                continue
            bar = daily_index.get(stock_code)
            if bar is None:
                continue
            exit_price = float(bar["open"]) * (1 - config.slippage_rate)
            gross = exit_price * int(position["shares"])
            commission = gross * config.commission_rate
            pnl = gross - commission - position["entry_cost"]
            cash += gross - commission
            trade_records.append(
                _finalize_trade(
                    position=position,
                    exit_date=trade_date,
                    exit_price=exit_price,
                    exit_reason="EMA_DEAD_CROSS",
                    pnl=pnl,
                    bar_index_map=stock_bar_index_map,
                )
            )
            del open_positions[stock_code]

        for stock_code in list(open_positions.keys()):
            position = open_positions[stock_code]
            bar = daily_index.get(stock_code)
            if bar is None:
                continue
            stop_price = float(position["stop_price"])
            if float(bar["low"]) <= stop_price:
                raw_exit_price = float(bar["open"]) if float(bar["open"]) < stop_price else stop_price
                exit_price = raw_exit_price * (1 - config.slippage_rate)
                gross = exit_price * int(position["shares"])
                commission = gross * config.commission_rate
                pnl = gross - commission - position["entry_cost"]
                cash += gross - commission
                trade_records.append(
                    _finalize_trade(
                        position=position,
                        exit_date=trade_date,
                        exit_price=exit_price,
                        exit_reason="ATR_STOP",
                        pnl=pnl,
                        bar_index_map=stock_bar_index_map,
                    )
                )
                del open_positions[stock_code]

        market_value = 0.0
        for stock_code, position in open_positions.items():
            bar = daily_index.get(stock_code)
            if bar is None:
                continue
            market_value += float(bar["close"]) * int(position["shares"])
        equity_before_entries = cash + market_value

        daily_signals = signal_map.get(trade_date, pd.DataFrame())
        for _, signal in daily_signals.iterrows():
            stock_code = str(signal["code"])
            if stock_code in open_positions:
                continue
            if trade_date not in stock_date_sets.get(stock_code, set()):
                continue
            entry_price = float(signal["entry_open"]) * (1 + config.slippage_rate)
            stop_price = float(signal["stop_price"])
            risk_per_share = entry_price - stop_price
            if risk_per_share <= 0:
                continue
            risk_amount = equity_before_entries * config.risk_pct
            shares = math.floor((risk_amount / risk_per_share) / config.lot_size) * config.lot_size
            max_cash_shares = math.floor((cash / entry_price) / config.lot_size) * config.lot_size
            shares = min(int(shares), int(max_cash_shares))
            if shares <= 0:
                continue
            gross_cost = entry_price * shares
            commission = gross_cost * config.commission_rate
            total_cost = gross_cost + commission
            if total_cost > cash:
                continue
            cash -= total_cost
            trade_seq += 1
            open_positions[stock_code] = {
                "trade_id": f"{params['name']}_{trade_seq:04d}",
                "code": stock_code,
                "stock_name": signal.get("stock_name"),
                "entry_date": trade_date,
                "entry_price": entry_price,
                "shares": shares,
                "stop_price": stop_price,
                "risk_per_share": risk_per_share,
                "risk_amount": risk_per_share * shares,
                "entry_cost": total_cost,
                "entry_ema21": signal["entry_ema21"],
                "entry_ema55": signal["entry_ema55"],
                "entry_atr10": signal["entry_atr10"],
                "entry_signal_low": signal["entry_signal_low"],
                "entry_signal_close": signal["entry_signal_close"],
                "scheduled_exit_date": None,
            }

        for stock_code in list(open_positions.keys()):
            position = open_positions[stock_code]
            if position["entry_date"] != trade_date:
                continue
            bar = daily_index.get(stock_code)
            if bar is None:
                continue
            stop_price = float(position["stop_price"])
            if float(bar["low"]) <= stop_price:
                exit_price = stop_price * (1 - config.slippage_rate)
                gross = exit_price * int(position["shares"])
                commission = gross * config.commission_rate
                pnl = gross - commission - position["entry_cost"]
                cash += gross - commission
                trade_records.append(
                    _finalize_trade(
                        position=position,
                        exit_date=trade_date,
                        exit_price=exit_price,
                        exit_reason="ATR_STOP",
                        pnl=pnl,
                        bar_index_map=stock_bar_index_map,
                    )
                )
                del open_positions[stock_code]

        for stock_code, position in open_positions.items():
            bar = daily_index.get(stock_code)
            if bar is None:
                continue
            next_trade_date = bar.get("next_trade_date")
            if pd.notna(bar["ema21"]) and pd.notna(bar["ema55"]) and float(bar["ema21"]) < float(bar["ema55"]) and pd.notna(next_trade_date):
                position["scheduled_exit_date"] = next_trade_date

        market_value = 0.0
        for stock_code, position in open_positions.items():
            bar = daily_index.get(stock_code)
            if bar is None:
                continue
            market_value += float(bar["close"]) * int(position["shares"])
        equity = cash + market_value
        equity_rows.append(
            {
                "date": trade_date,
                "cash": cash,
                "market_value": market_value,
                "equity": equity,
                "open_positions": len(open_positions),
            }
        )

    if open_positions:
        last_dates = enriched.groupby("stock_code")["trade_date"].max().to_dict()
        for stock_code in list(open_positions.keys()):
            position = open_positions[stock_code]
            last_date = last_dates[stock_code]
            last_bar = daily_groups[last_date].loc[daily_groups[last_date]["stock_code"] == stock_code].iloc[-1]
            exit_price = float(last_bar["close"]) * (1 - config.slippage_rate)
            gross = exit_price * int(position["shares"])
            commission = gross * config.commission_rate
            pnl = gross - commission - position["entry_cost"]
            cash += gross - commission
            trade_records.append(
                _finalize_trade(
                    position=position,
                    exit_date=last_date,
                    exit_price=exit_price,
                    exit_reason="END_OF_TEST",
                    pnl=pnl,
                    bar_index_map=stock_bar_index_map,
                )
            )
            del open_positions[stock_code]
        if equity_rows:
            equity_rows[-1]["cash"] = cash
            equity_rows[-1]["market_value"] = 0.0
            equity_rows[-1]["equity"] = cash
            equity_rows[-1]["open_positions"] = 0

    trades = pd.DataFrame(trade_records)
    equity_curve = pd.DataFrame(equity_rows)
    if not equity_curve.empty:
        equity_curve["daily_return"] = equity_curve["equity"].pct_change().fillna(0.0)
        equity_curve["cummax_equity"] = equity_curve["equity"].cummax()
        equity_curve["drawdown"] = equity_curve["equity"] / equity_curve["cummax_equity"] - 1.0
        equity_curve = equity_curve.drop(columns=["cummax_equity"])

    stock_summary = summarize_by_stock(trades)
    summary = summarize_run(trades, equity_curve, initial_cash=config.initial_cash)
    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "stock_summary": stock_summary,
        "summary": summary,
        "signal_log": signal_log,
    }


def _finalize_trade(
    *,
    position: dict[str, Any],
    exit_date: Any,
    exit_price: float,
    exit_reason: str,
    pnl: float,
    bar_index_map: dict[tuple[str, Any], int],
) -> dict[str, Any]:
    entry_index = bar_index_map.get((position["code"], position["entry_date"]), 0)
    exit_index = bar_index_map.get((position["code"], exit_date), entry_index)
    risk_amount = float(position["risk_amount"])
    pnl_pct = pnl / position["entry_cost"] if position["entry_cost"] else 0.0
    return {
        "trade_id": position["trade_id"],
        "code": position["code"],
        "stock_name": position.get("stock_name"),
        "entry_date": position["entry_date"],
        "entry_price": position["entry_price"],
        "exit_date": exit_date,
        "exit_price": exit_price,
        "shares": position["shares"],
        "stop_price": position["stop_price"],
        "risk_per_share": position["risk_per_share"],
        "risk_amount": risk_amount,
        "holding_days": int(max(exit_index - entry_index, 0)),
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "r_multiple": (pnl / risk_amount) if risk_amount else 0.0,
        "exit_reason": exit_reason,
        "entry_ema21": position["entry_ema21"],
        "entry_ema55": position["entry_ema55"],
        "entry_atr10": position["entry_atr10"],
        "entry_signal_low": position["entry_signal_low"],
        "entry_signal_close": position["entry_signal_close"],
    }


def summarize_by_stock(trades: pd.DataFrame) -> pd.DataFrame:
    columns = ["code", "stock_name", "trade_count", "win_count", "win_rate", "total_pnl", "avg_pnl", "best_trade", "worst_trade"]
    if trades.empty:
        return pd.DataFrame(columns=columns)
    grouped = trades.groupby(["code", "stock_name"], dropna=False)
    summary = grouped["pnl"].agg(["count", "sum", "mean", "max", "min"]).reset_index()
    wins = trades.assign(is_win=trades["pnl"] > 0).groupby(["code", "stock_name"], dropna=False)["is_win"].sum().reset_index()
    summary = summary.merge(wins, on=["code", "stock_name"], how="left")
    summary["win_rate"] = summary["is_win"] / summary["count"]
    summary = summary.rename(
        columns={
            "count": "trade_count",
            "is_win": "win_count",
            "sum": "total_pnl",
            "mean": "avg_pnl",
            "max": "best_trade",
            "min": "worst_trade",
        }
    )
    return summary[columns].sort_values(["total_pnl", "trade_count"], ascending=[False, False]).reset_index(drop=True)


def summarize_run(trades: pd.DataFrame, equity_curve: pd.DataFrame, *, initial_cash: float) -> dict[str, Any]:
    if equity_curve.empty:
        final_equity = initial_cash
        total_return = 0.0
        annual_return = 0.0
        max_drawdown = 0.0
    else:
        final_equity = float(equity_curve.iloc[-1]["equity"])
        total_return = final_equity / initial_cash - 1.0
        periods = max(len(equity_curve), 1)
        annual_return = (final_equity / initial_cash) ** (252 / periods) - 1.0 if final_equity > 0 else -1.0
        max_drawdown = float(equity_curve["drawdown"].min())

    losses = trades.loc[trades["pnl"] < 0, "pnl"] if not trades.empty else pd.Series(dtype=float)
    wins = trades.loc[trades["pnl"] > 0, "pnl"] if not trades.empty else pd.Series(dtype=float)
    max_consecutive_losses = 0
    current_losses = 0
    for pnl in trades["pnl"] if not trades.empty else []:
        if pnl < 0:
            current_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, current_losses)
        else:
            current_losses = 0

    return {
        "initial_cash": float(initial_cash),
        "final_equity": final_equity,
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "trade_count": int(len(trades)),
        "win_rate": float((trades["pnl"] > 0).mean()) if not trades.empty else 0.0,
        "avg_win": float(wins.mean()) if not wins.empty else 0.0,
        "avg_loss": float(losses.mean()) if not losses.empty else 0.0,
        "profit_loss_ratio": float(wins.mean() / abs(losses.mean())) if (not wins.empty and not losses.empty and losses.mean() != 0) else 0.0,
        "avg_holding_days": float(trades["holding_days"].mean()) if not trades.empty else 0.0,
        "max_consecutive_losses": int(max_consecutive_losses),
        "total_pnl": float(trades["pnl"].sum()) if not trades.empty else 0.0,
        "best_trade": float(trades["pnl"].max()) if not trades.empty else 0.0,
        "worst_trade": float(trades["pnl"].min()) if not trades.empty else 0.0,
        "atr_stop_count": int((trades["exit_reason"] == "ATR_STOP").sum()) if not trades.empty else 0,
        "ema_dead_cross_count": int((trades["exit_reason"] == "EMA_DEAD_CROSS").sum()) if not trades.empty else 0,
        "end_of_test_count": int((trades["exit_reason"] == "END_OF_TEST").sum()) if not trades.empty else 0,
    }


class SemiconductorEmaBacktestRunner:
    def __init__(self, config: SemiconductorEmaBaseConfig) -> None:
        self.config = config
        self.store = DuckDBStore(config.db_path)
        self.market_data = LocalMarketData(self.store)

    def run(self) -> dict[str, Any]:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        board_snapshot = self._load_board_snapshot()
        stock_codes = board_snapshot["stock_code"].dropna().astype(str).tolist()
        if not stock_codes:
            raise ValueError(f"No constituents found for board {self.config.board_name}")

        kline = self.market_data.get_kline(
            timeframe=self.config.timeframe,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            stock_codes=stock_codes,
        )
        if kline.empty:
            raise ValueError("No local daily K-line data found for the selected board constituents.")

        enriched = add_semiconductor_ema_factors(kline, ema55_slope_days=self.config.ema55_slope_days)
        output_root = Path(self.config.output_root) / run_id
        output_root.mkdir(parents=True, exist_ok=True)

        board_snapshot_path = output_root / "ths_board_snapshot.csv"
        board_snapshot.to_csv(board_snapshot_path, index=False, encoding="utf-8-sig")

        config_payload = asdict(self.config)
        config_payload["run_id"] = run_id
        config_payload["board_snapshot_date"] = datetime.now().strftime("%Y-%m-%d")
        config_payload["board_constituent_count"] = int(len(board_snapshot))
        config_payload["warning_survivorship_bias"] = self.config.current_constituents_ok
        config_payload["board_snapshot_note"] = self._board_snapshot_note()
        (output_root / "run_config.json").write_text(json.dumps(config_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        param_summaries: list[dict[str, Any]] = []
        param_outputs: dict[str, dict[str, str]] = {}
        focus_summary: dict[str, Any] | None = None

        for params in DEFAULT_PARAM_GRID:
            param_dir = output_root / params["name"]
            param_dir.mkdir(parents=True, exist_ok=True)
            result = run_single_param_backtest(enriched, params=params, config=self.config)
            self._write_param_bundle(param_dir=param_dir, params=params, result=result)
            summary_row = {"name": params["name"], **params, **result["summary"]}
            param_summaries.append(summary_row)
            param_outputs[params["name"]] = {
                "trades": str(param_dir / "trades.csv"),
                "equity_curve": str(param_dir / "equity_curve.csv"),
                "stock_summary": str(param_dir / "stock_summary.csv"),
                "signal_log": str(param_dir / "signal_log.csv"),
                "summary": str(param_dir / "summary.json"),
            }
            if params["name"] == "F_slope_buffer_1_5atr":
                focus_summary = summary_row

        param_summary_df = pd.DataFrame(param_summaries).sort_values(
            ["total_return", "win_rate", "trade_count"],
            ascending=[False, False, False],
        )
        param_summary_path = output_root / "parameter_grid_summary.csv"
        param_summary_df.to_csv(param_summary_path, index=False, encoding="utf-8-sig")

        analyst_brief_path = output_root / "analyst_5_5_brief.md"
        analyst_brief_path.write_text(
            self._build_analyst_brief(
                run_id=run_id,
                board_snapshot_count=len(board_snapshot),
                constituent_source=self.config.constituent_source,
                param_summary=param_summary_df,
                focus_summary=focus_summary,
            ),
            encoding="utf-8",
        )

        return {
            "run_id": run_id,
            "output_root": str(output_root),
            "board_snapshot_path": str(board_snapshot_path),
            "parameter_grid_summary_path": str(param_summary_path),
            "analyst_brief_path": str(analyst_brief_path),
            "board_constituent_count": int(len(board_snapshot)),
            "date_range": {
                "start": str(pd.to_datetime(kline["trade_date"]).min().date()),
                "end": str(pd.to_datetime(kline["trade_date"]).max().date()),
            },
            "focus_summary": focus_summary,
            "param_outputs": param_outputs,
        }

    def _load_board_snapshot(self) -> pd.DataFrame:
        if self.config.constituent_source == "local_sector_store":
            board_snapshot = self.store.query_frame(
                """
                SELECT
                    m.sector_name AS board_name,
                    s.source_sector_code AS board_code,
                    m.stock_code,
                    m.stock_name
                FROM stock_sector_map AS m
                LEFT JOIN sectors AS s
                    ON s.sector_id = m.sector_id
                    AND s.source = m.source
                WHERE m.sector_name = ?
                  AND (? = '' OR m.source = ?)
                  AND (? = '' OR m.sector_type = ?)
                ORDER BY m.stock_code
                """,
                (
                    self.config.board_name,
                    self.config.sector_source,
                    self.config.sector_source,
                    self.config.sector_type,
                    self.config.sector_type,
                ),
            )
            if board_snapshot.empty:
                raise ValueError(
                    f"No local sector-store constituents found for board `{self.config.board_name}` "
                    f"source `{self.config.sector_source or 'any'}`."
                )
            return board_snapshot.drop_duplicates(subset=["stock_code"]).reset_index(drop=True)
        return fetch_ths_board_constituents(board_name=self.config.board_name, board_code=self.config.board_code)

    def _board_snapshot_note(self) -> str:
        if self.config.constituent_source == "local_sector_store":
            return (
                "This run used constituents from the local sector store, imported from a saved board snapshot. "
                f"Source={self.config.sector_source or 'any'}, sector_type={self.config.sector_type}."
            )
        return (
            "THS public industry pages were used for the board snapshot in this run. "
            "If you later provide the full board-download response used in the original software design, "
            "replace the snapshot and rerun for a tighter match."
        )

    def _write_param_bundle(self, *, param_dir: Path, params: dict[str, Any], result: dict[str, Any]) -> None:
        result["trades"].to_csv(param_dir / "trades.csv", index=False, encoding="utf-8-sig")
        result["equity_curve"].to_csv(param_dir / "equity_curve.csv", index=False, encoding="utf-8-sig")
        result["stock_summary"].to_csv(param_dir / "stock_summary.csv", index=False, encoding="utf-8-sig")
        result["signal_log"].to_csv(param_dir / "signal_log.csv", index=False, encoding="utf-8-sig")
        (param_dir / "summary.json").write_text(json.dumps(result["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
        (param_dir / "params.json").write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _build_analyst_brief(
        *,
        run_id: str,
        board_snapshot_count: int,
        constituent_source: str,
        param_summary: pd.DataFrame,
        focus_summary: dict[str, Any] | None,
    ) -> str:
        top_rows = param_summary.head(3)
        source_label = "local sector store snapshot" if constituent_source == "local_sector_store" else "THS live snapshot"
        lines = [
            f"# Semiconductor EMA Backtest Brief",
            "",
            f"- Run ID: `{run_id}`",
            f"- Constituent source: `{source_label}`",
            f"- Board snapshot: `半导体`, constituents `{board_snapshot_count}`",
            f"- Current note: this run used `{source_label}` for the board universe.",
            f"- Survivorship bias note: current constituent snapshot was used, as allowed by the design note.",
            f"- Recommended focus parameter: `F_slope_buffer_1_5atr`",
            "",
            "## Files",
            "",
            "- `ths_board_snapshot.csv`: THS synced semiconductor constituent snapshot used in this run.",
            "- `parameter_grid_summary.csv`: six parameter-set summaries for quick comparison.",
            "- `{param_name}/trades.csv`: trade-by-trade detail.",
            "- `{param_name}/equity_curve.csv`: daily cash, market value, equity, return, drawdown.",
            "- `{param_name}/stock_summary.csv`: contribution by stock.",
            "- `{param_name}/signal_log.csv`: every signal-day condition check, including rejected rows.",
            "- `{param_name}/summary.json`: machine-readable summary for analyst review.",
            "",
            "## What To Review",
            "",
            "- Compare the six parameter sets by total return, max drawdown, trade count, win rate, and exit-reason mix.",
            "- Focus on whether pullbacks near EMA55 lead to clean next-open entries instead of noisy knife-catching.",
            "- Inspect stocks with the largest positive and negative contribution in `stock_summary.csv`.",
            "- Use `signal_log.csv` to study false positives and missed entries around slope filter changes.",
            "",
            "## Top Parameter Rows",
            "",
        ]
        for _, row in top_rows.iterrows():
            lines.append(
                f"- `{row['name']}`: return={row['total_return']:.2%}, max_dd={row['max_drawdown']:.2%}, trades={int(row['trade_count'])}, win_rate={row['win_rate']:.2%}"
            )
        if focus_summary is not None:
            lines.extend(
                [
                    "",
                    "## Focus Set Snapshot",
                    "",
                    f"- `F_slope_buffer_1_5atr`: return={focus_summary['total_return']:.2%}, annual={focus_summary['annual_return']:.2%}, max_dd={focus_summary['max_drawdown']:.2%}, trades={int(focus_summary['trade_count'])}, win_rate={focus_summary['win_rate']:.2%}",
                ]
            )
        return "\n".join(lines) + "\n"
