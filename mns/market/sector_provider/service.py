from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from mns.market.leader_detector import identify_sector_leaders
from mns.market.sector_provider.base import SectorProvider
from mns.market.sector_provider.sector_normalizer import SectorNormalizer
from mns.market.sector_provider.sector_store import SectorStore
from mns.market.sector_strength import compute_sector_strength


@dataclass(frozen=True)
class SectorSyncConfig:
    db_path: str = "data/duckdb/mns.duckdb"
    sector_types: list[str] | None = None
    sector_names: list[str] | None = None
    include_daily: bool = True
    max_sectors: int | None = None


class SectorSyncService:
    """Fetch, normalize, score, and persist sector snapshots."""

    def __init__(self, *, provider: SectorProvider, config: SectorSyncConfig) -> None:
        self.provider = provider
        self.config = config
        self.normalizer = SectorNormalizer(provider.name)
        self.store = SectorStore(config.db_path)

    def run(self) -> dict[str, int | str]:
        sectors = self.normalizer.normalize_sector_list(self.provider.get_sector_list(self.config.sector_types))
        if sectors.empty:
            raise ValueError(
                f"No sector rows fetched from provider `{self.provider.name}`. "
                "Check upstream connectivity or switch provider."
            )
        if self.config.sector_names:
            wanted = set(self.config.sector_names)
            sectors = sectors.loc[sectors["sector_name"].isin(wanted)].reset_index(drop=True)
        if self.config.max_sectors is not None:
            sectors = sectors.head(self.config.max_sectors).reset_index(drop=True)

        mappings: list[pd.DataFrame] = []
        for _, sector in sectors.iterrows():
            members = self.provider.get_sector_stocks(
                sector_name=str(sector["sector_name"]),
                sector_type=str(sector["sector_type"]),
                source_sector_code=str(sector["source_sector_code"]) if pd.notna(sector["source_sector_code"]) else None,
            )
            mappings.append(
                self.normalizer.normalize_stock_sector_map(
                    members,
                    sector_id=str(sector["sector_id"]),
                    sector_name=str(sector["sector_name"]),
                    sector_type=str(sector["sector_type"]),
                )
            )
        stock_sector_map = pd.concat(mappings, ignore_index=True) if mappings else pd.DataFrame()

        sector_daily = pd.DataFrame()
        sector_strength = pd.DataFrame()
        sector_leaders = pd.DataFrame()
        if self.config.include_daily:
            raw_daily = self.provider.get_sector_daily(sector_types=self.config.sector_types)
            sector_daily = self.normalizer.normalize_sector_daily(raw_daily, sectors=sectors)
            sector_strength = compute_sector_strength(sector_daily)
            sector_leaders = identify_sector_leaders(sector_daily)

        self.store.replace_source_snapshot(
            source=self.provider.name,
            sectors=sectors,
            stock_sector_map=stock_sector_map,
            sector_daily=sector_daily,
            sector_strength=sector_strength,
            sector_leaders=sector_leaders,
        )
        return {
            "source": self.provider.name,
            "sector_count": int(len(sectors)),
            "mapping_count": int(len(stock_sector_map)),
            "sector_daily_count": int(len(sector_daily)),
            "sector_strength_count": int(len(sector_strength)),
            "sector_leader_count": int(len(sector_leaders)),
            "db_path": str(Path(self.config.db_path)),
        }
