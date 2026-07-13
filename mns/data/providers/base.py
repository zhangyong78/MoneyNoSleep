from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Iterable

import pandas as pd


class DataProvider(ABC):
    """Unified external data source interface.

    Strategies must not use providers directly. Provider output should be
    normalized and persisted locally before strategy or backtest access.
    """

    name: str = "base"

    @abstractmethod
    def get_stock_list(self) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def get_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def get_kline(
        self,
        stock_code: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str,
    ) -> pd.DataFrame:
        raise NotImplementedError

    def get_index_kline(
        self,
        index_code: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str,
    ) -> pd.DataFrame:
        return self.get_kline(index_code, start_time, end_time, timeframe)

    def get_sector_info(self) -> pd.DataFrame:
        return pd.DataFrame()

    def get_financial_data(self, stock_code: str) -> pd.DataFrame:
        return pd.DataFrame()

    def iter_klines(
        self,
        stock_codes: Iterable[str],
        start_time: datetime,
        end_time: datetime,
        timeframe: str,
    ) -> Iterable[pd.DataFrame]:
        for stock_code in stock_codes:
            yield self.get_kline(stock_code, start_time, end_time, timeframe)
