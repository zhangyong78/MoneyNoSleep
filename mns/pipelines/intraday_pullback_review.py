from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from mns.backtest.quick_review import QuickReviewBacktester, QuickReviewConfig
from mns.backtest.report import summarize_trades
from mns.data.duckdb_store import DuckDBStore
from mns.data.local_data import LocalMarketData
from mns.factors.technical import add_intraday_trend_factors
from mns.review.report_exporter import ReportExporter
from mns.strategies.base import StrategyContext
from mns.strategies.ema21_ma55_pullback import Ema21Ma55PullbackStrategy


@dataclass(frozen=True)
class IntradayPullbackReviewConfig:
    db_path: str = "data/duckdb/mns.duckdb"
    timeframe: str = "5m"
    start_date: str | None = None
    end_date: str | None = None
    as_of_date: str | None = None
    stock_codes: list[str] | None = None
    pullback_tolerance: float = 0.003
    atr_stop_multiple: float = 1.0
    reward_multiple: float = 2.0
    initial_cash: float = 1_000_000
    per_trade_cash: float = 100_000
    risk_per_trade: float = 5_000
    max_hold_bars: int = 12
    commission_rate: float = 0.0
    stamp_tax_rate: float = 0.0
    transfer_fee_rate: float = 0.0
    slippage_rate: float = 0.0
    export_root: str = "data/reports/exports"


class IntradayPullbackReviewRunner:
    def __init__(self, config: IntradayPullbackReviewConfig) -> None:
        self.config = config
        self.store = DuckDBStore(config.db_path)
        self.market_data = LocalMarketData(self.store)

    def run(self) -> dict[str, pd.DataFrame | str | dict[str, Path]]:
        kline = self.market_data.get_kline(
            timeframe=self.config.timeframe,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            stock_codes=self.config.stock_codes,
        )
        if kline.empty:
            raise ValueError("No local intraday K-line data found. Run sync-qmt-kline first.")

        enriched = add_intraday_trend_factors(kline)
        as_of_date = self.config.as_of_date or str(pd.to_datetime(enriched["trade_date"]).max().date())
        as_of_rows = enriched[pd.to_datetime(enriched["trade_date"]).dt.date == pd.Timestamp(as_of_date).date()].copy()

        strategy = Ema21Ma55PullbackStrategy(
            pullback_tolerance=self.config.pullback_tolerance,
            atr_stop_multiple=self.config.atr_stop_multiple,
            reward_multiple=self.config.reward_multiple,
        )
        signals = strategy.generate_signals(
            as_of_rows,
            StrategyContext(
                start_date=self.config.start_date,
                end_date=self.config.end_date,
                params={
                    "pullback_tolerance": self.config.pullback_tolerance,
                    "atr_stop_multiple": self.config.atr_stop_multiple,
                    "reward_multiple": self.config.reward_multiple,
                },
            ),
        )

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        backtester = QuickReviewBacktester(
            QuickReviewConfig(
                initial_cash=self.config.initial_cash,
                hold_days=1,
                max_hold_bars=self.config.max_hold_bars,
                per_trade_cash=self.config.per_trade_cash,
                commission_rate=self.config.commission_rate,
                stamp_tax_rate=self.config.stamp_tax_rate,
                transfer_fee_rate=self.config.transfer_fee_rate,
                slippage_rate=self.config.slippage_rate,
                risk_per_trade=self.config.risk_per_trade,
                respect_signal_levels=True,
            )
        )
        result = backtester.run(signals, kline, run_id=run_id)
        trades = result["trades"]
        portfolio_snapshots = result["portfolio_snapshots"]
        summary = summarize_trades(trades)

        self._persist_run(
            run_id=run_id,
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

        signals_path = Path(self.config.export_root) / f"{run_id}_signals.csv"
        signals.to_csv(signals_path, index=False)
        outputs["signals"] = signals_path

        return {
            "run_id": run_id,
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
        signals: pd.DataFrame,
        trades: pd.DataFrame,
        portfolio_snapshots: pd.DataFrame,
        summary: dict[str, float | int],
    ) -> None:
        self.store.replace_backtest_run(
            run_id=run_id,
            run_type="intraday_pullback_review",
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            initial_cash=self.config.initial_cash,
            config={
                "timeframe": self.config.timeframe,
                "as_of_date": self.config.as_of_date,
                "pullback_tolerance": self.config.pullback_tolerance,
                "atr_stop_multiple": self.config.atr_stop_multiple,
                "reward_multiple": self.config.reward_multiple,
                "per_trade_cash": self.config.per_trade_cash,
                "risk_per_trade": self.config.risk_per_trade,
                "max_hold_bars": self.config.max_hold_bars,
                "commission_rate": self.config.commission_rate,
                "stamp_tax_rate": self.config.stamp_tax_rate,
                "transfer_fee_rate": self.config.transfer_fee_rate,
                "slippage_rate": self.config.slippage_rate,
            },
            result=summary,
        )
        self.store.replace_signals_for_run(run_id, self._prepare_signals(signals, run_id))
        self.store.replace_trades_for_run(run_id, self._to_trade_actions(trades))
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
                    "reason": trade.get("exit_reason", trade.get("reason", "")),
                }
            )
        return pd.DataFrame(rows)
