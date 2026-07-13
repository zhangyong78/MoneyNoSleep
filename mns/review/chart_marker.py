from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ChartMarker:
    signal_time: pd.Timestamp | None = None
    buy_time: pd.Timestamp | None = None
    sell_time: pd.Timestamp | None = None
    stop_loss: float | None = None


def build_trade_markers(trade: pd.Series | dict) -> ChartMarker:
    buy_time = pd.Timestamp(trade["buy_time"]) if trade.get("buy_time") is not None else None
    sell_time = pd.Timestamp(trade["sell_time"]) if trade.get("sell_time") is not None else None
    return ChartMarker(
        signal_time=pd.Timestamp(trade["signal_time"]) if trade.get("signal_time") is not None else None,
        buy_time=buy_time,
        sell_time=sell_time,
        stop_loss=trade.get("stop_loss"),
    )
