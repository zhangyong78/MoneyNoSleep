from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from mns.data.providers.base import DataProvider
from mns.data.timeframes import normalize_timeframe


DAILY_FIELDS = ",".join(
    [
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "adjustflag",
        "turn",
        "tradestatus",
        "pctChg",
        "isST",
    ]
)

MINUTE_FIELDS = ",".join(
    [
        "date",
        "time",
        "code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adjustflag",
    ]
)

FREQUENCY_MAP = {
    "1d": "d",
    "d": "d",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "60m": "60",
    "1h": "60",
}


class BaoStockProvider(DataProvider):
    """BaoStock public market-data provider.

    BaoStock uses codes like ``sh.600000`` while this project stores codes as
    ``600000.SH``. Conversion is handled at the provider boundary.
    """

    name = "baostock"

    def __init__(
        self,
        *,
        adjustflag: str = "2",
        user_id: str | None = None,
        password: str | None = None,
        bs_module: Any | None = None,
    ) -> None:
        self.adjustflag = adjustflag
        self.user_id = self._normalize_credential(user_id)
        self.password = self._normalize_credential(password)
        self._bs = bs_module
        self._logged_in = False

    @staticmethod
    def _normalize_credential(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def to_baostock_code(stock_code: str) -> str:
        code = stock_code.strip()
        if "." not in code:
            raise ValueError(f"stock code must include exchange suffix: {stock_code}")
        symbol, exchange = code.split(".", 1)
        return f"{exchange.lower()}.{symbol}"

    @staticmethod
    def from_baostock_code(stock_code: str) -> str:
        code = stock_code.strip()
        if "." not in code:
            return code
        exchange, symbol = code.split(".", 1)
        return f"{symbol}.{exchange.upper()}"

    def _module(self):
        if self._bs is not None:
            return self._bs
        try:
            import baostock as bs
        except ModuleNotFoundError as exc:
            raise RuntimeError("baostock is required. Run `pip install -e .`.") from exc
        self._bs = bs
        return self._bs

    def login(self) -> None:
        if self._logged_in:
            return
        bs = self._module()
        if self.user_id is None and self.password is None:
            result = bs.login()
        else:
            result = bs.login(
                user_id=self.user_id if self.user_id is not None else "anonymous",
                password=self.password if self.password is not None else "123456",
            )
        if getattr(result, "error_code", "0") != "0":
            raise RuntimeError(f"BaoStock login failed: {getattr(result, 'error_msg', '')}")
        self._logged_in = True

    def logout(self) -> None:
        if self._logged_in:
            self._module().logout()
            self._logged_in = False

    def get_stock_list(self) -> pd.DataFrame:
        self.login()
        query_dates = [None]
        today = pd.Timestamp.today().date()
        for offset in range(0, 10):
            candidate = today - timedelta(days=offset)
            if candidate not in query_dates:
                query_dates.append(candidate)

        last_df = pd.DataFrame()
        for candidate in query_dates:
            if candidate is None:
                rs = self._module().query_all_stock()
            else:
                rs = self._module().query_all_stock(candidate.isoformat())
            self._raise_on_error(rs, "query_all_stock")
            df = self._result_to_frame(rs)
            if not df.empty:
                if "code" in df.columns:
                    df["stock_code"] = df["code"].map(self.from_baostock_code)
                return df
            last_df = df
        if "code" in last_df.columns:
            last_df["stock_code"] = last_df["code"].map(self.from_baostock_code)
        return last_df

    def get_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        self.login()
        rs = self._module().query_trade_dates(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        self._raise_on_error(rs, "query_trade_dates")
        df = self._result_to_frame(rs)
        if "calendar_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["calendar_date"])
        if "is_trading_day" in df.columns:
            df["is_open"] = df["is_trading_day"].astype(str) == "1"
        return df

    def get_kline(
        self,
        stock_code: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str,
    ) -> pd.DataFrame:
        self.login()
        frequency = FREQUENCY_MAP.get(timeframe)
        if frequency is None:
            raise ValueError(f"Unsupported BaoStock timeframe: {timeframe}")

        fields = DAILY_FIELDS if frequency == "d" else MINUTE_FIELDS
        rs = self._module().query_history_k_data_plus(
            self.to_baostock_code(stock_code),
            fields,
            start_date=start_time.date().isoformat(),
            end_date=end_time.date().isoformat(),
            frequency=frequency,
            adjustflag=self.adjustflag,
        )
        self._raise_on_error(rs, "query_history_k_data_plus")
        df = self._result_to_frame(rs)
        if df.empty:
            return df
        return self._normalize_baostock_kline(df, timeframe=timeframe)

    def _normalize_baostock_kline(self, df: pd.DataFrame, *, timeframe: str) -> pd.DataFrame:
        normalized = pd.DataFrame()
        normalized["stock_code"] = df["code"].map(self.from_baostock_code)
        normalized["stock_name"] = None
        normalized["exchange"] = normalized["stock_code"].str.split(".").str[-1]

        if "time" in df.columns and df["time"].notna().any():
            time_text = df["time"].astype(str).str.slice(0, 14)
            normalized["bar_time"] = pd.to_datetime(time_text, format="%Y%m%d%H%M%S", errors="coerce")
            normalized["bar_time"] = normalized["bar_time"].fillna(pd.to_datetime(df["date"]))
        else:
            normalized["bar_time"] = pd.to_datetime(df["date"])
        normalized["trade_date"] = pd.to_datetime(df["date"]).dt.date
        normalized["timeframe"] = normalize_timeframe(timeframe)

        normalized["open"] = df["open"]
        normalized["high"] = df["high"]
        normalized["low"] = df["low"]
        normalized["close"] = df["close"]
        normalized["volume"] = df["volume"]
        normalized["amount"] = df["amount"]
        normalized["turnover"] = df["turn"] if "turn" in df.columns else None
        normalized["pre_close"] = df["preclose"] if "preclose" in df.columns else None
        normalized["adj_factor"] = None
        normalized["limit_up_price"] = None
        normalized["limit_down_price"] = None
        normalized["is_suspended"] = df["tradestatus"].astype(str) != "1" if "tradestatus" in df.columns else False
        return normalized

    @staticmethod
    def _result_to_frame(result: Any) -> pd.DataFrame:
        rows: list[list[str]] = []
        while (getattr(result, "error_code", "0") == "0") and result.next():
            rows.append(result.get_row_data())
        return pd.DataFrame(rows, columns=result.fields)

    @staticmethod
    def _raise_on_error(result: Any, operation: str) -> None:
        if getattr(result, "error_code", "0") != "0":
            raise RuntimeError(f"BaoStock {operation} failed: {getattr(result, 'error_msg', '')}")
