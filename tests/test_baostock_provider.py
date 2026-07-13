from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from mns.data.providers.baostock_provider import BaoStockProvider


@dataclass
class _FakeLoginResult:
    error_code: str = "0"
    error_msg: str = "success"


class _FakeResultSet:
    def __init__(self, fields: list[str], rows: list[list[str]], *, error_code: str = "0", error_msg: str = "success") -> None:
        self.fields = fields
        self._rows = rows
        self._index = -1
        self.error_code = error_code
        self.error_msg = error_msg

    def next(self) -> bool:
        self._index += 1
        return self._index < len(self._rows)

    def get_row_data(self) -> list[str]:
        return self._rows[self._index]


class _FakeBaoStockModule:
    def __init__(self) -> None:
        self.query_all_stock_calls: list[str | None] = []
        self.login_calls: list[tuple[str | None, str | None]] = []

    def login(self, user_id=None, password=None):
        self.login_calls.append((user_id, password))
        return _FakeLoginResult()

    def logout(self):
        return None

    def query_all_stock(self, day: str | None = None):
        self.query_all_stock_calls.append(day)
        if day in (None, "2026-05-22"):
            return _FakeResultSet(["code", "tradeStatus", "code_name"], [])
        if day == "2026-05-21":
            return _FakeResultSet(
                ["code", "tradeStatus", "code_name"],
                [["sh.600000", "1", "浦发银行"], ["sz.000001", "1", "平安银行"]],
            )
        return _FakeResultSet(["code", "tradeStatus", "code_name"], [])


def test_baostock_provider_get_stock_list_falls_back_to_previous_day(monkeypatch):
    fake_module = _FakeBaoStockModule()
    provider = BaoStockProvider(bs_module=fake_module)
    monkeypatch.setattr(pd.Timestamp, "today", classmethod(lambda cls: pd.Timestamp("2026-05-22 10:00:00")))

    result = provider.get_stock_list()

    assert result["stock_code"].tolist() == ["600000.SH", "000001.SZ"]
    assert fake_module.query_all_stock_calls[:3] == [None, "2026-05-22", "2026-05-21"]


def test_baostock_provider_passes_explicit_credentials_to_login():
    fake_module = _FakeBaoStockModule()
    provider = BaoStockProvider(
        user_id="zhangyong78",
        password="Zy123456@",
        bs_module=fake_module,
    )

    provider.login()

    assert fake_module.login_calls == [("zhangyong78", "Zy123456@")]


def test_baostock_provider_treats_blank_credentials_as_anonymous_login():
    fake_module = _FakeBaoStockModule()
    provider = BaoStockProvider(
        user_id="   ",
        password="",
        bs_module=fake_module,
    )

    provider.login()

    assert fake_module.login_calls == [(None, None)]
