from __future__ import annotations

import math

import pandas as pd


def ma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window, min_periods=window).mean()


def ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False, min_periods=span).mean()


def atr(df: pd.DataFrame, window: int = 10) -> pd.Series:
    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window=window, min_periods=window).mean()


def n_day_high(high: pd.Series, window: int) -> pd.Series:
    return high.rolling(window=window, min_periods=window).max()


def kline_angle(close: pd.Series, window: int) -> pd.Series:
    delta = close - close.shift(window)
    return delta.apply(lambda value: math.degrees(math.atan(value)) if pd.notna(value) else float("nan"))


def add_default_daily_technical_factors(df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.sort_values(["stock_code", "bar_time"]).copy()
    grouped = enriched.groupby("stock_code", group_keys=False)
    enriched["ema21"] = grouped["close"].transform(lambda s: ema(s, 21))
    enriched["ma55"] = grouped["close"].transform(lambda s: ma(s, 55))
    enriched["n20_high"] = grouped["high"].transform(lambda s: n_day_high(s, 20))
    enriched["kline_angle_5"] = grouped["close"].transform(lambda s: kline_angle(s, 5))
    return enriched


def add_daily_trend_following_factors(df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.sort_values(["stock_code", "bar_time"]).copy()
    grouped = enriched.groupby("stock_code", group_keys=False)

    enriched["ema20"] = grouped["close"].transform(lambda s: ema(s, 20))
    enriched["ema50"] = grouped["close"].transform(lambda s: ema(s, 50))
    atr_parts = [atr(group, 14) for _, group in enriched.groupby("stock_code", sort=False)]
    enriched["atr14"] = pd.concat(atr_parts).sort_index()
    enriched["ema20_slope_5"] = enriched.groupby("stock_code", group_keys=False)["ema20"].transform(
        lambda s: (s - s.shift(5)) / s.shift(5)
    )
    enriched["ema50_slope_5"] = enriched.groupby("stock_code", group_keys=False)["ema50"].transform(
        lambda s: (s - s.shift(5)) / s.shift(5)
    )
    enriched["ema20_ema50_bias"] = (enriched["ema20"] - enriched["ema50"]) / enriched["ema50"]
    enriched["close_change_1"] = enriched.groupby("stock_code", group_keys=False)["close"].transform(lambda s: s / s.shift(1) - 1)
    volume_ma20 = grouped["volume"].transform(lambda s: s.shift(1).rolling(window=20, min_periods=20).mean())
    enriched["volume_ma20"] = volume_ma20
    enriched["volume_ratio_20"] = enriched["volume"] / volume_ma20
    close_above_ema20 = enriched["close"] > enriched["ema20"]
    enriched["recent_close_above_ema20_3"] = (
        close_above_ema20.groupby(enriched["stock_code"]).transform(lambda s: s.shift(1).rolling(window=3, min_periods=1).max())
    ).fillna(False)
    return enriched


def add_intraday_trend_factors(df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.sort_values(["stock_code", "bar_time"]).copy()
    grouped = enriched.groupby("stock_code", group_keys=False)
    enriched["ema21"] = grouped["close"].transform(lambda s: ema(s, 21))
    enriched["ma55"] = grouped["close"].transform(lambda s: ma(s, 55))
    atr_parts = [atr(group, 10) for _, group in enriched.groupby("stock_code", sort=False)]
    enriched["atr10"] = pd.concat(atr_parts).sort_index()
    enriched["distance_to_ema21"] = (enriched["close"] - enriched["ema21"]) / enriched["ema21"]
    enriched["distance_to_ma55"] = (enriched["close"] - enriched["ma55"]) / enriched["ma55"]
    enriched["ema21_slope_3"] = enriched.groupby("stock_code", group_keys=False)["ema21"].transform(
        lambda s: s - s.shift(3)
    )
    return enriched
