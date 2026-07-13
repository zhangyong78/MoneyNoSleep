from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.timeframes import normalize_timeframe, timeframe_aliases


@dataclass(frozen=True)
class StockFeatureStoreConfig:
    db_path: str = "data/duckdb/mns.duckdb"
    timeframe: str = "1d"
    start_date: str | None = None
    end_date: str | None = None
    stock_codes: list[str] | None = None


class StockFeatureStoreBuilder:
    def __init__(self, config: StockFeatureStoreConfig) -> None:
        self.config = config
        self.store = DuckDBStore(config.db_path)

    def run(self) -> dict[str, object]:
        bars = self._load_bars()
        if bars.empty:
            raise ValueError("No local daily bars were loaded for stock feature generation.")

        features = self._build_features(bars)
        followups = self._build_followups(features)

        if self.config.start_date:
            start_ts = pd.Timestamp(self.config.start_date)
            features = features[features["trade_date"] >= start_ts].copy()
            followups = followups[followups["anchor_date"] >= start_ts].copy()

        feature_rows = self.store.replace_stock_daily_features(features)
        followup_rows = self.store.replace_stock_daily_followups(followups)
        min_date = features["trade_date"].min() if not features.empty else None
        max_date = features["trade_date"].max() if not features.empty else None
        return {
            "feature_rows": feature_rows,
            "followup_rows": followup_rows,
            "start_date": str(pd.Timestamp(min_date).date()) if min_date is not None and pd.notna(min_date) else None,
            "end_date": str(pd.Timestamp(max_date).date()) if max_date is not None and pd.notna(max_date) else None,
            "stock_count": int(features["stock_code"].nunique()) if not features.empty else 0,
        }

    def _load_bars(self) -> pd.DataFrame:
        filters = ["timeframe IN (SELECT UNNEST(?))"]
        params: list[object] = [list(timeframe_aliases(self.config.timeframe))]
        if self.config.end_date:
            filters.append("trade_date <= ?")
            params.append(self.config.end_date)
        if self.config.stock_codes:
            filters.append("stock_code IN (SELECT UNNEST(?))")
            params.append(self.config.stock_codes)
        sql = f"""
            SELECT
                stock_code,
                COALESCE(NULLIF(stock_name, ''), stock_code) AS stock_name,
                trade_date,
                bar_time,
                timeframe,
                open,
                high,
                low,
                close,
                volume,
                amount,
                turnover,
                pre_close,
                limit_up_price,
                limit_down_price
            FROM kline_bars
            WHERE {' AND '.join(filters)}
            ORDER BY stock_code, trade_date
        """
        frame = self.store.query_frame(sql, tuple(params))
        if frame.empty:
            return frame
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        frame["bar_time"] = pd.to_datetime(frame["bar_time"])
        frame["timeframe"] = normalize_timeframe(self.config.timeframe)
        return frame

    @staticmethod
    def _days_since_event(flag_series: pd.Series) -> pd.Series:
        event_index = np.where(flag_series.fillna(False).to_numpy(), np.arange(len(flag_series)), np.nan)
        last_index = pd.Series(event_index, index=flag_series.index, dtype=float).ffill()
        result = pd.Series(pd.NA, index=flag_series.index, dtype="Int64")
        valid_mask = last_index.notna()
        if valid_mask.any():
            result.loc[valid_mask] = (
                np.arange(len(flag_series))[valid_mask.to_numpy()] - last_index.loc[valid_mask].astype(int).to_numpy()
            )
        return result

    def _build_features(self, bars: pd.DataFrame) -> pd.DataFrame:
        parts: list[pd.DataFrame] = []
        for _, stock_bars in bars.groupby("stock_code", sort=False):
            frame = stock_bars.sort_values("trade_date").reset_index(drop=True).copy()
            frame["pct_chg"] = np.where(
                frame["pre_close"].fillna(0).abs() < 1e-12,
                np.nan,
                frame["close"] / frame["pre_close"] - 1.0,
            )
            body_high = frame[["open", "close"]].max(axis=1)
            body_low = frame[["open", "close"]].min(axis=1)
            frame["upper_shadow_pct"] = np.where(frame["close"].abs() < 1e-12, np.nan, (frame["high"] - body_high) / frame["close"])
            frame["lower_shadow_pct"] = np.where(frame["close"].abs() < 1e-12, np.nan, (body_low - frame["low"]) / frame["close"])
            frame["body_pct"] = np.where(frame["close"].abs() < 1e-12, np.nan, (frame["close"] - frame["open"]).abs() / frame["close"])
            frame["amplitude_pct"] = np.where(frame["close"].abs() < 1e-12, np.nan, (frame["high"] - frame["low"]) / frame["close"])

            for window in (20, 55, 120):
                frame[f"ma{window}"] = frame["close"].rolling(window).mean()

            frame["prev_close_calc"] = frame["close"].shift(1)
            frame["prev_ma20"] = frame["ma20"].shift(1)
            frame["prev_ma55"] = frame["ma55"].shift(1)
            frame["break_ma20_today"] = (
                frame["ma20"].notna()
                & frame["prev_ma20"].notna()
                & (frame["prev_close_calc"] <= frame["prev_ma20"])
                & (frame["close"] > frame["ma20"])
            )
            frame["break_ma55_today"] = (
                frame["ma55"].notna()
                & frame["prev_ma55"].notna()
                & (frame["prev_close_calc"] <= frame["prev_ma55"])
                & (frame["close"] > frame["ma55"])
            )

            frame["last_break_ma20_date"] = frame["trade_date"].where(frame["break_ma20_today"]).ffill()
            frame["last_break_ma55_date"] = frame["trade_date"].where(frame["break_ma55_today"]).ffill()
            frame["days_since_break_ma20"] = self._days_since_event(frame["break_ma20_today"])
            frame["days_since_break_ma55"] = self._days_since_event(frame["break_ma55_today"])

            frame["limit_up"] = np.where(
                frame["limit_up_price"].notna(),
                frame["close"] >= frame["limit_up_price"] * 0.995,
                frame["pct_chg"] >= 0.095,
            )
            frame["limit_down"] = np.where(
                frame["limit_down_price"].notna(),
                frame["close"] <= frame["limit_down_price"] * 1.005,
                frame["pct_chg"] <= -0.095,
            )

            parts.append(frame)

        feature_df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        if feature_df.empty:
            return feature_df
        feature_df["created_time"] = pd.Timestamp.utcnow().tz_localize(None)
        ordered_columns = [
            "stock_code",
            "stock_name",
            "trade_date",
            "bar_time",
            "timeframe",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "turnover",
            "pre_close",
            "pct_chg",
            "upper_shadow_pct",
            "lower_shadow_pct",
            "body_pct",
            "amplitude_pct",
            "ma20",
            "ma55",
            "ma120",
            "break_ma20_today",
            "break_ma55_today",
            "last_break_ma20_date",
            "last_break_ma55_date",
            "days_since_break_ma20",
            "days_since_break_ma55",
            "limit_up",
            "limit_down",
            "created_time",
        ]
        return feature_df[ordered_columns]

    def _build_followups(self, features: pd.DataFrame) -> pd.DataFrame:
        parts: list[pd.DataFrame] = []
        for _, stock_features in features.groupby("stock_code", sort=False):
            frame = stock_features.sort_values("trade_date").reset_index(drop=True).copy()
            frame["available_date_5d"] = frame["trade_date"].shift(-5)
            frame["amount_sum_next_5d"] = sum(frame["amount"].shift(-offset) for offset in range(1, 6))
            frame["return_next_5d"] = frame["close"].shift(-5) / frame["close"] - 1.0
            frame["max_return_next_5d"] = (
                pd.concat([frame["close"].shift(-offset) for offset in range(1, 6)], axis=1).max(axis=1) / frame["close"] - 1.0
            )
            frame["limit_up_count_next_5d"] = sum(frame["limit_up"].shift(-offset).eq(True).astype(int) for offset in range(1, 6))
            parts.append(
                frame[
                    [
                        "stock_code",
                        "stock_name",
                        "trade_date",
                        "timeframe",
                        "available_date_5d",
                        "amount_sum_next_5d",
                        "return_next_5d",
                        "max_return_next_5d",
                        "limit_up_count_next_5d",
                    ]
                ].rename(columns={"trade_date": "anchor_date"})
            )

        followup_df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        if followup_df.empty:
            return followup_df
        followup_df["created_time"] = pd.Timestamp.utcnow().tz_localize(None)
        return followup_df[
            [
                "stock_code",
                "stock_name",
                "anchor_date",
                "timeframe",
                "available_date_5d",
                "amount_sum_next_5d",
                "return_next_5d",
                "max_return_next_5d",
                "limit_up_count_next_5d",
                "created_time",
            ]
        ]
