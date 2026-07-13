from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from uuid import uuid4

import pandas as pd

from mns.backtest.quick_review import QuickReviewBacktester, QuickReviewConfig
from mns.backtest.report import summarize_trades
from mns.data.duckdb_store import DuckDBStore
from mns.data.local_data import LocalMarketData
from mns.factors.technical import add_default_daily_technical_factors
from mns.factors.volume_price import add_default_volume_price_factors
from mns.review.report_exporter import ReportExporter
from mns.selector.condition_screener import ConditionScreener, close_above, greater_than
from mns.strategies.base import StrategyContext
from mns.strategies.next_open_hold_n import NextOpenHoldNStrategy


@dataclass(frozen=True)
class DailyReviewConfig:
    db_path: str = "data/duckdb/mns.duckdb"
    timeframe: str = "1d"
    start_date: str | None = None
    end_date: str | None = None
    as_of_date: str | None = None
    volume_ratio_min: float = 1.0
    hold_days: int = 5
    initial_cash: float = 1_000_000
    per_trade_cash: float = 100_000
    commission_rate: float = 0.0
    stamp_tax_rate: float = 0.0
    transfer_fee_rate: float = 0.0
    slippage_rate: float = 0.0
    export_root: str = "data/reports/exports"


class DailyReviewRunner:
    def __init__(self, config: DailyReviewConfig) -> None:
        self.config = config
        self.store = DuckDBStore(config.db_path)
        self.market_data = LocalMarketData(self.store)

    def run(self) -> dict[str, pd.DataFrame | str | dict[str, Path]]:
        kline = self.market_data.get_kline(
            timeframe=self.config.timeframe,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
        )
        if kline.empty:
            raise ValueError("No local K-line data found. Run sync-csv-kline first.")

        enriched = add_default_daily_technical_factors(kline)
        enriched = add_default_volume_price_factors(enriched)
        as_of_date = self.config.as_of_date or str(pd.to_datetime(enriched["trade_date"]).max().date())
        as_of_rows = enriched[pd.to_datetime(enriched["trade_date"]).dt.date == pd.Timestamp(as_of_date).date()]

        screener = ConditionScreener(
            [
                close_above("close", "ma55"),
                greater_than("volume_ratio_5", self.config.volume_ratio_min),
            ]
        )
        candidates = screener.screen(as_of_rows)

        strategy = NextOpenHoldNStrategy(hold_days=self.config.hold_days)
        signals = strategy.generate_signals(
            candidates,
            StrategyContext(start_date=self.config.start_date, end_date=self.config.end_date),
        )
        backtester = QuickReviewBacktester(
            QuickReviewConfig(
                initial_cash=self.config.initial_cash,
                hold_days=self.config.hold_days,
                per_trade_cash=self.config.per_trade_cash,
                commission_rate=self.config.commission_rate,
                stamp_tax_rate=self.config.stamp_tax_rate,
                transfer_fee_rate=self.config.transfer_fee_rate,
                slippage_rate=self.config.slippage_rate,
            )
        )
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        result = backtester.run(signals, kline, run_id=run_id)
        run_id = str(result["run_id"])
        trades = result["trades"]
        portfolio_snapshots = result["portfolio_snapshots"]
        summary = summarize_trades(trades)

        self._persist_run(
            run_id=run_id,
            candidates=candidates,
            signals=signals,
            trades=trades,
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
        trades: pd.DataFrame,
        portfolio_snapshots: pd.DataFrame,
        summary: dict[str, float | int],
    ) -> None:
        self.store.replace_backtest_run(
            run_id=run_id,
            run_type="quick_review",
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            initial_cash=self.config.initial_cash,
            config={
                "timeframe": self.config.timeframe,
                "as_of_date": self.config.as_of_date,
                "volume_ratio_min": self.config.volume_ratio_min,
                "hold_days": self.config.hold_days,
                "per_trade_cash": self.config.per_trade_cash,
                "commission_rate": self.config.commission_rate,
                "stamp_tax_rate": self.config.stamp_tax_rate,
                "transfer_fee_rate": self.config.transfer_fee_rate,
                "slippage_rate": self.config.slippage_rate,
            },
            result=summary,
        )
        self.store.replace_candidates_for_run(run_id, candidates)
        self.store.replace_trades_for_run(run_id, self._to_trade_actions(trades))
        self.store.replace_signals_for_run(run_id, self._prepare_signals(signals, run_id))
        self.store.replace_portfolio_snapshots_for_run(run_id, portfolio_snapshots)

    @staticmethod
    def _prepare_signals(signals: pd.DataFrame, run_id: str) -> pd.DataFrame:
        if signals.empty:
            return signals
        prepared = signals.copy()
        prepared["signal_id"] = [f"{run_id}_sig_{idx + 1:04d}" for idx in range(len(prepared))]
        return prepared

    @staticmethod
    def _to_trade_actions(trades: pd.DataFrame) -> pd.DataFrame:
        if trades.empty:
            return pd.DataFrame(
                columns=[
                    "trade_id",
                    "run_id",
                    "stock_code",
                    "strategy_name",
                    "action",
                    "price",
                    "quantity",
                    "trade_time",
                    "commission",
                    "tax",
                    "slippage",
                    "reason",
                ]
            )

        rows: list[dict] = []
        for _, trade in trades.iterrows():
            rows.append(
                {
                    "trade_id": trade["trade_id"],
                    "run_id": trade["run_id"],
                    "stock_code": trade["stock_code"],
                    "strategy_name": trade["strategy_name"],
                    "action": "BUY",
                    "price": trade["buy_price"],
                    "quantity": int(trade["quantity"]),
                    "trade_time": trade["buy_time"],
                    "commission": float(trade.get("buy_commission", 0.0)),
                    "tax": 0.0,
                    "slippage": float(trade.get("slippage", 0.0)) / 2,
                    "reason": trade.get("reason", ""),
                }
            )
            rows.append(
                {
                    "trade_id": trade["trade_id"],
                    "run_id": trade["run_id"],
                    "stock_code": trade["stock_code"],
                    "strategy_name": trade["strategy_name"],
                    "action": "SELL",
                    "price": trade["sell_price"],
                    "quantity": int(trade["quantity"]),
                    "trade_time": trade["sell_time"],
                    "commission": float(trade.get("sell_commission", 0.0)),
                    "tax": float(trade.get("tax", 0.0)),
                    "slippage": float(trade.get("slippage", 0.0)) / 2,
                    "reason": trade.get("reason", ""),
                }
            )
        return pd.DataFrame(rows)
