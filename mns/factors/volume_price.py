from __future__ import annotations

import pandas as pd


def volume_ratio(volume: pd.Series, window: int = 5) -> pd.Series:
    avg = volume.shift(1).rolling(window=window, min_periods=window).mean()
    return volume / avg


def add_default_volume_price_factors(df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.sort_values(["stock_code", "bar_time"]).copy()
    grouped = enriched.groupby("stock_code", group_keys=False)
    enriched["volume_ratio_5"] = grouped["volume"].transform(lambda s: volume_ratio(s, 5))
    return enriched
