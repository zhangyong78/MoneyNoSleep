from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from mns.data.providers.base import DataProvider


class CSVPublicProvider(DataProvider):
    """Simple provider for local CSV fixtures and exported public data."""

    name = "csv_public"

    def __init__(self, root: str | Path = "data/raw/public") -> None:
        self.root = Path(root)

    def get_stock_list(self) -> pd.DataFrame:
        path = self.root / "stock_list.csv"
        return pd.read_csv(path) if path.exists() else pd.DataFrame()

    def get_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        path = self.root / "trade_calendar.csv"
        if path.exists():
            return pd.read_csv(path, parse_dates=["trade_date"])
        return pd.DataFrame({"trade_date": pd.date_range(start_date, end_date, freq="B"), "is_open": True})

    def get_kline(
        self,
        stock_code: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str,
    ) -> pd.DataFrame:
        safe_code = stock_code.replace(".", "_")
        path = self.root / "kline" / f"{safe_code}_{timeframe}.csv"
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_csv(path, parse_dates=["bar_time"])
        mask = (df["bar_time"] >= pd.Timestamp(start_time)) & (df["bar_time"] <= pd.Timestamp(end_time))
        return df.loc[mask].copy()
