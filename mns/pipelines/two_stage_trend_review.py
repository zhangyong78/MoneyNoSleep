from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import pandas as pd

from mns.backtest.two_stage_trend import TwoStageTrendBacktestConfig, TwoStageTrendBacktester, summarize_two_stage_trend_run
from mns.data.duckdb_store import DuckDBStore
from mns.data.khquant_cache import KhQuantCacheStore, bs_to_mns_code
from mns.data.local_data import LocalMarketData
from mns.review.capital_utilization_exporter import CapitalUtilizationExporter
from mns.review.report_exporter import ReportExporter
from mns.strategies.two_stage_trend import TwoStageTrendStrategy, TwoStageTrendStrategyConfig


@dataclass(frozen=True)
class TwoStageTrendReviewConfig:
    db_path: str = "data/duckdb/mns.duckdb"
    khquant_cache_path: str = "data/cache/screening_cache.duckdb"
    start_date: str | None = None
    end_date: str | None = None
    initial_cash: float = 200_000.0
    max_positions: int = 10
    batch_size: int = 200
    export_root: str = "data/reports/exports"
    strategy: TwoStageTrendStrategyConfig = TwoStageTrendStrategyConfig()
    backtest: TwoStageTrendBacktestConfig = TwoStageTrendBacktestConfig()


def non_st_mns_codes(cache: KhQuantCacheStore, end_date: str) -> list[str]:
    resolved_date = cache.resolve_signal_date(end_date)
    if resolved_date is None:
        raise ValueError(f"No screening-cache trade date on or before {end_date}.")
    universe = cache.load_universe(signal_date=resolved_date, universe="all_a", exclude_st=True)
    codes = [bs_to_mns_code(code) for code in universe["code"].astype(str).tolist()]
    if not codes:
        raise ValueError(f"Non-ST universe is empty on {resolved_date}.")
    return codes


