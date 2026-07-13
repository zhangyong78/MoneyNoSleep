from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from mns.market.sector_provider.base import SectorProvider
from mns.market.sector_provider.sector_normalizer import SectorNormalizer
from mns.market.sector_provider.qmt_sector_snapshot import load_qmt_sector_snapshot


class QMTSectorProvider(SectorProvider):
    """miniQMT-backed sector provider."""

    name = "qmt"

    def __init__(self, *, xtdata_module: Any | None = None, raw_snapshot_path: str | Path | None = None) -> None:
        self._xtdata = xtdata_module
        self._raw_snapshot_path = Path(raw_snapshot_path) if raw_snapshot_path else None
        self._snapshot_sectors: pd.DataFrame | None = None
        self._snapshot_map: pd.DataFrame | None = None
        if self._raw_snapshot_path is not None:
            self._snapshot_sectors, self._snapshot_map = load_qmt_sector_snapshot(self._raw_snapshot_path)

    def _module(self):
        if self._xtdata is not None:
            return self._xtdata
        try:
            from xtquant import xtdata
        except ModuleNotFoundError as exc:
            raise RuntimeError("xtquant is required. Run `pip install xtquant` or `pip install -e .`.") from exc
        self._xtdata = xtdata
        return self._xtdata

    def refresh_sector_cache(self) -> None:
        if self._snapshot_sectors is not None:
            return
        module = self._module()
        if hasattr(module, "download_sector_data"):
            module.download_sector_data()

    def get_sector_list(self, sector_types: list[str] | None = None) -> pd.DataFrame:
        if self._snapshot_sectors is not None:
            frame = self._snapshot_sectors.copy()
            if sector_types and "sector_type" in frame.columns:
                frame = frame.loc[frame["sector_type"].isin(set(sector_types))].reset_index(drop=True)
            return frame
        module = self._module()
        self.refresh_sector_cache()
        if not hasattr(module, "get_sector_list"):
            return pd.DataFrame(columns=["sector_name", "source_sector_code", "sector_type"])
        raw = module.get_sector_list()
        names = raw if isinstance(raw, list) else list(raw or [])
        frame = pd.DataFrame({"sector_name": names})
        frame["source_sector_code"] = frame["sector_name"]
        frame["sector_type"] = frame["sector_name"].map(self._guess_sector_type)
        if sector_types:
            frame = frame.loc[frame["sector_type"].isin(set(sector_types))].reset_index(drop=True)
        return frame

    def get_sector_stocks(
        self,
        *,
        sector_name: str,
        sector_type: str | None = None,
        source_sector_code: str | None = None,
    ) -> pd.DataFrame:
        if self._snapshot_map is not None:
            frame = self._snapshot_map.copy()
            mask = pd.Series(True, index=frame.index)
            if "sector_name" in frame.columns:
                mask &= frame["sector_name"].astype(str) == str(sector_name)
            if sector_type and "sector_type" in frame.columns:
                mask &= frame["sector_type"].astype(str) == str(sector_type)
            if source_sector_code and "source_sector_code" in frame.columns:
                mask &= frame["source_sector_code"].astype(str) == str(source_sector_code)
            return frame.loc[mask].reset_index(drop=True)
        module = self._module()
        self.refresh_sector_cache()
        if not hasattr(module, "get_stock_list_in_sector"):
            return pd.DataFrame()
        codes = module.get_stock_list_in_sector(source_sector_code or sector_name)
        normalizer = SectorNormalizer(self.name)
        return pd.DataFrame({"stock_code": [normalizer.normalize_stock_code(code) for code in codes]})

    def get_stock_sectors(self, stock_code: str) -> pd.DataFrame:
        if self._snapshot_map is None:
            return pd.DataFrame()
        normalizer = SectorNormalizer(self.name)
        normalized = normalizer.normalize_stock_code(stock_code)
        if "stock_code" not in self._snapshot_map.columns:
            return pd.DataFrame()
        return self._snapshot_map.loc[self._snapshot_map["stock_code"].astype(str) == str(normalized)].reset_index(drop=True)

    @staticmethod
    def _guess_sector_type(name: str) -> str:
        raw = str(name or "")
        if "指数" in raw or raw.startswith(("沪深", "中证", "上证", "深证")):
            return "index"
        if "地域" in raw:
            return "region"
        if "概念" in raw:
            return "concept"
        if "行业" in raw:
            return "industry"
        return "unknown"
