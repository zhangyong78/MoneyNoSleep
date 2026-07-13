from __future__ import annotations

from datetime import datetime, time, timezone
import math

import pandas as pd

from mns.data.normalizer import normalize_kline_frame
from mns.data.timeframes import normalize_timeframe


_TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}

_MORNING_SESSION_START = time(9, 30)
_MORNING_SESSION_END = time(11, 30)
_AFTERNOON_SESSION_START = time(13, 0)
_AFTERNOON_SESSION_END = time(15, 0)


def can_resample_timeframe(source_timeframe: str, target_timeframe: str) -> bool:
    source = normalize_timeframe(source_timeframe)
    target = normalize_timeframe(target_timeframe)
    if source == target:
        return True
    if target == "1d":
        return source in _TIMEFRAME_MINUTES
    source_minutes = _TIMEFRAME_MINUTES.get(source)
    target_minutes = _TIMEFRAME_MINUTES.get(target)
    if source_minutes is None or target_minutes is None:
        return False
    return source_minutes < target_minutes and target_minutes % source_minutes == 0


def resample_kline_frame(
    frame: pd.DataFrame,
    *,
    source_timeframe: str,
    target_timeframe: str,
    source_label: str | None = None,
) -> pd.DataFrame:
    source = normalize_timeframe(source_timeframe)
    target = normalize_timeframe(target_timeframe)
    if not can_resample_timeframe(source, target):
        raise ValueError(f"Cannot resample {source_timeframe} to {target_timeframe}")

    if frame.empty:
        return normalize_kline_frame(pd.DataFrame(), source=source_label or "resampled", timeframe=target)

    prepared = frame.copy()
    prepared["bar_time"] = pd.to_datetime(prepared["bar_time"], errors="coerce")
    for column in ("pre_close", "adj_factor", "limit_up_price", "limit_down_price", "stock_name", "exchange", "turnover", "source", "is_suspended"):
        if column not in prepared.columns:
            prepared[column] = None if column != "is_suspended" else False
    prepared = prepared.dropna(subset=["stock_code", "bar_time"]).sort_values(["stock_code", "bar_time"]).reset_index(drop=True)
    if prepared.empty:
        return normalize_kline_frame(pd.DataFrame(), source=source_label or "resampled", timeframe=target)

    prepared["trade_date"] = pd.to_datetime(prepared.get("trade_date", prepared["bar_time"]), errors="coerce").dt.date
    prepared = prepared.dropna(subset=["trade_date"]).reset_index(drop=True)
    if prepared.empty:
        return normalize_kline_frame(pd.DataFrame(), source=source_label or "resampled", timeframe=target)

    if target == "1d":
        grouped = _aggregate_daily(prepared)
    else:
        prepared["_target_bar_time"] = prepared["bar_time"].map(lambda value: _bucket_bar_time(value, target))
        prepared = prepared.dropna(subset=["_target_bar_time"]).reset_index(drop=True)
        grouped = _aggregate_intraday(prepared, target_timeframe=target)

    return normalize_kline_frame(grouped, source=_derive_source_label(prepared, source, source_label), timeframe=target)


def _aggregate_daily(prepared: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        prepared.groupby(["stock_code", "trade_date"], as_index=False)
        .agg(
            stock_name=("stock_name", "first"),
            exchange=("exchange", "first"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            amount=("amount", "sum"),
            turnover=("turnover", "sum"),
            pre_close=("pre_close", "first"),
            adj_factor=("adj_factor", "last"),
            limit_up_price=("limit_up_price", "max"),
            limit_down_price=("limit_down_price", "min"),
            is_suspended=("is_suspended", "all"),
        )
    )
    grouped["bar_time"] = pd.to_datetime(grouped["trade_date"])
    grouped["timeframe"] = "1d"
    return grouped


def _aggregate_intraday(prepared: pd.DataFrame, *, target_timeframe: str) -> pd.DataFrame:
    grouped = (
        prepared.groupby(["stock_code", "trade_date", "_target_bar_time"], as_index=False)
        .agg(
            stock_name=("stock_name", "first"),
            exchange=("exchange", "first"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            amount=("amount", "sum"),
            turnover=("turnover", "sum"),
            pre_close=("pre_close", "first"),
            adj_factor=("adj_factor", "last"),
            limit_up_price=("limit_up_price", "max"),
            limit_down_price=("limit_down_price", "min"),
            is_suspended=("is_suspended", "all"),
        )
        .rename(columns={"_target_bar_time": "bar_time"})
        .sort_values(["stock_code", "bar_time"])
        .reset_index(drop=True)
    )
    grouped["timeframe"] = target_timeframe
    return grouped


def _bucket_bar_time(value: pd.Timestamp, target_timeframe: str) -> pd.Timestamp | pd.NaT:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return pd.NaT
    target_minutes = _TIMEFRAME_MINUTES[normalize_timeframe(target_timeframe)]
    session_start = _session_start_for_timestamp(timestamp)
    if session_start is None:
        return pd.NaT
    delta_minutes = int((timestamp - session_start).total_seconds() // 60)
    if delta_minutes < 0:
        return pd.NaT
    bucket_index = max(1, math.ceil(delta_minutes / target_minutes))
    return session_start + pd.Timedelta(minutes=bucket_index * target_minutes)


def _session_start_for_timestamp(timestamp: pd.Timestamp) -> pd.Timestamp | None:
    current_time = timestamp.time()
    if _MORNING_SESSION_START < current_time <= _MORNING_SESSION_END:
        return timestamp.normalize() + pd.Timedelta(hours=9, minutes=30)
    if _AFTERNOON_SESSION_START < current_time <= _AFTERNOON_SESSION_END:
        return timestamp.normalize() + pd.Timedelta(hours=13)
    return None


def _derive_source_label(frame: pd.DataFrame, source_timeframe: str, explicit_label: str | None) -> str:
    if explicit_label:
        return explicit_label
    unique_sources = [value for value in frame.get("source", pd.Series(dtype=object)).dropna().astype(str).unique().tolist() if value]
    if unique_sources:
        return f"{unique_sources[0]}_resampled_from_{source_timeframe}"
    return f"resampled_from_{source_timeframe}"
