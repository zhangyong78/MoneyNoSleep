from __future__ import annotations

import pandas as pd

from mns.strategies.base import Strategy, StrategyContext


class Ema21Ma55PullbackStrategy(Strategy):
    name = "ema21_ma55_pullback"
    timeframe = "5m"

    def __init__(
        self,
        *,
        pullback_tolerance: float = 0.003,
        atr_stop_multiple: float = 1.0,
        reward_multiple: float = 2.0,
    ) -> None:
        self.pullback_tolerance = pullback_tolerance
        self.atr_stop_multiple = atr_stop_multiple
        self.reward_multiple = reward_multiple

    def generate_signals(self, data: pd.DataFrame, context: StrategyContext) -> pd.DataFrame:
        if data.empty:
            return pd.DataFrame()

        required = {"stock_code", "bar_time", "close", "low", "ema21", "ma55", "atr10"}
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"missing columns for signal generation: {sorted(missing)}")

        candidates = data.copy()
        mask = (
            candidates["ema21"].notna()
            & candidates["ma55"].notna()
            & candidates["atr10"].notna()
            & (candidates["atr10"] > 0)
            & (candidates["close"] > candidates["ma55"])
            & (candidates["ema21"] > candidates["ma55"])
            & (candidates["low"] <= candidates["ema21"] * (1 + self.pullback_tolerance))
            & (candidates["close"] >= candidates["ema21"])
        )
        filtered = candidates.loc[mask].copy()
        if filtered.empty:
            return pd.DataFrame()

        filtered["strategy_name"] = self.name
        filtered["action"] = "BUY"
        filtered["timeframe"] = self.timeframe
        filtered["signal_time"] = pd.to_datetime(filtered["bar_time"])
        filtered["entry_price"] = filtered["close"]
        filtered["stop_loss"] = filtered["close"] - filtered["atr10"] * self.atr_stop_multiple
        filtered["take_profit"] = filtered["close"] + filtered["atr10"] * self.reward_multiple
        ema_slope = filtered["ema21_slope_3"] if "ema21_slope_3" in filtered.columns else pd.Series(0.0, index=filtered.index)
        filtered["score"] = ((filtered["close"] - filtered["ma55"]) / filtered["ma55"]) + ema_slope.fillna(0) / filtered["close"]
        filtered["reason"] = "ema21回踩;close>ma55;ema21>ma55"
        filtered["status"] = "NEW"
        return filtered[
            [
                "stock_code",
                "strategy_name",
                "action",
                "timeframe",
                "signal_time",
                "entry_price",
                "stop_loss",
                "take_profit",
                "score",
                "reason",
                "status",
            ]
        ].reset_index(drop=True)
