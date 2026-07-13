from __future__ import annotations

from datetime import date

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.timeframes import normalize_timeframe, timeframe_aliases


class LocalMarketData:
    """Read-only access to normalized local market data."""

    def __init__(self, store: DuckDBStore) -> None:
        self.store = store

    def get_kline(
        self,
        *,
        timeframe: str = "1d",
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        stock_codes: list[str] | None = None,
    ) -> pd.DataFrame:
        clauses = ["timeframe IN (SELECT UNNEST(?))"]
        params: list = [list(timeframe_aliases(timeframe))]

        if start_date is not None:
            clauses.append("trade_date >= ?")
            params.append(start_date)
        if end_date is not None:
            clauses.append("trade_date <= ?")
            params.append(end_date)
        if stock_codes:
            clauses.append("stock_code IN (SELECT UNNEST(?))")
            params.append(stock_codes)

        sql = f"""
            SELECT *
            FROM kline_bars
            WHERE {" AND ".join(clauses)}
            ORDER BY stock_code, bar_time
        """
        frame = self.store.query_frame(sql, tuple(params))
        if not frame.empty and "timeframe" in frame.columns:
            frame["timeframe"] = normalize_timeframe(timeframe)
        return frame
