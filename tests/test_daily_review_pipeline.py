from __future__ import annotations

from datetime import datetime

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.parquet_store import ParquetStore
from mns.data.providers.csv_provider import CSVPublicProvider
from mns.data.sync import DailyKlineSyncService
from mns.pipelines.daily_review import DailyReviewConfig, DailyReviewRunner


def _write_fixture_kline(root, stock_code: str, closes: list[float], volumes: list[float]) -> None:
    dates = pd.bdate_range("2026-01-01", periods=len(closes))
    rows = []
    for dt, close, volume in zip(dates, closes, volumes):
        rows.append(
            {
                "stock_code": stock_code,
                "stock_name": stock_code,
                "exchange": stock_code.split(".")[-1],
                "bar_time": dt,
                "open": close - 0.05,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": volume,
                "amount": close * volume,
            }
        )
    kline_dir = root / "kline"
    kline_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(kline_dir / f"{stock_code.replace('.', '_')}_1d.csv", index=False)


def test_csv_sync_and_daily_review_pipeline(tmp_path):
    raw_root = tmp_path / "raw"
    db_path = tmp_path / "mns.duckdb"
    parquet_root = tmp_path / "parquet"
    export_root = tmp_path / "exports"

    closes_a = [10 + i * 0.1 for i in range(70)]
    closes_b = [10 for _ in range(70)]
    volumes = [1000 for _ in range(70)]
    volumes[59] = 1500
    _write_fixture_kline(raw_root, "600000.SH", closes_a, volumes)
    _write_fixture_kline(raw_root, "000001.SZ", closes_b, volumes)

    service = DailyKlineSyncService(
        provider=CSVPublicProvider(raw_root),
        duckdb_store=DuckDBStore(db_path),
        parquet_store=ParquetStore(parquet_root),
    )
    sync_result = service.sync(
        stock_codes=["600000.SH", "000001.SZ"],
        start_time=datetime(2026, 1, 1),
        end_time=datetime(2026, 4, 30),
    )

    assert sync_result.rows_written == 140
    assert sync_result.parquet_files
    assert DuckDBStore(db_path).query_frame("SELECT COUNT(*) AS count FROM kline_bars").iloc[0]["count"] == 140

    as_of = str(pd.bdate_range("2026-01-01", periods=70)[59].date())
    runner = DailyReviewRunner(
        DailyReviewConfig(
            db_path=str(db_path),
            start_date="2026-01-01",
            end_date="2026-04-30",
            as_of_date=as_of,
            volume_ratio_min=1.1,
            hold_days=3,
            export_root=str(export_root),
        )
    )
    result = runner.run()

    assert result["candidates"]["stock_code"].tolist() == ["600000.SH"]
    assert len(result["signals"]) == 1
    assert len(result["trades"]) == 1
    store = DuckDBStore(db_path)
    runs = store.list_backtest_runs()
    assert runs.iloc[0]["run_id"] == result["run_id"]
    assert store.get_run_candidates(result["run_id"]).shape[0] == 1
    assert store.get_run_signals(result["run_id"]).shape[0] == 1
    assert store.get_run_trades(result["run_id"]).shape[0] == 2
    assert store.get_run_portfolio_snapshots(result["run_id"]).shape[0] == 1
    assert (export_root / f"{result['run_id']}_candidates.csv").exists()
    assert (export_root / f"{result['run_id']}_trades.csv").exists()
