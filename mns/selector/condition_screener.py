from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


Condition = Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class ScreeningCondition:
    name: str
    predicate: Condition
    reason: str


class ConditionScreener:
    def __init__(self, conditions: list[ScreeningCondition] | None = None) -> None:
        self.conditions = conditions or []

    def add_condition(self, condition: ScreeningCondition) -> None:
        self.conditions.append(condition)

    def screen(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()

        result = df.copy()
        reasons = pd.Series([""] * len(result), index=result.index, dtype="object")
        mask = pd.Series(True, index=result.index)

        for condition in self.conditions:
            condition_mask = condition.predicate(result).fillna(False)
            mask &= condition_mask
            reasons.loc[condition_mask] = reasons.loc[condition_mask].apply(
                lambda existing: f"{existing};{condition.reason}".strip(";")
            )

        screened = result.loc[mask].copy()
        screened["candidate_reason"] = reasons.loc[mask]
        screened["score"] = screened["candidate_reason"].apply(lambda value: len([p for p in value.split(";") if p]))
        return screened


def close_above(column: str, threshold_column: str) -> ScreeningCondition:
    return ScreeningCondition(
        name=f"{column}_above_{threshold_column}",
        predicate=lambda df: df[column] > df[threshold_column],
        reason=f"{column}>{threshold_column}",
    )


def greater_than(column: str, threshold: float) -> ScreeningCondition:
    return ScreeningCondition(
        name=f"{column}_gt_{threshold}",
        predicate=lambda df: df[column] > threshold,
        reason=f"{column}>{threshold}",
    )
