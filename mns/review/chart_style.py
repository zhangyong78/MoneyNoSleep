from __future__ import annotations

import pandas as pd


UP_COLOR = "#d14a61"
DOWN_COLOR = "#1a9b5f"
LIMIT_UP_COLOR = "#f59e0b"


def build_limit_up_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool)

    close = _numeric_series(frame, "close")
    limit_up_price = _numeric_series(frame, "limit_up_price")
    pre_close = _numeric_series(frame, "pre_close")

    has_limit_price = limit_up_price.notna()
    by_limit_price = has_limit_price & (close >= limit_up_price * 0.995)

    valid_pre_close = pre_close.notna() & (pre_close.abs() > 1e-12)
    pct_change = close / pre_close - 1.0
    by_pct_change = (~has_limit_price) & valid_pre_close & (pct_change >= 0.095)

    return (by_limit_price | by_pct_change).fillna(False)


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series(float("nan"), index=frame.index, dtype="float64")


def build_kline_colors(frame: pd.DataFrame) -> list[str]:
    limit_up_mask = build_limit_up_mask(frame)
    open_price = pd.to_numeric(frame.get("open"), errors="coerce")
    close_price = pd.to_numeric(frame.get("close"), errors="coerce")

    colors: list[str] = []
    for is_limit_up, open_value, close_value in zip(limit_up_mask, open_price, close_price):
        if is_limit_up:
            colors.append(LIMIT_UP_COLOR)
        elif pd.notna(close_value) and pd.notna(open_value) and close_value >= open_value:
            colors.append(UP_COLOR)
        else:
            colors.append(DOWN_COLOR)
    return colors
