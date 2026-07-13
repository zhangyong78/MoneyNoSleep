from __future__ import annotations

from mns.market.sector_provider.akshare_sector_provider import AKShareSectorProvider
from mns.market.sector_provider.base import SectorProvider
from mns.market.sector_provider.custom_sector_provider import CustomSectorProvider
from mns.market.sector_provider.pywencai_sector_provider import PyWenCaiSectorProvider
from mns.market.sector_provider.qmt_sector_provider import QMTSectorProvider
from mns.market.sector_provider.sector_normalizer import SectorNormalizer
from mns.market.sector_provider.sector_store import SectorStore
from mns.market.sector_provider.service import SectorSyncConfig, SectorSyncService
from mns.market.sector_provider.tushare_sector_provider import TushareSectorProvider


def build_sector_provider(name: str, **kwargs) -> SectorProvider:
    lowered = name.strip().lower()
    if lowered == "akshare":
        return AKShareSectorProvider(**kwargs)
    if lowered == "qmt":
        return QMTSectorProvider(**kwargs)
    if lowered == "custom":
        return CustomSectorProvider(**kwargs)
    if lowered == "tushare":
        return TushareSectorProvider(**kwargs)
    if lowered == "pywencai":
        return PyWenCaiSectorProvider(**kwargs)
    raise ValueError(f"unsupported sector provider: {name}")


__all__ = [
    "AKShareSectorProvider",
    "CustomSectorProvider",
    "PyWenCaiSectorProvider",
    "QMTSectorProvider",
    "SectorNormalizer",
    "SectorProvider",
    "SectorStore",
    "SectorSyncConfig",
    "SectorSyncService",
    "TushareSectorProvider",
    "build_sector_provider",
]
