from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from mns.data.providers.qmt_provider import QMTProvider


class _FakeClient:
    def __init__(self) -> None:
        self.instrument_calls: list[str] = []

    def is_connected(self) -> bool:
        return True

    def get_app_dir(self) -> str:
        return "D:/fake_qmt/bin.x64"

    def get_data_dir(self) -> str:
        return "D:/fake_qmt/userdata/datadir"

    def get_peer_addr(self) -> str:
        return "127.0.0.1:58610"

    def get_server_tag(self) -> bytes:
        return b"server-tag"

    def get_instrument_detail(self, stock_code: str) -> bytes:
        self.instrument_calls.append(stock_code)
        return b"detail-bytes"


class _FakeXTDataModule:
    def __init__(self) -> None:
        self.enable_hello = True
        self.client = _FakeClient()
        self.connect_calls: list[dict] = []
        self.download_calls: list[dict] = []
        self.local_data_calls: list[dict] = []
        self.trade_calendar_calls: list[dict] = []

    def connect(self, ip="", port=None, remember_if_success=True):
        self.connect_calls.append(
            {
                "ip": ip,
                "port": port,
                "remember_if_success": remember_if_success,
            }
        )
        return self.client

    def get_client(self):
        return self.client

    def download_history_data(self, stock_code, period, start_time="", end_time="", incrementally=None):
        self.download_calls.append(
            {
                "stock_code": stock_code,
                "period": period,
                "start_time": start_time,
                "end_time": end_time,
                "incrementally": incrementally,
            }
        )

    def get_local_data(
        self,
        field_list=None,
        stock_list=None,
        period="1d",
        start_time="",
        end_time="",
        count=-1,
        dividend_type="none",
        fill_data=True,
        data_dir=None,
    ):
        self.local_data_calls.append(
            {
                "field_list": field_list,
                "stock_list": stock_list,
                "period": period,
                "start_time": start_time,
                "end_time": end_time,
                "dividend_type": dividend_type,
                "fill_data": fill_data,
                "data_dir": data_dir,
            }
        )
        return {
            stock_list[0]: pd.DataFrame(
                [
                    {
                        "time": 1767542400000,
                        "open": 12.47,
                        "high": 12.48,
                        "low": 11.80,
                        "close": 11.82,
                        "volume": 1222843,
                        "amount": 1459886000.0,
                    }
                ],
                index=["20260105"],
            )
        }

    def get_trading_dates(self, market, start_time="", end_time="", count=-1):
        self.trade_calendar_calls.append(
            {
                "market": market,
                "start_time": start_time,
                "end_time": end_time,
                "count": count,
            }
        )
        if market == "SH":
            return [1767542400000, 1767628800000]
        return [1767542400000]

    def get_stock_list_in_sector(self, sector_name, real_timetag=-1):
        if sector_name == "沪深A股":
            return ["600000.SH", "000001.SZ"]
        return []

    def get_stock_list_in_sector(self, sector_name, real_timetag=-1):
        if sector_name in {"\u6caa\u6df1A\u80a1", "\u6caa\u6df1\u4eacA\u80a1"}:
            return ["600000.SH", "000001.SZ"]
        if sector_name == "\u6caa\u6df1ETF":
            return ["510300.SH"]
        return []


class _FakeBSONDoc:
    def __init__(self, raw):
        self.raw = raw

    def decode(self):
        if self.raw == b"server-tag":
            return {"tag": "sp3", "version": "1.0"}
        return {"InstrumentName": "浦发银行"}


class _FakeBSONModule:
    BSON = _FakeBSONDoc


def test_qmt_provider_connection_info_and_kline():
    fake_xtdata = _FakeXTDataModule()
    provider = QMTProvider(
        dividend_type="qfq",
        xtdata_module=fake_xtdata,
        xtbson_module=_FakeBSONModule(),
    )

    info = provider.connection_info()
    df = provider.get_kline(
        "600000.SH",
        datetime(2026, 1, 1),
        datetime(2026, 1, 31),
        "1d",
    )

    assert info["connected"] is True
    assert info["app_dir"] == "D:/fake_qmt/bin.x64"
    assert info["server_tag"] == {"tag": "sp3", "version": "1.0"}
    assert fake_xtdata.connect_calls[0]["remember_if_success"] is True
    assert fake_xtdata.download_calls[0]["stock_code"] == "600000.SH"
    assert fake_xtdata.download_calls[0]["period"] == "1d"
    assert fake_xtdata.local_data_calls[0]["dividend_type"] == "front"
    assert df.loc[0, "stock_code"] == "600000.SH"
    assert df.loc[0, "stock_name"] == "浦发银行"
    assert df.loc[0, "bar_time"].strftime("%Y-%m-%d") == "2026-01-05"
    assert df.loc[0, "close"] == 11.82


def test_qmt_provider_trade_calendar_and_stock_list():
    fake_xtdata = _FakeXTDataModule()
    provider = QMTProvider(
        xtdata_module=fake_xtdata,
        xtbson_module=_FakeBSONModule(),
        auto_download=False,
    )

    calendar = provider.get_trade_calendar(date(2026, 1, 1), date(2026, 1, 31))
    stocks = provider.get_stock_list()

    assert fake_xtdata.trade_calendar_calls[0]["market"] == "SH"
    assert fake_xtdata.trade_calendar_calls[1]["market"] == "SZ"
    assert calendar["trade_date"].astype(str).tolist() == ["2026-01-05", "2026-01-06"]
    assert stocks["stock_code"].tolist() == ["000001.SZ", "600000.SH"]


def test_qmt_provider_stock_list_can_include_etf():
    fake_xtdata = _FakeXTDataModule()
    provider = QMTProvider(
        xtdata_module=fake_xtdata,
        xtbson_module=_FakeBSONModule(),
        auto_download=False,
    )

    stocks = provider.get_stock_list(include_etf=True)

    assert "510300.SH" in stocks["stock_code"].tolist()
