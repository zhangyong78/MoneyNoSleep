from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mns.factors.technical import atr


@dataclass(frozen=True)
class TwoStageTrendStrategyConfig:
    attention_window: int = 60
    strong_change_pct: float = 0.06
    strong_volume_ratio: float = 1.8
    limit_up_close_ratio: float = 0.985
    breakout_window: int = 60
    breakout_volume_ratio: float = 1.5
    ma10_window: int = 10
    ma20_window: int = 20
    ma60_window: int = 60
    ma20_slope_days: int = 3
    volume_ma_window: int = 20
    consolidation_window: int = 5
    entry_volume_ratio: float = 1.2
    entry_volume_ratio_max: float = 3.0
    entry_breakout_pct_max: float = 0.03
    max_chase_pct: float = 0.12
    chase_window: int = 20


class TwoStageTrendStrategy:
    name = "two_stage_trend"
    timeframe = "1d"

    def __init__(self, config: TwoStageTrendStrategyConfig | None = None) -> None:
        self.config = config or TwoStageTrendStrategyConfig()

    def enrich(self, data: pd.DataFrame) -> pd.DataFrame:
        required = {"stock_code", "stock_name", "trade_date", "bar_time", "open", "high", "low", "close", "volume"}
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"missing columns for two-stage trend strategy: {sorted(missing)}")
        if data.empty:
            return data.copy()

        frame = data.sort_values(["stock_code", "bar_time"]).copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        frame["bar_time"] = pd.to_datetime(frame["bar_time"])
        grouped = frame.groupby("stock_code", group_keys=False)
        frame["prev_close"] = grouped["close"].shift(1)
        frame["close_change"] = frame["close"] / frame["prev_close"] - 1.0
        frame["ma10"] = grouped["close"].transform(lambda s: s.rolling(self.config.ma10_window, min_periods=self.config.ma10_window).mean())
        frame["ma20"] = grouped["close"].transform(lambda s: s.rolling(self.config.ma20_window, min_periods=self.config.ma20_window).mean())
        frame["ma60"] = grouped["close"].transform(lambda s: s.rolling(self.config.ma60_window, min_periods=self.config.ma60_window).mean())
        frame["ma20_prior"] = grouped["ma20"].shift(self.config.ma20_slope_days)
        frame["ma60_prior"] = grouped["ma60"].shift(1)
        frame["volume_ma"] = grouped["volume"].transform(
            lambda s: s.shift(1).rolling(self.config.volume_ma_window, min_periods=self.config.volume_ma_window).mean()
        )
        frame["volume_ratio_20"] = frame["volume"] / frame["volume_ma"].where(frame["volume_ma"] > 0)
        volume_ma5 = grouped["volume"].transform(
            lambda s: s.shift(1).rolling(5, min_periods=5).mean()
        )
        frame["volume_ratio_5"] = frame["volume"] / volume_ma5.where(volume_ma5 > 0)
        frame[["volume_ratio_20", "volume_ratio_5"]] = frame[["volume_ratio_20", "volume_ratio_5"]].replace([np.inf, -np.inf], np.nan)
        frame["prior_high_60"] = grouped["close"].transform(
            lambda s: s.shift(1).rolling(self.config.breakout_window, min_periods=self.config.breakout_window).max()
        )
        frame["prior_high_5"] = grouped["close"].transform(
            lambda s: s.shift(1).rolling(self.config.consolidation_window, min_periods=self.config.consolidation_window).max()
        )
        frame["prior_high_20"] = grouped["close"].transform(
            lambda s: s.shift(1).rolling(self.config.chase_window, min_periods=self.config.chase_window).max()
        )
        frame["atr14"] = 0.0
        for _, positions in frame.groupby("stock_code").groups.items():
            frame.loc[positions, "atr14"] = atr(frame.loc[positions], 14)

        limit_up = pd.to_numeric(frame.get("limit_up_price"), errors="coerce")
        limit_near = limit_up.notna() & (frame["close"] >= limit_up * self.config.limit_up_close_ratio)
        frame["attention_strong_bar"] = limit_near | (
            (frame["close_change"] >= self.config.strong_change_pct)
            & (frame["volume_ratio_20"] >= self.config.strong_volume_ratio)
        )
        frame["attention_breakout"] = (
            (frame["close"] > frame["prior_high_60"])
            & (frame["volume_ratio_20"] >= self.config.breakout_volume_ratio)
        )
        frame["attention_ma60_cross"] = (
            (frame["close"] > frame["ma60"])
            & (frame["prev_close"] <= frame["ma60_prior"])
            & (frame["ma20"] >= frame["ma20_prior"])
        )
        frame["attention_raw"] = frame[["attention_strong_bar", "attention_breakout", "attention_ma60_cross"]].any(axis=1)
        previous_attention_raw = frame.groupby("stock_code", group_keys=False)["attention_raw"].shift(1).astype("boolean").fillna(False).astype(bool)
        frame["attention"] = frame["attention_raw"] & ~previous_attention_raw
        frame["attention_reason_current"] = ""
        frame.loc[frame["attention_strong_bar"], "attention_reason_current"] = "strong_bar"
        frame.loc[frame["attention_breakout"], "attention_reason_current"] = frame.loc[
            frame["attention_breakout"], "attention_reason_current"
        ].replace("", "breakout")
        frame.loc[frame["attention_ma60_cross"], "attention_reason_current"] = frame.loc[
            frame["attention_ma60_cross"], "attention_reason_current"
        ].replace("", "ma60_cross")

        frame["attention_reason"] = ""
        frame["watch_active"] = False
        frame["watch_event_id"] = 0
        for _, group in frame.groupby("stock_code", sort=False):
            attention_positions = group.index.to_series().where(group["attention"]).shift(1).ffill()
            bars_since = pd.Series(range(len(group)), index=group.index) - attention_positions.map(
                {index: position for position, index in enumerate(group.index)}
            )
            frame.loc[group.index, "watch_active"] = (bars_since > 0) & (bars_since <= self.config.attention_window)
            frame.loc[group.index, "attention_reason"] = (
                group["attention_reason_current"].where(group["attention"]).shift(1).ffill().fillna("")
            )
            frame.loc[group.index, "watch_event_id"] = group["attention"].cumsum().shift(1).fillna(0).astype(int)

        frame["trend_base"] = (
            (frame["close"] > frame["ma10"])
            & (frame["close"] > frame["ma20"])
            & (frame["close"] > frame["ma60"])
            & (frame["ma10"] >= frame["ma20"])
            & (frame["ma20"] >= frame["ma20_prior"])
        )
        frame["range_breakout"] = frame["close"] > frame["prior_high_5"]
        frame["volume_confirm"] = frame["volume_ratio_5"] >= self.config.entry_volume_ratio
        frame["not_chasing"] = frame["close"] <= frame["prior_high_20"] * (1.0 + self.config.max_chase_pct)
        frame["confirmation_count"] = frame[["range_breakout", "volume_confirm", "not_chasing"]].sum(axis=1)
        frame["breakout_pct"] = frame["close"] / frame["prior_high_5"] - 1.0
        frame["entry_quality"] = (
            frame["range_breakout"]
            & frame["volume_confirm"]
            & frame["volume_ratio_5"].between(self.config.entry_volume_ratio, self.config.entry_volume_ratio_max)
            & frame["breakout_pct"].between(0.0, self.config.entry_breakout_pct_max)
        )
        frame["is_st"] = frame["stock_name"].fillna("").astype(str).str.upper().str.contains("ST")
        frame["entry_candidate"] = (
            ~frame["is_st"] & frame["watch_active"] & frame["trend_base"] & frame["entry_quality"]
        )
        frame["entry_signal"] = False
        candidate_rows = frame.loc[frame["entry_candidate"]].copy()
        if not candidate_rows.empty:
            first_in_event = candidate_rows.groupby(["stock_code", "watch_event_id"]).cumcount() == 0
            frame.loc[candidate_rows.index, "entry_signal"] = first_in_event.to_numpy()
        frame["entry_date"] = grouped["trade_date"].shift(-1)
        return frame

    def build_candidates(self, data: pd.DataFrame) -> pd.DataFrame:
        enriched = self.enrich(data)
        return enriched.loc[enriched["entry_candidate"]].copy().reset_index(drop=True)

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        return self.signals_from_enriched(self.enrich(data))

    def signals_from_enriched(self, enriched: pd.DataFrame) -> pd.DataFrame:
        candidates = enriched.loc[enriched["entry_signal"]].copy().reset_index(drop=True)
        candidates = candidates.loc[candidates["entry_date"].notna()].copy()
        if candidates.empty:
            return pd.DataFrame()

        candidates["strategy_name"] = self.name
        candidates["action"] = "BUY"
        candidates["timeframe"] = self.timeframe
        candidates["signal_time"] = pd.to_datetime(candidates["bar_time"])
        attention_bonus = candidates["attention_reason"].map({"breakout": 0.5, "ma60_cross": 0.25}).fillna(0.0)
        candidates["score"] = (
            candidates["confirmation_count"].astype(float)
            + candidates["volume_ratio_5"].clip(upper=self.config.entry_volume_ratio_max).fillna(0.0)
            - candidates["breakout_pct"].clip(lower=0.0).fillna(0.0) * 10.0
            + attention_bonus
        )
        reasons = []
        for _, row in candidates.iterrows():
            items = ["trend_base"]
            items.extend(name for name in ("range_breakout", "volume_confirm", "not_chasing") if bool(row[name]))
            reasons.append(";".join(items))
        candidates["reason"] = reasons
        candidates["status"] = "NEW"
        return candidates[
            [
                "stock_code", "stock_name", "trade_date", "bar_time", "strategy_name", "action", "timeframe",
                "signal_time", "entry_date", "score", "volume_ratio_5", "breakout_pct", "attention_reason",
                "watch_event_id", "reason", "status", "atr14",
            ]
        ].reset_index(drop=True)
