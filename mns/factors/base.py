from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class FactorContext:
    timeframe: str
    params: dict[str, Any] | None = None


class Factor(ABC):
    name: str
    timeframe: str

    @abstractmethod
    def compute(self, data: pd.DataFrame, context: FactorContext) -> pd.Series:
        raise NotImplementedError