def code_batches(codes: list[str], batch_size: int) -> Iterator[list[str]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    for start in range(0, len(codes), batch_size):
        yield codes[start : start + batch_size]


def clean_two_stage_daily_bars(frame: pd.DataFrame, *, placeholder_min_rows: int = 50) -> tuple[pd.DataFrame, dict[str, int]]:
    """Remove non-trading placeholders and invalid OHLC rows before indicator calculation."""
    stats = {"dropped_placeholder_rows": 0, "dropped_zero_activity_rows": 0, "dropped_invalid_ohlc_rows": 0}
    if frame.empty:
        return frame.copy(), stats

    cleaned = frame.copy()
    volume = pd.to_numeric(cleaned.get("volume"), errors="coerce")
    amount = pd.to_numeric(cleaned.get("amount"), errors="coerce")
    inactive = volume.eq(0) & amount.eq(0)
    date_counts = pd.DataFrame({"trade_date": cleaned["trade_date"], "inactive": inactive}).groupby("trade_date", dropna=False).agg(
        rows=("inactive", "size"), inactive_rows=("inactive", "sum")
    )
    placeholder_dates = date_counts.index[
        (date_counts["rows"] >= placeholder_min_rows) & (date_counts["inactive_rows"] == date_counts["rows"])
    ]
    placeholder_mask = cleaned["trade_date"].isin(placeholder_dates)
    stats["dropped_placeholder_rows"] = int(placeholder_mask.sum())
    cleaned = cleaned.loc[~placeholder_mask].copy()

    ohlc = cleaned[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    valid_ohlc = ohlc.notna().all(axis=1) & ohlc.gt(0).all(axis=1)
    stats["dropped_invalid_ohlc_rows"] = int((~valid_ohlc).sum())
    cleaned = cleaned.loc[valid_ohlc].copy()
    no_activity = pd.to_numeric(cleaned["volume"], errors="coerce").eq(0) & pd.to_numeric(cleaned["amount"], errors="coerce").eq(0)
    stats["dropped_zero_activity_rows"] = int(no_activity.sum())
    return cleaned.loc[~no_activity].copy(), stats


def select_backtest_bars(enriched: pd.DataFrame, active_codes: pd.Series) -> pd.DataFrame:
    columns = [
        "stock_code", "trade_date", "bar_time", "open", "high", "low", "close", "atr14", "ma20",
        "is_suspended", "limit_up_price", "limit_down_price",
    ]
    available = [column for column in columns if column in enriched.columns]
    return enriched.loc[enriched["stock_code"].isin(active_codes), available].copy()


def prepare_trade_actions(actions: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "trade_id", "run_id", "stock_code", "strategy_name", "action", "price", "quantity",
        "trade_time", "commission", "tax", "slippage", "reason",
    ]
    prepared = actions.copy()
    for column in columns:
        if column not in prepared.columns:
            prepared[column] = None
    return prepared[columns]


class TwoStageTrendReviewRunner:
    def __init__(self, config: TwoStageTrendReviewConfig) -> None:
        self.config = config; self.store = DuckDBStore(config.db_path); self.market = LocalMarketData(self.store)

    def run(self) -> dict[str, object]:
        if not self.config.start_date or not self.config.end_date:
            raise ValueError("start_date and end_date are required")
        codes = non_st_mns_codes(KhQuantCacheStore(self.config.khquant_cache_path), self.config.end_date)
        strategy = TwoStageTrendStrategy(self.config.strategy)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        root = Path(self.config.export_root); root.mkdir(parents=True, exist_ok=True)
        process_log = root / f"{run_id}_process.log"
        process_log.write_text(f"run_id={run_id}\ncodes={len(codes)}\nbatch_size={self.config.batch_size}\n", encoding="utf-8")
        candidate_parts: list[pd.DataFrame] = []
        signal_parts: list[pd.DataFrame] = []
        bar_parts: list[pd.DataFrame] = []
        cleaning_totals = {"dropped_placeholder_rows": 0, "dropped_zero_activity_rows": 0, "dropped_invalid_ohlc_rows": 0}
        batches = list(code_batches(codes, self.config.batch_size))
        for number, batch in enumerate(batches, start=1):
            bars = self.market.get_kline(timeframe="1d", start_date=self.config.start_date, end_date=self.config.end_date, stock_codes=batch)
            if bars.empty:
                continue
            raw_rows = len(bars)
            bars, cleaning = clean_two_stage_daily_bars(bars)
            for key, value in cleaning.items():
                cleaning_totals[key] += value
            if bars.empty:
                with process_log.open("a", encoding="utf-8") as handle:
                    handle.write(f"batch={number}/{len(batches)} raw_rows={raw_rows} rows=0 {cleaning}\n")
                continue
            enriched = strategy.enrich(bars)
            candidates_batch = enriched.loc[enriched["entry_candidate"]].copy()
            signals_batch = strategy.signals_from_enriched(enriched)
            if not candidates_batch.empty:
                candidate_parts.append(candidates_batch)
            if not signals_batch.empty:
                signal_parts.append(signals_batch)
                active_codes = signals_batch["stock_code"].drop_duplicates()
                bar_parts.append(select_backtest_bars(enriched, active_codes))
            with process_log.open("a", encoding="utf-8") as handle:
                handle.write(f"batch={number}/{len(batches)} raw_rows={raw_rows} rows={len(bars)} {cleaning} candidates={len(candidates_batch)} signals={len(signals_batch)}\n")
            print(f"two-stage batch {number}/{len(batches)}: {len(signals_batch)} signals", flush=True)
        with process_log.open("a", encoding="utf-8") as handle:
            handle.write(f"cleaning_totals={cleaning_totals}\n")
        candidates = pd.concat(candidate_parts, ignore_index=True) if candidate_parts else pd.DataFrame()
        signals = pd.concat(signal_parts, ignore_index=True) if signal_parts else pd.DataFrame()
        enriched = pd.concat(bar_parts, ignore_index=True) if bar_parts else pd.DataFrame()
        if enriched.empty:
            raise ValueError("No two-stage signals found; nothing to backtest.")
        backtest_config = replace(self.config.backtest, initial_cash=self.config.initial_cash, max_positions=self.config.max_positions)
        result = TwoStageTrendBacktester(backtest_config).run(signals, enriched, run_id=run_id)
        summary = summarize_two_stage_trend_run(result["trades"], result["portfolio_snapshots"])
        self.store.replace_backtest_run(run_id=run_id, run_type="two_stage_trend", start_date=self.config.start_date, end_date=self.config.end_date, initial_cash=self.config.initial_cash, config={"max_positions": self.config.max_positions, "per_position_cash": backtest_config.per_position_cash, "ma20_exit_mode": backtest_config.ma20_exit_mode, "exclude_st": True}, result=summary)
        self.store.replace_signals_for_run(run_id, signals)
        self.store.replace_trades_for_run(run_id, prepare_trade_actions(result["trade_actions"]))
        self.store.replace_portfolio_snapshots_for_run(run_id, result["portfolio_snapshots"])
        outputs = ReportExporter(root).export_csv_bundle(run_id=run_id, trades=result["trades"], portfolio=result["portfolio_snapshots"], problems=result["skipped_orders"])
        outputs["capital_utilization"] = CapitalUtilizationExporter(root).export(result["portfolio_snapshots"], run_id=run_id)
        outputs["process_log"] = process_log
        for name, frame in {"candidates": candidates, "signals": signals, "skipped_orders": result["skipped_orders"]}.items():
            path = root / f"{run_id}_{name}.csv"; frame.to_csv(path, index=False); outputs[name] = path
        return {"run_id": run_id, "candidates": candidates, "signals": signals, "summary": summary, "outputs": outputs, **result}
