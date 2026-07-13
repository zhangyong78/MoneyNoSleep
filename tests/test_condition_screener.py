import pandas as pd

from mns.selector.condition_screener import ConditionScreener, close_above, greater_than


def test_condition_screener_returns_candidates_with_reasons():
    df = pd.DataFrame(
        [
            {"stock_code": "A", "close": 12, "ma55": 10, "volume_ratio_5": 2.0},
            {"stock_code": "B", "close": 9, "ma55": 10, "volume_ratio_5": 3.0},
        ]
    )
    screener = ConditionScreener(
        [
            close_above("close", "ma55"),
            greater_than("volume_ratio_5", 1.5),
        ]
    )

    result = screener.screen(df)

    assert result["stock_code"].tolist() == ["A"]
    assert result.iloc[0]["score"] == 2
    assert "close>ma55" in result.iloc[0]["candidate_reason"]
