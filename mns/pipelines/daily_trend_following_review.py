from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from mns.backtest.daily_trend_following import (
    DailyTrendBacktestConfig,
    DailyTrendFollowingBacktester,
    summarize_daily_trend_run,
)
from mns.data.duckdb_store import DuckDBStore
from mns.data.local_data import LocalMarketData
from mns.factors.technical import add_daily_trend_following_factors
from mns.review.report_exporter import ReportExporter
from mns.strategies.daily_trend_following import DailyTrendFollowingConfig, DailyTrendFollowingStrategy


@dataclass(frozen=True)
class DailyTrendFollowingReviewConfig:
    db_path: str = "data/duckdb/mns.duckdb"
    timeframe: str = "1d"
    start_date: str | None = None
    end_date: str | None = None
    stock_codes: list[str] | None = None
    min_bias: float = 0.02
    min_close_above_ema20: float = 0.002
    pullback_floor: float = 0.995
    min_volume_ratio: float = 1.2
    atr_stop_multiple: float = 1.5
    initial_cash: float = 1_000_000
    risk_per_trade_pct: float = 0.008
    max_position_pct: float = 0.20
    max_total_risk_pct: float = 0.025
    high_volatility_threshold: float = 0.06
    high_volatility_size_factor: float = 0.5
    commission_rate: float = 0.0005
    stamp_tax_rate: float = 0.001
    transfer_fee_rate: float = 0.0
    slippage_rate: float = 0.001
    stage2_timeout_days: int = 15
    export_root: str = "data/reports/exports"


class DailyTrendFollowingReviewRunner:
    def __init__(self, config: DailyTrendFollowingReviewConfig) -> None:
        self.config = config
        self.store = DuckDBStore(config.db_path)
        self.market_data = LocalMarketData(self.store)

    def run(self) -> dict[str, pd.DataFrame | str | dict[str, Path] | dict]:
        kline = self.market_data.get_kline(
            timeframe=self.config.timeframe,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            stock_codes=self.config.stock_codes,
        )
        if kline.empty:
            raise ValueError("No local daily K-line data found. Run daily sync first.")

        enriched = add_daily_trend_following_factors(kline)
        strategy = DailyTrendFollowingStrategy(
            DailyTrendFollowingConfig(
                min_bias=self.config.min_bias,
                min_close_above_ema20=self.config.min_close_above_ema20,
                pullback_floor=self.config.pullback_floor,
                min_volume_ratio=self.config.min_volume_ratio,
                atr_stop_multiple=self.config.atr_stop_multiple,
            )
        )
        candidates = strategy.build_candidates(enriched)
        signals = strategy.generate_signals(enriched)

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        backtester = DailyTrendFollowingBacktester(
            DailyTrendBacktestConfig(
                initial_cash=self.config.initial_cash,
                risk_per_trade_pct=self.config.risk_per_trade_pct,
                max_position_pct=self.config.max_position_pct,
                max_total_risk_pct=self.config.max_total_risk_pct,
                high_volatility_threshold=self.config.high_volatility_threshold,
                high_volatility_size_factor=self.config.high_volatility_size_factor,
                commission_rate=self.config.commission_rate,
                stamp_tax_rate=self.config.stamp_tax_rate,
                transfer_fee_rate=self.config.transfer_fee_rate,
                slippage_rate=self.config.slippage_rate,
                stage2_timeout_days=self.config.stage2_timeout_days,
            )
        )
        result = backtester.run(signals, enriched, run_id=run_id)
        trades = result["trades"]
        trade_actions = result["trade_actions"]
        portfolio_snapshots = result["portfolio_snapshots"]
        summary = summarize_daily_trend_run(trades, portfolio_snapshots)

        self._persist_run(
            run_id=run_id,
            candidates=candidates,
            signals=signals,
            trade_actions=trade_actions,
            portfolio_snapshots=portfolio_snapshots,
            summary=summary,
        )

        exporter = ReportExporter(self.config.export_root)
        outputs = exporter.export_csv_bundle(
            run_id=run_id,
            trades=trades,
            portfolio=portfolio_snapshots,
            problems=pd.DataFrame(columns=["problem_tag", "count"]),
        )
        candidates_path = Path(self.config.export_root) / f"{run_id}_candidates.csv"
        signals_path = Path(self.config.export_root) / f"{run_id}_signals.csv"
        candidates.to_csv(candidates_path, index=False)
        signals.to_csv(signals_path, index=False)
        outputs["candidates"] = candidates_path
        outputs["signals"] = signals_path

        return {
            "run_id": run_id,
            "candidates": candidates,
            "signals": signals,
            "trades": trades,
            "portfolio_snapshots": portfolio_snapshots,
            "summary": summary,
            "outputs": outputs,
        }

    def _persist_run(
        self,
        *,
        run_id: str,
        candidates: pd.DataFrame,
        signals: pd.DataFrame,
        trade_actions: pd.DataFrame,
        portfolio_snapshots: pd.DataFrame,
        summary: dict[str, float | int],
    ) -> None:
        self.store.replace_backtest_run(
            run_id=run_id,
            run_type="daily_trend_following",
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            initial_cash=self.config.initial_cash,
            config={
                "timeframe": self.config.timeframe,
                "min_bias": self.config.min_bias,
                "min_close_above_ema20": self.config.min_close_above_ema20,
                "pullback_floor": self.config.pullback_floor,
                "min_volume_ratio": self.config.min_volume_ratio,
                "atr_stop_multiple": self.config.atr_stop_multiple,
                "risk_per_trade_pct": self.config.risk_per_trade_pct,
                "max_position_pct": self.config.max_position_pct,
                "max_total_risk_pct": self.config.max_total_risk_pct,
                "high_volatility_threshold": self.config.high_volatility_threshold,
                "high_volatility_size_factor": self.config.high_volatility_size_factor,
                "commission_rate": self.config.commission_rate,
                "stamp_tax_rate": self.config.stamp_tax_rate,
                "transfer_fee_rate": self.config.transfer_fee_rate,
                "slippage_rate": self.config.slippage_rate,
                "stage2_timeout_days": self.config.stage2_timeout_days,
                "unsupported_filters": ["earnings_window", "industry_max_one"],
            },
            result=summary,
        )
        self.store.replace_candidates_for_run(run_id, self._prepare_candidates(candidates))
        self.store.replace_signals_for_run(run_id, self._prepare_signals(signals, run_id))
        self.store.replace_trades_for_run(run_id, trade_actions)
        self.store.replace_portfolio_snapshots_for_run(run_id, portfolio_snapshots)

    @staticmethod
    def _prepare_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
        if candidates.empty:
            return candidates
        prepared = candidates.copy()
        prepared["timeframe"] = "1d"
        prepared["close"] = prepared["entry_price"]
        return prepared[
            [
                "stock_code",
                "stock_name",
                "trade_date",
                "bar_time",
                "timeframe",
                "close",
                "score",
                "candidate_reason",
            ]
        ]

    @staticmethod
    def _prepare_signals(signals: pd.DataFrame, run_id: str) -> pd.DataFrame:
        if signals.empty:
            return signals
        prepared = signals.copy()
        prepared["signal_id"] = [f"{run_id}_sig_{idx + 1:04d}" for idx in range(len(prepared))]
        return prepared
