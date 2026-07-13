import pandas as pd

from mns.data.normalizer import normalize_kline_frame
from mns.data.validator import validate_kline_frame


def test_normalize_and_validate_valid_kline():
    raw = pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "bar_time": "2026-05-19",
                "open": 10,
                "high": 11,
                "low": 9.8,
                "close": 10.5,
                "volume": 1000,
                "amount": 10500,
            }
        ]
    )

    normalized = normalize_kline_frame(raw, source="fixture", timeframe="1d")

    assert list(normalized.columns)[0] == "stock_code"
    assert normalized.loc[0, "timeframe"] == "1d"
    assert validate_kline_frame(normalized) == []


def test_validate_rejects_bad_ohlc():
    df = pd.DataFrame(
        [
            {
                "open": 10,
                "high": 9,
                "low": 11,
                "close": 10.5,
                "volume": -1,
                "amount": 100,
            }
        ]
    )

    issues = validate_kline_frame(df)

    assert len(issues) >= 3
    assert {issue.field for issue in issues} >= {"high", "low", "volume"}
