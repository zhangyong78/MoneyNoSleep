from __future__ import annotations

import pandas as pd

from mns.data.models import DataQualityIssue


def validate_kline_frame(df: pd.DataFrame) -> list[DataQualityIssue]:
    """Return quality issues for a normalized K-line DataFrame."""

    issues: list[DataQualityIssue] = []
    required = ["open", "high", "low", "close", "volume", "amount"]

    for column in required:
        if column not in df.columns:
            issues.append(DataQualityIssue(-1, column, "missing required column"))
            return issues

    for idx, row in df.reset_index(drop=True).iterrows():
        high = row["high"]
        low = row["low"]
        open_ = row["open"]
        close = row["close"]
        volume = row["volume"]
        amount = row["amount"]

        if pd.isna(high) or pd.isna(low) or pd.isna(open_) or pd.isna(close):
            issues.append(DataQualityIssue(idx, "ohlc", "missing OHLC value"))
            continue
        if high < open_:
            issues.append(DataQualityIssue(idx, "high", "high is lower than open"))
        if high < close:
            issues.append(DataQualityIssue(idx, "high", "high is lower than close"))
        if low > open_:
            issues.append(DataQualityIssue(idx, "low", "low is higher than open"))
        if low > close:
            issues.append(DataQualityIssue(idx, "low", "low is higher than close"))
        if high < low:
            issues.append(DataQualityIssue(idx, "high", "high is lower than low"))
        if pd.notna(volume) and volume < 0:
            issues.append(DataQualityIssue(idx, "volume", "volume is negative"))
        if pd.notna(amount) and amount < 0:
            issues.append(DataQualityIssue(idx, "amount", "amount is negative"))

    return issues
