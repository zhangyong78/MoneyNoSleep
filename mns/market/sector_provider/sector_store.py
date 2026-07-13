from __future__ import annotations

from pathlib import Path

import pandas as pd

from mns.data.duckdb_store import DuckDBStore


class SectorStore:
    """DuckDB-backed storage facade for normalized sector tables."""

    def __init__(self, path: str | Path = "data/duckdb/mns.duckdb") -> None:
        self.store = DuckDBStore(path)
        self.store.initialize()

    def replace_source_snapshot(
        self,
        *,
        source: str,
        sectors: pd.DataFrame,
        stock_sector_map: pd.DataFrame,
        sector_daily: pd.DataFrame | None = None,
        sector_strength: pd.DataFrame | None = None,
        sector_leaders: pd.DataFrame | None = None,
    ) -> None:
        con = self.store.connect()
        try:
            con.execute("DELETE FROM sectors WHERE source = ?", (source,))
            con.execute("DELETE FROM stock_sector_map WHERE source = ?", (source,))
            con.execute("DELETE FROM sector_daily WHERE source = ?", (source,))
            con.execute("DELETE FROM sector_strength WHERE source = ?", (source,))
            if not sectors.empty:
                con.register("incoming_sectors", sectors)
                con.execute("INSERT INTO sectors SELECT * FROM incoming_sectors")
            if not stock_sector_map.empty:
                con.register("incoming_sector_map", stock_sector_map)
                con.execute("INSERT INTO stock_sector_map SELECT * FROM incoming_sector_map")
            if sector_daily is not None and not sector_daily.empty:
                con.register("incoming_sector_daily", sector_daily)
                con.execute("INSERT INTO sector_daily SELECT * FROM incoming_sector_daily")
            if sector_strength is not None and not sector_strength.empty:
                con.register("incoming_sector_strength", sector_strength)
                con.execute("INSERT INTO sector_strength SELECT * FROM incoming_sector_strength")
            if sector_leaders is not None and not sector_leaders.empty:
                con.register("incoming_sector_leaders", sector_leaders)
                con.execute("INSERT INTO sector_leaders SELECT * FROM incoming_sector_leaders")
        finally:
            con.close()

    def list_sectors(self, *, source: str | None = None, sector_type: str | None = None) -> pd.DataFrame:
        clauses = ["1=1"]
        params: list = []
        if source:
            clauses.append("source = ?")
            params.append(source)
        if sector_type:
            clauses.append("sector_type = ?")
            params.append(sector_type)
        return self.store.query_frame(
            f"""
            SELECT *
            FROM sectors
            WHERE {" AND ".join(clauses)}
            ORDER BY sector_type, sector_name
            """,
            tuple(params),
        )

    def get_stock_sectors(self, stock_code: str) -> pd.DataFrame:
        return self.store.query_frame(
            """
            SELECT *
            FROM stock_sector_map
            WHERE stock_code = ?
            ORDER BY source, sector_type, sector_name
            """,
            (stock_code,),
        )

    def get_sector_stocks(self, sector_id: str) -> pd.DataFrame:
        return self.store.query_frame(
            """
            SELECT *
            FROM stock_sector_map
            WHERE sector_id = ?
            ORDER BY stock_code
            """,
            (sector_id,),
        )
