from __future__ import annotations

from collections import Counter

import pandas as pd


def count_problem_tags(reviews: pd.DataFrame) -> pd.DataFrame:
    counter: Counter[str] = Counter()
    if reviews.empty or "problem_tags" not in reviews.columns:
        return pd.DataFrame(columns=["problem_tag", "count"])
    for value in reviews["problem_tags"].dropna():
        for tag in str(value).split(","):
            tag = tag.strip()
            if tag:
                counter[tag] += 1
    return pd.DataFrame(
        [{"problem_tag": tag, "count": count} for tag, count in counter.most_common()]
    )
