from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class SectorProvider(ABC):
    """Unified sector-data provider interface."""

    name: str = "base"

    @abstractmethod
    def get_sector_list(self, sector_types: list[str] | None = None) -> pd.DataFrame:
        """Return raw sector rows for the requested types."""
        raise NotImplementedError

    @abstractmethod
    def get_sector_stocks(
        self,
        *,
        sector_name: str,
        sector_type: str | None = None,
        source_sector_code: str | None = None,
    ) -> pd.DataFrame:
        """Return raw constituent rows for a sector."""
        raise NotImplementedError

    def get_stock_sectors(self, stock_code: str) -> pd.DataFrame:
        """Optional provider-side reverse lookup."""
        return pd.DataFrame()

    def get_sector_daily(self, trade_date: str | None = None, sector_types: list[str] | None = None) -> pd.DataFrame:
        """Optional sector daily snapshot."""
        return pd.DataFrame()
