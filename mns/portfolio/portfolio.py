from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Portfolio:
    initial_cash: float
    cash: float | None = None
    positions: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cash is None:
            self.cash = self.initial_cash
