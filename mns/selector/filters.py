from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FilterResult:
    passed: pd.DataFrame
    rejected: pd.DataFrame


def exclude_st(df: pd.DataFrame) -> FilterResult:
    if "is_st" not in df.columns:
        return FilterResult(df.copy(), df.iloc[0:0].copy())
    mask = ~df["is_st"].fillna(False)
    return FilterResult(df.loc[mask].copy(), df.loc[~mask].copy())


def exclude_suspended(df: pd.DataFrame) -> FilterResult:
    if "is_suspended" not in df.columns:
        return FilterResult(df.copy(), df.iloc[0:0].copy())
    mask = ~df["is_suspended"].fillna(False)
    return FilterResult(df.loc[mask].copy(), df.loc[~mask].copy())
