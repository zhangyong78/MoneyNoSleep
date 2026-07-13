from __future__ import annotations

import pandas as pd

from mns.strategies.base import Strategy, StrategyContext


class NextOpenHoldNStrategy(Strategy):
    name = "next_open_hold_n"
    timeframe = "1d"

    def __init__(self, hold_days: int = 5) -> None:
        if hold_days < 1:
            raise ValueError("hold_days must be at least 1")
        self.hold_days = hold_days

    def generate_signals(self, data: pd.DataFrame, context: StrategyContext) -> pd.DataFrame:
        if data.empty:
            return pd.DataFrame()
        required = {"stock_code", "bar_time", "close"}
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"missing columns for signal generation: {sorted(missing)}")

        signals = data[["stock_code", "bar_time", "close"]].copy()
        signals["strategy_name"] = self.name
        signals["action"] = "BUY"
        signals["timeframe"] = self.timeframe
        signals["signal_time"] = pd.to_datetime(signals["bar_time"])
        signals["entry_price"] = signals["close"]
        signals["score"] = data["score"] if "score" in data.columns else 1.0
        signals["reason"] = data["candidate_reason"] if "candidate_reason" in data.columns else "candidate"
        signals["status"] = "NEW"
        return signals[
            [
                "stock_code",
                "strategy_name",
                "action",
                "timeframe",
                "signal_time",
                "entry_price",
                "score",
                "reason",
                "status",
            ]
        ]
