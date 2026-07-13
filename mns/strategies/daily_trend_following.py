from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DailyTrendFollowingConfig:
    min_bias: float = 0.02
    min_close_above_ema20: float = 0.002
    pullback_floor: float = 0.995
    min_volume_ratio: float = 1.2
    atr_stop_multiple: float = 1.5


class DailyTrendFollowingStrategy:
    name = "daily_trend_following"
    timeframe = "1d"

    def __init__(self, config: DailyTrendFollowingConfig | None = None) -> None:
        self.config = config or DailyTrendFollowingConfig()

    def build_candidates(self, data: pd.DataFrame) -> pd.DataFrame:
        required = {
            "stock_code",
            "stock_name",
            "trade_date",
            "bar_time",
            "close",
            "low",
            "volume",
            "ema20",
            "ema50",
            "ema50_slope_5",
            "ema20_ema50_bias",
            "volume_ratio_20",
            "atr14",
            "recent_close_above_ema20_3",
        }
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"missing columns for daily trend following strategy: {sorted(missing)}")

        candidates = data.copy()
        previous_close = candidates.groupby("stock_code", group_keys=False)["close"].shift(1)
        trend_mask = (
            candidates["ema20"].notna()
            & candidates["ema50"].notna()
            & candidates["atr14"].notna()
            & (candidates["close"] > candidates["ema20"])
            & (candidates["ema20"] > candidates["ema50"])
            & (candidates["ema50_slope_5"] > 0)
            & (candidates["ema20_ema50_bias"] > self.config.min_bias)
            & (candidates["volume_ratio_20"] >= self.config.min_volume_ratio)
        )
        filtered = candidates.loc[trend_mask].copy()
        if filtered.empty:
            return filtered

        condition_a = (
            (filtered["close"] > previous_close.loc[filtered.index])
            & (filtered["low"] <= filtered["ema20"])
            & (filtered["close"] >= filtered["ema20"] * (1 + self.config.min_close_above_ema20))
        )
        condition_b = (
            filtered["recent_close_above_ema20_3"].astype(bool)
            & (filtered["low"] >= filtered["ema20"] * self.config.pullback_floor)
            & (filtered["close"] > previous_close.loc[filtered.index])
        )

        entry_mask = condition_a | condition_b
        signals = filtered.loc[entry_mask].copy()
        if signals.empty:
            return signals

        signals["entry_condition"] = "A"
        signals.loc[condition_b.loc[signals.index], "entry_condition"] = "B"
        signals.loc[condition_a.loc[signals.index] & condition_b.loc[signals.index], "entry_condition"] = "A+B"
        signals["entry_price"] = signals["close"]
        signals["stop_loss"] = signals["entry_price"] - self.config.atr_stop_multiple * signals["atr14"]
        signals["candidate_reason"] = (
            "trend_ok;volume_ok;entry_" + signals["entry_condition"].astype(str)
        )
        signals["score"] = (
            signals["ema20_ema50_bias"].fillna(0)
            + signals["ema50_slope_5"].fillna(0) * 3
            + (signals["volume_ratio_20"].fillna(0) - self.config.min_volume_ratio)
        )
        return signals

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        candidates = self.build_candidates(data)
        if candidates.empty:
            return pd.DataFrame()

        signals = candidates.copy()
        signals["strategy_name"] = self.name
        signals["action"] = "BUY"
        signals["timeframe"] = self.timeframe
        signals["signal_time"] = pd.to_datetime(signals["bar_time"])
        signals["take_profit"] = signals["entry_price"] + 2 * (signals["entry_price"] - signals["stop_loss"])
        signals["reason"] = signals["candidate_reason"]
        signals["status"] = "NEW"
        return signals[
            [
                "stock_code",
                "stock_name",
                "trade_date",
                "bar_time",
                "strategy_name",
                "action",
                "timeframe",
                "signal_time",
                "entry_price",
                "stop_loss",
                "take_profit",
                "atr14",
                "ema20",
                "ema50",
                "ema20_slope_5",
                "ema50_slope_5",
                "volume_ratio_20",
                "entry_condition",
                "score",
                "reason",
                "status",
            ]
        ].reset_index(drop=True)
