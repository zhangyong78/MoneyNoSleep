from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.parquet_store import ParquetStore
from mns.data.providers.base import DataProvider
from mns.data.sync import DailyKlineSyncService


class StubProvider(DataProvider):
    name = "stub"

    def __init__(self) -> None:
        self.kline_calls: list[tuple[str, datetime, datetime, str]] = []

    def get_stock_list(self) -> pd.DataFrame:
        return pd.DataFrame({"stock_code": ["600000.SH", "000001.SZ"]})

    def get_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame({"trade_date": pd.to_datetime(["2026-03-30", "2026-03-31"]), "is_open": [True, True]})

    def get_kline(self, stock_code: str, start_time: datetime, end_time: datetime, timeframe: str) -> pd.DataFrame:
        self.kline_calls.append((stock_code, start_time, end_time, timeframe))
        dates_by_code = {
            "600000.SH": ["2026-03-30", "2026-03-31"],
            "000001.SZ": ["2026-03-30"],
        }
        rows = []
        for value in dates_by_code.get(stock_code, []):
            ts = pd.Timestamp(value)
            rows.append(
                {
                    "stock_code": stock_code,
                    "stock_name": stock_code,
                    "exchange": stock_code.split(".")[-1],
                    "bar_time": ts,
                    "trade_date": ts.date(),
                    "timeframe": timeframe,
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000.0,
                    "amount": 10200.0,
                }
            )
        return pd.DataFrame(rows)


def test_sync_result_marks_lagging_stock_codes(tmp_path):
    service = DailyKlineSyncService(
        provider=StubProvider(),
        duckdb_store=DuckDBStore(tmp_path / "mns.duckdb"),
        parquet_store=ParquetStore(tmp_path / "parquet"),
    )

    result = service.sync(
        stock_codes=["600000.SH", "000001.SZ"],
        start_time=datetime(2026, 3, 1),
        end_time=datetime(2026, 3, 31),
        timeframe="1d",
    )

    assert result.rows_written == 3
    assert result.latest_trade_date == "2026-03-31"
    assert result.expected_latest_trade_date == "2026-03-31"
    assert result.lagging_stock_codes == ["000001.SZ"]
    assert result.requested_stock_count == 2
    assert result.synced_stock_count == 2


class PartiallyFailingProvider(StubProvider):
    def get_kline(self, stock_code: str, start_time: datetime, end_time: datetime, timeframe: str) -> pd.DataFrame:
        if stock_code == "000001.SZ":
            raise RuntimeError("mock failure")
        return super().get_kline(stock_code, start_time, end_time, timeframe)


def test_sync_collects_failed_stock_codes_without_aborting_batch(tmp_path):
    service = DailyKlineSyncService(
        provider=PartiallyFailingProvider(),
        duckdb_store=DuckDBStore(tmp_path / "mns.duckdb"),
        parquet_store=ParquetStore(tmp_path / "parquet"),
    )

    result = service.sync(
        stock_codes=["600000.SH", "000001.SZ"],
        start_time=datetime(2026, 3, 1),
        end_time=datetime(2026, 3, 31),
        timeframe="1d",
    )

    assert result.rows_written == 2
    assert result.requested_stock_count == 2
    assert result.synced_stock_count == 1
    assert result.failed_stock_codes == ["000001.SZ"]


def test_sync_emits_progress_events_for_preparing_running_and_results(tmp_path):
    service = DailyKlineSyncService(
        provider=PartiallyFailingProvider(),
        duckdb_store=DuckDBStore(tmp_path / "mns.duckdb"),
        parquet_store=ParquetStore(tmp_path / "parquet"),
    )
    events = []

    service.sync(
        stock_codes=["600000.SH", "000001.SZ"],
        start_time=datetime(2026, 3, 1),
        end_time=datetime(2026, 3, 31),
        timeframe="1d",
        progress_callback=events.append,
    )

    statuses = [event.status for event in events]
    assert statuses == ["preparing", "running", "synced", "running", "failed"]
    assert events[0].current == 0
    assert events[1].stock_code == "600000.SH"
    assert events[1].current == 0
    assert events[2].current == 1
    assert events[4].stock_code == "000001.SZ"
    assert events[4].message == "mock failure"


