from __future__ import annotations

import pandas as pd

from mns.data.intraday_resample import can_resample_timeframe, resample_kline_frame


def _sample_5m_frame() -> pd.DataFrame:
    rows = [
        {
            "stock_code": "600000.SH",
            "stock_name": "浦发银行",
            "exchange": "SH",
            "trade_date": pd.Timestamp("2026-06-22").date(),
            "bar_time": pd.Timestamp("2026-06-22 09:35:00"),
            "timeframe": "5m",
            "open": 10.0,
            "high": 10.2,
            "low": 9.9,
            "close": 10.1,
            "volume": 100,
            "amount": 1000,
            "turnover": 0.1,
            "is_suspended": False,
            "source": "baostock",
        },
        {
            "stock_code": "600000.SH",
            "stock_name": "浦发银行",
            "exchange": "SH",
            "trade_date": pd.Timestamp("2026-06-22").date(),
            "bar_time": pd.Timestamp("2026-06-22 09:40:00"),
            "timeframe": "5m",
            "open": 10.1,
            "high": 10.3,
            "low": 10.0,
            "close": 10.2,
            "volume": 120,
            "amount": 1200,
            "turnover": 0.2,
            "is_suspended": False,
            "source": "baostock",
        },
        {
            "stock_code": "600000.SH",
            "stock_name": "浦发银行",
            "exchange": "SH",
            "trade_date": pd.Timestamp("2026-06-22").date(),
            "bar_time": pd.Timestamp("2026-06-22 09:45:00"),
            "timeframe": "5m",
            "open": 10.2,
            "high": 10.4,
            "low": 10.1,
            "close": 10.3,
            "volume": 140,
            "amount": 1400,
            "turnover": 0.3,
            "is_suspended": False,
            "source": "baostock",
        },
        {
            "stock_code": "600000.SH",
            "stock_name": "浦发银行",
            "exchange": "SH",
            "trade_date": pd.Timestamp("2026-06-22").date(),
            "bar_time": pd.Timestamp("2026-06-22 10:25:00"),
            "timeframe": "5m",
            "open": 10.8,
            "high": 11.0,
            "low": 10.7,
            "close": 10.9,
            "volume": 180,
            "amount": 1800,
            "turnover": 0.4,
            "is_suspended": False,
            "source": "baostock",
        },
        {
            "stock_code": "600000.SH",
            "stock_name": "浦发银行",
            "exchange": "SH",
            "trade_date": pd.Timestamp("2026-06-22").date(),
            "bar_time": pd.Timestamp("2026-06-22 10:30:00"),
            "timeframe": "5m",
            "open": 10.9,
            "high": 11.1,
            "low": 10.8,
            "close": 11.0,
            "volume": 200,
            "amount": 2000,
            "turnover": 0.5,
            "is_suspended": False,
            "source": "baostock",
        },
        {
            "stock_code": "600000.SH",
            "stock_name": "浦发银行",
            "exchange": "SH",
            "trade_date": pd.Timestamp("2026-06-22").date(),
            "bar_time": pd.Timestamp("2026-06-22 13:05:00"),
            "timeframe": "5m",
            "open": 11.1,
            "high": 11.3,
            "low": 11.0,
            "close": 11.2,
            "volume": 220,
            "amount": 2200,
            "turnover": 0.6,
            "is_suspended": False,
            "source": "baostock",
        },
    ]
    return pd.DataFrame(rows)


def test_can_resample_timeframe_supports_expected_pairs():
    assert can_resample_timeframe("5m", "15m")
    assert can_resample_timeframe("5m", "1h")
    assert can_resample_timeframe("15m", "1d")
    assert not can_resample_timeframe("15m", "5m")
    assert not can_resample_timeframe("1d", "15m")


def test_resample_kline_frame_aggregates_5m_to_15m():
    frame = _sample_5m_frame()

    result = resample_kline_frame(frame, source_timeframe="5m", target_timeframe="15m")

    assert result["timeframe"].unique().tolist() == ["15m"]
    assert result["bar_time"].dt.strftime("%H:%M:%S").tolist() == ["09:45:00", "10:30:00", "13:15:00"]
    first_bar = result.iloc[0]
    assert first_bar["open"] == 10.0
    assert first_bar["high"] == 10.4
    assert first_bar["low"] == 9.9
    assert first_bar["close"] == 10.3
    assert first_bar["volume"] == 360
    assert first_bar["amount"] == 3600
    assert first_bar["source"] == "baostock_resampled_from_5m"


def test_resample_kline_frame_aggregates_5m_to_1h_with_china_sessions():
    frame = _sample_5m_frame()

    result = resample_kline_frame(frame, source_timeframe="5m", target_timeframe="1h")

    assert result["bar_time"].dt.strftime("%H:%M:%S").tolist() == ["10:30:00", "14:00:00"]
    assert result.iloc[0]["open"] == 10.0
    assert result.iloc[0]["close"] == 11.0
    assert result.iloc[1]["bar_time"].strftime("%H:%M:%S") == "14:00:00"


def test_resample_kline_frame_aggregates_intraday_to_daily():
    frame = _sample_5m_frame()

    result = resample_kline_frame(frame, source_timeframe="5m", target_timeframe="1d")

    assert len(result) == 1
    assert result.iloc[0]["bar_time"] == pd.Timestamp("2026-06-22")
    assert result.iloc[0]["open"] == 10.0
    assert result.iloc[0]["close"] == 11.2
    assert result.iloc[0]["high"] == 11.3
    assert result.iloc[0]["low"] == 9.9
