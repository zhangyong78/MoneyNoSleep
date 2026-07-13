from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from mns.data.providers.base import DataProvider
from mns.data.timeframes import normalize_timeframe

CHINA_TZ = "Asia/Shanghai"

PERIOD_MAP = {
    "d": "1d",
    "1d": "1d",
    "daily": "1d",
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "60m",
    "1h": "60m",
}

DIVIDEND_TYPE_MAP = {
    "front": "front",
    "qfq": "front",
    "back": "back",
    "hfq": "back",
    "none": "none",
    "raw": "none",
}

QMT_A_SHARE_SECTORS = [
    "\u6caa\u6df1\u4eacA\u80a1",
    "\u6caa\u6df1A\u80a1",
    "\u4e0a\u8bc1A\u80a1",
    "\u6df1\u8bc1A\u80a1",
    "\u521b\u4e1a\u677f",
]

QMT_ETF_SECTORS = [
    "\u6caa\u6df1ETF",
    "\u4e0a\u8bc1ETF",
    "\u6df1\u8bc1ETF",
]


class QMTProvider(DataProvider):
    """miniQMT market-data provider backed by ``xtquant.xtdata``."""

    name = "qmt"

    def __init__(
        self,
        *,
        dividend_type: str = "front",
        ip: str = "",
        port: int | None = None,
        remember_if_success: bool = True,
        xtdata_module: Any | None = None,
        xtbson_module: Any | None = None,
        auto_download: bool = True,
        fill_data: bool = True,
    ) -> None:
        self.dividend_type = DIVIDEND_TYPE_MAP.get(dividend_type, dividend_type)
        self.ip = ip
        self.port = port
        self.remember_if_success = remember_if_success
        self.auto_download = auto_download
        self.fill_data = fill_data
        self._xtdata = xtdata_module
        self._xtbson = xtbson_module
        self._client = None
        self._instrument_cache: dict[str, str | None] = {}

    def _module(self):
        if self._xtdata is not None:
            return self._xtdata
        try:
            from xtquant import xtdata
        except ModuleNotFoundError as exc:
            raise RuntimeError("xtquant is required. Run `pip install xtquant` or `pip install -e .`.") from exc
        self._xtdata = xtdata
        return self._xtdata

    def _bson_module(self):
        if self._xtbson is not None:
            return self._xtbson
        try:
            from xtquant import xtbson
        except ModuleNotFoundError:
            return None
        self._xtbson = xtbson
        return self._xtbson

    def connect(self):
        module = self._module()
        setattr(module, "enable_hello", False)

        if self._client is not None:
            try:
                if self._client.is_connected():
                    return self._client
            except Exception:
                self._client = None

        client = module.connect(
            ip=self.ip,
            port=self.port,
            remember_if_success=self.remember_if_success,
        )
        if client is None:
            raise RuntimeError("miniQMT connection returned no client.")
        if hasattr(client, "is_connected") and not client.is_connected():
            raise RuntimeError("miniQMT connection failed.")
        self._client = client
        return client

    def connection_info(self) -> dict[str, Any]:
        client = self.connect()
        info: dict[str, Any] = {
            "connected": bool(client.is_connected()) if hasattr(client, "is_connected") else True,
            "app_dir": client.get_app_dir() if hasattr(client, "get_app_dir") else None,
            "data_dir": client.get_data_dir() if hasattr(client, "get_data_dir") else None,
            "peer_addr": client.get_peer_addr() if hasattr(client, "get_peer_addr") else None,
        }
        if hasattr(client, "get_server_tag"):
            try:
                raw_tag = client.get_server_tag()
                bson_module = self._bson_module()
                info["server_tag"] = bson_module.BSON(raw_tag).decode() if bson_module and raw_tag else raw_tag
            except Exception:
                info["server_tag"] = None
        return info

    def get_stock_list(self) -> pd.DataFrame:
        module = self._module()
        self.connect()
        sectors = ["沪深京A股", "沪深A股", "上证A股", "深证A股", "创业板"]
        codes: list[str] = []
        for sector in sectors:
            try:
                codes.extend(module.get_stock_list_in_sector(sector))
            except Exception:
                continue
        unique_codes = sorted({code for code in codes if code})
        return pd.DataFrame({"stock_code": unique_codes})

    def get_stock_list(self, *, include_etf: bool = False) -> pd.DataFrame:
        module = self._module()
        self.connect()
        sectors = list(QMT_A_SHARE_SECTORS)
        if include_etf:
            sectors.extend(QMT_ETF_SECTORS)
        codes: list[str] = []
        for sector in sectors:
            try:
                codes.extend(module.get_stock_list_in_sector(sector))
            except Exception:
                continue
        unique_codes = sorted({code for code in codes if code})
        return pd.DataFrame({"stock_code": unique_codes})

    def get_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        module = self._module()
        self.connect()

        start_text = start_date.strftime("%Y%m%d")
        end_text = end_date.strftime("%Y%m%d")
        timestamps = set()
        for market in ("SH", "SZ"):
            timestamps.update(module.get_trading_dates(market, start_text, end_text))

        trade_days = sorted(self._to_china_datetime(list(timestamps)).date) if timestamps else []
        return pd.DataFrame({"trade_date": trade_days, "is_open": True})

    def get_kline(
        self,
        stock_code: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str,
    ) -> pd.DataFrame:
        module = self._module()
        self.connect()

        period = PERIOD_MAP.get(timeframe)
        if period is None:
            raise ValueError(f"Unsupported miniQMT timeframe: {timeframe}")

        start_text = self._format_api_time(start_time, period=period)
        end_text = self._format_api_time(end_time, period=period)
        if self.auto_download:
            module.download_history_data(stock_code, period, start_text, end_text)

        frame_map = module.get_local_data(
            field_list=["time", "open", "high", "low", "close", "volume", "amount"],
            stock_list=[stock_code],
            period=period,
            start_time=start_text,
            end_time=end_text,
            dividend_type=self.dividend_type,
            fill_data=self.fill_data,
        )
        if not isinstance(frame_map, dict) or stock_code not in frame_map:
            return pd.DataFrame()

        raw = frame_map[stock_code]
        if raw is None or raw.empty:
            return pd.DataFrame()
        return self._normalize_qmt_kline(raw.copy(), stock_code=stock_code, timeframe=timeframe)

    def _normalize_qmt_kline(self, df: pd.DataFrame, *, stock_code: str, timeframe: str) -> pd.DataFrame:
        normalized = pd.DataFrame(index=df.index)
        normalized["stock_code"] = stock_code
        normalized["stock_name"] = self._instrument_name(stock_code)
        normalized["exchange"] = stock_code.split(".")[-1] if "." in stock_code else None
        normalized["bar_time"] = self._to_china_datetime(df["time"])
        if normalized["bar_time"].isna().any():
            fallback = pd.to_datetime(df.index.astype(str), errors="coerce")
            normalized["bar_time"] = normalized["bar_time"].fillna(fallback)
        normalized["trade_date"] = normalized["bar_time"].dt.date
        normalized["timeframe"] = normalize_timeframe(timeframe)
        normalized["open"] = df.get("open")
        normalized["high"] = df.get("high")
        normalized["low"] = df.get("low")
        normalized["close"] = df.get("close")
        normalized["volume"] = df.get("volume")
        normalized["amount"] = df.get("amount")
        normalized["turnover"] = None
        normalized["pre_close"] = None
        normalized["adj_factor"] = None
        normalized["limit_up_price"] = None
        normalized["limit_down_price"] = None
        normalized["is_suspended"] = False
        return normalized.reset_index(drop=True)

    def _instrument_name(self, stock_code: str) -> str | None:
        if stock_code in self._instrument_cache:
            return self._instrument_cache[stock_code]

        name = None
        try:
            client = self.connect()
            raw_detail = client.get_instrument_detail(stock_code)
            bson_module = self._bson_module()
            if bson_module and raw_detail:
                detail = bson_module.BSON(raw_detail).decode()
                name = detail.get("InstrumentName") or detail.get("ExtendName")
        except Exception:
            name = None

        self._instrument_cache[stock_code] = name
        return name

    @staticmethod
    def _format_api_time(value: datetime, *, period: str) -> str:
        if period == "1d":
            return value.strftime("%Y%m%d")
        return value.strftime("%Y%m%d%H%M%S")

    @staticmethod
    def _to_china_datetime(values) -> pd.Series:
        converted = pd.to_datetime(values, unit="ms", errors="coerce", utc=True)
        if isinstance(converted, pd.Series):
            return converted.dt.tz_convert(CHINA_TZ).dt.tz_localize(None)
        return converted.tz_convert(CHINA_TZ).tz_localize(None)
