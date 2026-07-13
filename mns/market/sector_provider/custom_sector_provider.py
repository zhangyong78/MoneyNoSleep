from __future__ import annotations

from pathlib import Path

import pandas as pd

from mns.market.sector_provider.base import SectorProvider


class CustomSectorProvider(SectorProvider):
    """CSV/dataframe-backed custom sector provider."""

    name = "custom"

    def __init__(
        self,
        *,
        sectors: pd.DataFrame | None = None,
        sector_map: pd.DataFrame | None = None,
        sectors_path: str | Path | None = None,
        sector_map_path: str | Path | None = None,
    ) -> None:
        self._sectors = sectors
        self._sector_map = sector_map
        self._sectors_path = Path(sectors_path) if sectors_path else None
        self._sector_map_path = Path(sector_map_path) if sector_map_path else None

    def get_sector_list(self, sector_types: list[str] | None = None) -> pd.DataFrame:
        frame = self._load_frame(self._sectors, self._sectors_path)
        if frame.empty:
            return frame
        if sector_types and "sector_type" in frame.columns:
            frame = frame.loc[frame["sector_type"].isin(set(sector_types))].reset_index(drop=True)
        return frame

    def get_sector_stocks(
        self,
        *,
        sector_name: str,
        sector_type: str | None = None,
        source_sector_code: str | None = None,
    ) -> pd.DataFrame:
        frame = self._load_frame(self._sector_map, self._sector_map_path)
        if frame.empty:
            return frame
        mask = frame["sector_name"] == sector_name
        if sector_type and "sector_type" in frame.columns:
            mask &= frame["sector_type"] == sector_type
        return frame.loc[mask].reset_index(drop=True)

    @staticmethod
    def _load_frame(frame: pd.DataFrame | None, path: Path | None) -> pd.DataFrame:
        if frame is not None:
            return frame.copy()
        if path is not None and path.exists():
            return pd.read_csv(path)
        return pd.DataFrame()
