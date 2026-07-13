from __future__ import annotations

from datetime import datetime

import pandas as pd

from mns.data.providers.akshare_provider import AKShareProvider


class _FakeAKShareModule:
    def __init__(self):
        self.last_call = None
        self.last_fetcher = None

    def stock_zh_a_hist(self, symbol, period, start_date, end_date, adjust):
        self.last_fetcher = "stock_zh_a_hist"
        self.last_call = {
            "symbol": symbol,
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust,
        }
        return pd.DataFrame(
            [
                {
                    "日期": "2026-01-05",
                    "开盘": 10.0,
                    "收盘": 10.4,
                    "最高": 10.5,
                    "最低": 9.9,
                    "成交量": 100000,
                    "成交额": 1040000,
                    "换手率": 1.2,
                }
            ]
        )

    def stock_zh_a_hist_min_em(self, symbol, start_date, end_date, period, adjust):
        self.last_fetcher = "stock_zh_a_hist_min_em"
        self.last_call = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "period": period,
            "adjust": adjust,
        }
        return pd.DataFrame(
            [
                {
                    "时间": "2026-06-24 09:45:00",
                    "开盘": 12.0,
                    "收盘": 12.3,
                    "最高": 12.4,
                    "最低": 11.9,
                    "成交量": 20000,
                    "成交额": 245000,
                    "换手率": 0.8,
                }
            ]
        )

    def fund_etf_hist_min_em(self, symbol, start_date, end_date, period, adjust):
        self.last_fetcher = "fund_etf_hist_min_em"
        self.last_call = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "period": period,
            "adjust": adjust,
        }
        return pd.DataFrame(
            [
                {
                    "时间": "2026-06-24 10:00:00",
                    "开盘": 1.0,
                    "收盘": 1.02,
                    "最高": 1.03,
                    "最低": 0.99,
                    "成交量": 500000,
                    "成交额": 510000,
                    "换手率": 2.5,
                }
            ]
        )

    def stock_zh_a_minute(self, symbol, period, adjust):
        self.last_fetcher = "stock_zh_a_minute"
        self.last_call = {
            "symbol": symbol,
            "period": period,
            "adjust": adjust,
        }
        return pd.DataFrame(
            [
                {
                    "day": "2026-06-24 09:45:00",
                    "open": 2.01,
                    "high": 2.03,
                    "low": 2.00,
                    "close": 2.02,
                    "volume": 880000,
                    "amount": 1770000,
                }
            ]
        )


def test_akshare_provider_normalizes_daily_kline():
    fake_ak = _FakeAKShareModule()
    provider = AKShareProvider(ak_module=fake_ak)

    df = provider.get_kline(
        "600000.SH",
        datetime(2026, 1, 1),
        datetime(2026, 1, 31),
        "1d",
    )

    assert fake_ak.last_fetcher == "stock_zh_a_hist"
    assert fake_ak.last_call == {
        "symbol": "600000",
        "period": "daily",
        "start_date": "20260101",
        "end_date": "20260131",
        "adjust": "qfq",
    }
    assert df.loc[0, "stock_code"] == "600000.SH"
    assert df.loc[0, "close"] == 10.4
    assert df.loc[0, "turnover"] == 1.2


def test_akshare_provider_uses_stock_minute_api_for_a_share():
    fake_ak = _FakeAKShareModule()
    provider = AKShareProvider(ak_module=fake_ak)

    df = provider.get_kline(
        "600000",
        datetime(2026, 6, 24, 9, 30),
        datetime(2026, 6, 24, 15, 0),
        "15m",
    )

    assert fake_ak.last_fetcher == "stock_zh_a_hist_min_em"
    assert fake_ak.last_call == {
        "symbol": "600000",
        "start_date": "2026-06-24 09:30:00",
        "end_date": "2026-06-24 15:00:00",
        "period": "15",
        "adjust": "qfq",
    }
    assert df.loc[0, "stock_code"] == "600000.SH"
    assert str(df.loc[0, "bar_time"]) == "2026-06-24 09:45:00"
    assert df.loc[0, "timeframe"] == "15m"


def test_akshare_provider_uses_etf_minute_api_for_etf():
    fake_ak = _FakeAKShareModule()
    provider = AKShareProvider(ak_module=fake_ak)

    df = provider.get_kline(
        "588000",
        datetime(2026, 6, 24, 9, 30),
        datetime(2026, 6, 24, 15, 0),
        "1h",
    )

    assert fake_ak.last_fetcher == "fund_etf_hist_min_em"
    assert fake_ak.last_call == {
        "symbol": "588000",
        "start_date": "2026-06-24 09:30:00",
        "end_date": "2026-06-24 15:00:00",
        "period": "60",
        "adjust": "qfq",
    }
    assert df.loc[0, "stock_code"] == "588000.SH"
    assert df.loc[0, "timeframe"] == "1h"
    assert df.loc[0, "turnover"] == 2.5


def test_akshare_provider_falls_back_to_sina_minute_api_when_eastmoney_fails():
    class _FallbackAKShareModule(_FakeAKShareModule):
        def stock_zh_a_hist_min_em(self, symbol, start_date, end_date, period, adjust):
            raise RuntimeError("eastmoney ssl failed")

    fake_ak = _FallbackAKShareModule()
    provider = AKShareProvider(ak_module=fake_ak)

    df = provider.get_kline(
        "600000.SH",
        datetime(2026, 6, 24, 9, 30),
        datetime(2026, 6, 24, 15, 0),
        "15m",
    )

    assert fake_ak.last_fetcher == "stock_zh_a_minute"
    assert fake_ak.last_call == {
        "symbol": "sh600000",
        "period": "15",
        "adjust": "qfq",
    }
    assert df.loc[0, "stock_code"] == "600000.SH"
    assert df.loc[0, "close"] == 2.02
