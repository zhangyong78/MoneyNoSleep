from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from mns.data.providers.base import DataProvider
from mns.data.timeframes import normalize_timeframe


PERIOD_MAP = {
    "1d": "daily",
    "d": "daily",
    "daily": "daily",
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "60m": "60",
    "1h": "60",
}

DATE_COLUMN = "\u65e5\u671f"
TIME_COLUMN = "\u65f6\u95f4"
OPEN_COLUMN = "\u5f00\u76d8"
HIGH_COLUMN = "\u6700\u9ad8"
LOW_COLUMN = "\u6700\u4f4e"
CLOSE_COLUMN = "\u6536\u76d8"
VOLUME_COLUMN = "\u6210\u4ea4\u91cf"
AMOUNT_COLUMN = "\u6210\u4ea4\u989d"
TURNOVER_COLUMN = "\u6362\u624b\u7387"


class AKShareProvider(DataProvider):
    """AKShare public market-data provider for daily and intraday K-line."""

    name = "akshare"

    def __init__(self, *, adjust: str = "qfq", ak_module: Any | None = None) -> None:
        self.adjust = adjust
        self._ak = ak_module

    @staticmethod
    def normalize_stock_code(stock_code: str) -> str:
        code = str(stock_code).strip()
        if not code:
            raise ValueError("stock code cannot be empty")

        uppered = code.upper()
        if uppered.endswith((".SH", ".SZ", ".BJ")) and "." in uppered:
            return uppered

        lowered = code.lower()
        if lowered.startswith(("sh.", "sz.", "bj.")) and len(lowered) >= 9:
            return f"{lowered[3:9]}.{lowered[:2].upper()}"

        digits = "".join(ch for ch in code if ch.isdigit())
        if len(digits) != 6:
            return uppered
        return AKShareProvider._with_exchange_guess(digits)

    @classmethod
    def to_akshare_symbol(cls, stock_code: str) -> str:
        return cls.normalize_stock_code(stock_code).split(".", 1)[0].strip()

    def _module(self):
        if self._ak is not None:
            return self._ak
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise RuntimeError("akshare is required. Run `pip install -e .`.") from exc
        self._ak = ak
        return self._ak

    def get_stock_list(self) -> pd.DataFrame:
        ak = self._module()
        if not hasattr(ak, "stock_info_a_code_name"):
            return pd.DataFrame()
        df = ak.stock_info_a_code_name()
        if "code" in df.columns:
            df["stock_code"] = df["code"].map(self._with_exchange_guess)
        return df

    def get_trade_calendar(self, start_date, end_date) -> pd.DataFrame:
        return pd.DataFrame({"trade_date": pd.date_range(start_date, end_date, freq="B"), "is_open": True})

    def get_kline(
        self,
        stock_code: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str,
    ) -> pd.DataFrame:
        timeframe = normalize_timeframe(timeframe)
        normalized_stock_code = self.normalize_stock_code(stock_code)
        period = PERIOD_MAP.get(timeframe)
        if period is None:
            raise ValueError(f"Unsupported AKShare timeframe: {timeframe}")

        if period == "daily":
            raw = self._module().stock_zh_a_hist(
                symbol=self.to_akshare_symbol(normalized_stock_code),
                period=period,
                start_date=start_time.strftime("%Y%m%d"),
                end_date=end_time.strftime("%Y%m%d"),
                adjust=self.adjust,
            )
        else:
            raw = self._get_intraday_kline(
                stock_code=normalized_stock_code,
                start_time=start_time,
                end_time=end_time,
                period=period,
            )
        if raw.empty:
            return pd.DataFrame()
        return self._normalize(raw, stock_code=normalized_stock_code, timeframe=timeframe)

    def _get_intraday_kline(
        self,
        *,
        stock_code: str,
        start_time: datetime,
        end_time: datetime,
        period: str,
    ) -> pd.DataFrame:
        ak = self._module()
        symbol = self.to_akshare_symbol(stock_code)
        fetcher_name = "fund_etf_hist_min_em" if self._uses_etf_endpoint(stock_code) else "stock_zh_a_hist_min_em"
        fetcher = getattr(ak, fetcher_name)
        try:
            raw = fetcher(
                symbol=symbol,
                start_date=start_time.strftime("%Y-%m-%d %H:%M:%S"),
                end_date=end_time.strftime("%Y-%m-%d %H:%M:%S"),
                period=period,
                adjust=self.adjust,
            )
            if not raw.empty:
                return raw
        except Exception:
            pass

        if hasattr(ak, "stock_zh_a_minute"):
            return self._get_sina_intraday_kline(
                stock_code=stock_code,
                start_time=start_time,
                end_time=end_time,
                period=period,
            )
        return pd.DataFrame()

    def _get_sina_intraday_kline(
        self,
        *,
        stock_code: str,
        start_time: datetime,
        end_time: datetime,
        period: str,
    ) -> pd.DataFrame:
        raw = self._module().stock_zh_a_minute(
            symbol=self._to_sina_symbol(stock_code),
            period=period,
            adjust=self.adjust,
        )
        if raw.empty:
            return raw

        prepared = raw.rename(
            columns={
                "day": TIME_COLUMN,
                "open": OPEN_COLUMN,
                "high": HIGH_COLUMN,
                "low": LOW_COLUMN,
                "close": CLOSE_COLUMN,
                "volume": VOLUME_COLUMN,
                "amount": AMOUNT_COLUMN,
            }
        ).copy()
        prepared[TIME_COLUMN] = pd.to_datetime(prepared[TIME_COLUMN], errors="coerce")
        prepared = prepared.loc[
            (prepared[TIME_COLUMN] >= pd.Timestamp(start_time))
            & (prepared[TIME_COLUMN] <= pd.Timestamp(end_time))
        ].reset_index(drop=True)
        return prepared

    def _normalize(self, df: pd.DataFrame, *, stock_code: str, timeframe: str) -> pd.DataFrame:
        normalized = pd.DataFrame(index=df.index)
        bar_time = pd.to_datetime(self._pick_column(df, [TIME_COLUMN, DATE_COLUMN]), errors="coerce")
        trade_date = pd.to_datetime(self._pick_column(df, [DATE_COLUMN]), errors="coerce")
        if trade_date.isna().all():
            trade_date = bar_time

        normalized["stock_code"] = stock_code
        normalized["stock_name"] = None
        normalized["exchange"] = stock_code.split(".")[-1] if "." in stock_code else None
        normalized["trade_date"] = trade_date.dt.date
        normalized["bar_time"] = bar_time
        normalized["timeframe"] = normalize_timeframe(timeframe)
        normalized["open"] = self._pick_column(df, [OPEN_COLUMN])
        normalized["high"] = self._pick_column(df, [HIGH_COLUMN])
        normalized["low"] = self._pick_column(df, [LOW_COLUMN])
        normalized["close"] = self._pick_column(df, [CLOSE_COLUMN])
        normalized["volume"] = self._pick_column(df, [VOLUME_COLUMN])
        normalized["amount"] = self._pick_column(df, [AMOUNT_COLUMN])
        normalized["turnover"] = self._pick_column(df, [TURNOVER_COLUMN])
        normalized["pre_close"] = None
        normalized["adj_factor"] = None
        normalized["limit_up_price"] = None
        normalized["limit_down_price"] = None
        normalized["is_suspended"] = False
        return normalized

    @staticmethod
    def _pick_column(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
        for column in candidates:
            if column in df.columns:
                return df[column]
        return pd.Series([None] * len(df), index=df.index)

    @staticmethod
    def _uses_etf_endpoint(stock_code: str) -> bool:
        symbol = AKShareProvider.to_akshare_symbol(stock_code)
        return symbol.startswith(("1", "5"))

    @staticmethod
    def _to_sina_symbol(stock_code: str) -> str:
        normalized = AKShareProvider.normalize_stock_code(stock_code)
        symbol, exchange = normalized.split(".", 1)
        return f"{exchange.lower()}{symbol}"

    @staticmethod
    def _with_exchange_guess(symbol: str) -> str:
        symbol = str(symbol).zfill(6)
        if symbol.startswith(("5", "6", "9")):
            return f"{symbol}.SH"
        if symbol.startswith(("4", "8")):
            return f"{symbol}.BJ"
        return f"{symbol}.SZ"
