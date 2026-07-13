from __future__ import annotations

import pandas as pd


def sort_by_score(df: pd.DataFrame, *, descending: bool = True) -> pd.DataFrame:
    if "score" not in df.columns:
        return df.copy()
    return df.sort_values("score", ascending=not descending).reset_index(drop=True)
