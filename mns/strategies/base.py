from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class StrategyContext:
    start_date: str | None = None
    end_date: str | None = None
    params: dict[str, Any] | None = None


class Strategy(ABC):
    name: str
    timeframe: str

    def prepare(self, context: StrategyContext) -> None:
        return None

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame, context: StrategyContext) -> pd.DataFrame:
        raise NotImplementedError

    def on_order_filled(self, trade: dict[str, Any], context: StrategyContext) -> None:
        return None

    def should_exit(self, position: dict[str, Any], data: pd.DataFrame, context: StrategyContext) -> bool:
        return False
