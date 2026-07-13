from __future__ import annotations

import pandas as pd

from mns.market.sector_provider.base import SectorProvider


class PyWenCaiSectorProvider(SectorProvider):
    """Reserved provider slot for theme and hot-topic supplementation."""

    name = "pywencai"

    def get_sector_list(self, sector_types: list[str] | None = None) -> pd.DataFrame:
        return pd.DataFrame()

    def get_sector_stocks(
        self,
        *,
        sector_name: str,
        sector_type: str | None = None,
        source_sector_code: str | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame()
