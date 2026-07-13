from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Signal:
    signal_id: str
    stock_code: str
    strategy_name: str
    action: str
    timeframe: str
    signal_time: datetime
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    score: float | None = None
    reason: str | None = None
    status: str = "NEW"
