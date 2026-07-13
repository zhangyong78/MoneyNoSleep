from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from mns.data.timeframes import normalize_timeframe


STANDARD_KLINE_COLUMNS = [
    "stock_code",
    "stock_name",
    "exchange",
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
    "adj_factor",
    "limit_up_price",
    "limit_down_price",
    "is_suspended",
    "source",
    "updated_at",
    "data_quality",
]


def normalize_kline_frame(df: pd.DataFrame, *, source: str, timeframe: str) -> pd.DataFrame:
    """Normalize external K-line data into the project-wide schema."""

    if df.empty:
        return pd.DataFrame(columns=STANDARD_KLINE_COLUMNS)

    normalized = df.copy()
    if "bar_time" not in normalized.columns and "trade_date" in normalized.columns:
        normalized["bar_time"] = pd.to_datetime(normalized["trade_date"])

    normalized["bar_time"] = pd.to_datetime(normalized["bar_time"])
    normalized["trade_date"] = normalized.get("trade_date", normalized["bar_time"].dt.date)
    normalized["trade_date"] = pd.to_datetime(normalized["trade_date"]).dt.date
    normalized["timeframe"] = normalize_timeframe(timeframe)
    normalized["source"] = source
    normalized["updated_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    normalized["data_quality"] = normalized.get("data_quality", "OK")
    normalized["is_suspended"] = normalized.get("is_suspended", False)

    for column in STANDARD_KLINE_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = None

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turnover",
        "pre_close",
        "adj_factor",
        "limit_up_price",
        "limit_down_price",
    ]
    for column in numeric_columns:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    return normalized[STANDARD_KLINE_COLUMNS]