def test_sync_uses_incremental_start_and_skips_up_to_date_stocks(tmp_path):
    provider = StubProvider()
    store = DuckDBStore(tmp_path / "mns.duckdb")
    store.initialize()
    existing = pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "stock_name": "600000.SH",
                "exchange": "SH",
                "trade_date": pd.Timestamp("2026-03-31").date(),
                "bar_time": pd.Timestamp("2026-03-31"),
                "timeframe": "1d",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1000.0,
                "amount": 10200.0,
                "turnover": None,
                "pre_close": None,
                "adj_factor": None,
                "limit_up_price": None,
                "limit_down_price": None,
                "is_suspended": False,
                "source": "seed",
                "updated_at": pd.Timestamp("2026-03-31 15:00:00"),
                "data_quality": "OK",
            },
            {
                "stock_code": "000001.SZ",
                "stock_name": "000001.SZ",
                "exchange": "SZ",
                "trade_date": pd.Timestamp("2026-03-29").date(),
                "bar_time": pd.Timestamp("2026-03-29"),
                "timeframe": "1d",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1000.0,
                "amount": 10200.0,
                "turnover": None,
                "pre_close": None,
                "adj_factor": None,
                "limit_up_price": None,
                "limit_down_price": None,
                "is_suspended": False,
                "source": "seed",
                "updated_at": pd.Timestamp("2026-03-29 15:00:00"),
                "data_quality": "OK",
            },
        ]
    )
    store.replace_kline_bars(existing)

    service = DailyKlineSyncService(
        provider=provider,
        duckdb_store=store,
        parquet_store=ParquetStore(tmp_path / "parquet"),
    )

    result = service.sync(
        stock_codes=["600000.SH", "000001.SZ"],
        start_time=datetime(2026, 3, 1),
        end_time=datetime(2026, 3, 31),
        timeframe="1d",
    )

    assert result.skipped_stock_codes == ["600000.SH"]
    assert result.synced_stock_count == 1
    assert result.rows_written == 1
    assert len(provider.kline_calls) == 1
    assert provider.kline_calls[0][0] == "000001.SZ"
    assert provider.kline_calls[0][1].date().isoformat() == "2026-03-30"


def test_sync_supports_parallel_workers_with_provider_factory(tmp_path):
    calls: list[str] = []

    class RecordingProvider(StubProvider):
        def get_kline(self, stock_code: str, start_time: datetime, end_time: datetime, timeframe: str) -> pd.DataFrame:
            calls.append(stock_code)
            return super().get_kline(stock_code, start_time, end_time, timeframe)

    service = DailyKlineSyncService(
        provider=RecordingProvider(),
        duckdb_store=DuckDBStore(tmp_path / "mns.duckdb"),
        parquet_store=ParquetStore(tmp_path / "parquet"),
        provider_factory=RecordingProvider,
        max_workers=2,
    )

    result = service.sync(
        stock_codes=["600000.SH", "000001.SZ"],
        start_time=datetime(2026, 3, 1),
        end_time=datetime(2026, 3, 31),
        timeframe="1d",
    )

    assert result.rows_written == 3
    assert sorted(calls) == ["000001.SZ", "600000.SH"]


def test_sync_retries_failed_stock_once_then_succeeds(tmp_path):
    attempts: dict[str, int] = {}

    class FlakyProvider(StubProvider):
        def get_kline(self, stock_code: str, start_time: datetime, end_time: datetime, timeframe: str) -> pd.DataFrame:
            attempts[stock_code] = attempts.get(stock_code, 0) + 1
            if stock_code == "600000.SH" and attempts[stock_code] == 1:
                raise RuntimeError("temporary failure")
            return super().get_kline(stock_code, start_time, end_time, timeframe)

    service = DailyKlineSyncService(
        provider=FlakyProvider(),
        duckdb_store=DuckDBStore(tmp_path / "mns.duckdb"),
        parquet_store=ParquetStore(tmp_path / "parquet"),
        max_retries=1,
    )

    result = service.sync(
        stock_codes=["600000.SH"],
        start_time=datetime(2026, 3, 1),
        end_time=datetime(2026, 3, 31),
        timeframe="1d",
    )

    assert result.rows_written == 2
    assert result.failed_stock_codes == []
    assert attempts["600000.SH"] == 2


def test_sync_refreshes_daily_feature_store_after_daily_write(tmp_path):
    service = DailyKlineSyncService(
        provider=StubProvider(),
        duckdb_store=DuckDBStore(tmp_path / "mns.duckdb"),
        parquet_store=ParquetStore(tmp_path / "parquet"),
    )

    result = service.sync(
        stock_codes=["600000.SH", "000001.SZ"],
        start_time=datetime(2026, 3, 1),
        end_time=datetime(2026, 3, 31),
        timeframe="1d",
    )

    assert result.feature_rows_written > 0
    store = DuckDBStore(tmp_path / "mns.duckdb")
    feature_count = store.query_frame("SELECT COUNT(*) AS count FROM stock_daily_features").iloc[0]["count"]
    followup_count = store.query_frame("SELECT COUNT(*) AS count FROM stock_daily_followups").iloc[0]["count"]
    assert int(feature_count) > 0
    assert int(followup_count) > 0


def test_sync_keeps_kline_result_when_feature_refresh_fails(tmp_path):
    class BrokenFeatureSyncService(DailyKlineSyncService):
        def _refresh_feature_store(self, *, merged: pd.DataFrame, timeframe: str):
            return 0, 0, True, False, "Feature refresh failed for test"

    service = BrokenFeatureSyncService(
        provider=StubProvider(),
        duckdb_store=DuckDBStore(tmp_path / "mns.duckdb"),
        parquet_store=ParquetStore(tmp_path / "parquet"),
    )

    result = service.sync(
        stock_codes=["600000.SH", "000001.SZ"],
        start_time=datetime(2026, 3, 1),
        end_time=datetime(2026, 3, 31),
        timeframe="1d",
    )

    assert result.rows_written == 3
    assert result.feature_refresh_attempted is True
    assert result.feature_refresh_success is False
    assert result.feature_refresh_message == "Feature refresh failed for test"
