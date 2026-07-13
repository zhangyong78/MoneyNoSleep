from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class KlineBar:
    stock_code: str
    stock_name: str | None
    exchange: str | None
    trade_date: date
    bar_time: datetime
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    turnover: float | None = None
    pre_close: float | None = None
    adj_factor: float | None = None
    limit_up_price: float | None = None
    limit_down_price: float | None = None
    is_suspended: bool = False
    source: str = "unknown"
    updated_at: datetime | None = None
    data_quality: str = "OK"


@dataclass(frozen=True)
class DataQualityIssue:
    row_index: int
    field: str
    message: str
