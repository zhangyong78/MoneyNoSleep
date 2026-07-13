from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StockPool:
    name: str
    stock_codes: list[str]
