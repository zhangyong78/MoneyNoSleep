from __future__ import annotations

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.local_data import LocalMarketData
from mns.data.timeframes import normalize_timeframe, timeframe_aliases


def _sample_kline(timeframe: str, *, close: float = 10.2) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "stock_name": "600000.SH",
                "exchange": "SH",
                "trade_date": pd.Timestamp("2026-03-31").date(),
                "bar_time": pd.Timestamp("2026-03-31 10:30:00"),
                "timeframe": timeframe,
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": close,
                "volume": 1000.0,
                "amount": 10200.0,
                "turnover": None,
                "pre_close": None,
                "adj_factor": None,
                "limit_up_price": None,
                "limit_down_price": None,
                "is_suspended": False,
                "source": "test",
                "updated_at": pd.Timestamp("2026-03-31 15:00:00"),
                "data_quality": "OK",
            }
        ]
    )


def test_timeframe_normalization_maps_60m_to_1h():
    assert normalize_timeframe("60m") == "1h"
    assert normalize_timeframe("1h") == "1h"
    assert timeframe_aliases("60m") == ("1h", "60m")


def test_replace_kline_bars_canonicalizes_hourly_aliases(tmp_path):
    store = DuckDBStore(tmp_path / "mns.duckdb")
    store.initialize()

    rows_written = store.replace_kline_bars(_sample_kline("60m"))
    assert rows_written == 1

    frame = store.query_frame("SELECT DISTINCT timeframe FROM kline_bars")
    assert frame["timeframe"].tolist() == ["1h"]


def test_local_market_data_reads_hourly_aliases_from_legacy_rows(tmp_path):
    store = DuckDBStore(tmp_path / "mns.duckdb")
    store.initialize()
    con = store.connect()
    try:
        con.register("incoming_df", _sample_kline("60m"))
        con.execute("INSERT INTO kline_bars SELECT * FROM incoming_df")
    finally:
        con.close()

    frame = LocalMarketData(store).get_kline(timeframe="1h", stock_codes=["600000.SH"])
    assert len(frame) == 1
    assert frame.iloc[0]["timeframe"] == "1h"


def test_initialize_migrates_legacy_hourly_rows_to_canonical_1h(tmp_path):
    store = DuckDBStore(tmp_path / "mns.duckdb")
    store.initialize()

    legacy = _sample_kline("60m", close=10.6)
    modern = _sample_kline("1h", close=10.1)
    con = store.connect()
    try:
        con.register("legacy_df", legacy)
        con.register("modern_df", modern)
        con.execute("INSERT INTO kline_bars SELECT * FROM legacy_df")
        con.execute("INSERT INTO kline_bars SELECT * FROM modern_df")
    finally:
        con.close()

    store.initialize()

    frame = store.query_frame(
        """
        SELECT timeframe, close
        FROM kline_bars
        WHERE stock_code = '600000.SH'
        """
    )
    assert len(frame) == 1
    assert frame.iloc[0]["timeframe"] == "1h"
    assert frame.iloc[0]["close"] == 10.6
