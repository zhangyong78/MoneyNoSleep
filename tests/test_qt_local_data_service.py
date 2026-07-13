from __future__ import annotations

from datetime import datetime
import json

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.normalizer import normalize_kline_frame
from mns.data.sync import DataSyncProgress, DataSyncResult
from mns.qt_local_data.service import LocalDataWorkbenchService


def _sample_frame(stock_code: str, *, stock_name: str, exchange: str, start_price: float) -> pd.DataFrame:
    rows = [
        {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "exchange": exchange,
            "trade_date": pd.Timestamp("2026-06-24").date(),
            "bar_time": pd.Timestamp("2026-06-24 09:35:00"),
            "open": start_price,
            "high": start_price + 0.2,
            "low": start_price - 0.1,
            "close": start_price + 0.1,
            "volume": 100,
            "amount": 1000,
            "turnover": 0.1,
        },
        {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "exchange": exchange,
            "trade_date": pd.Timestamp("2026-06-24").date(),
            "bar_time": pd.Timestamp("2026-06-24 09:40:00"),
            "open": start_price + 0.1,
            "high": start_price + 0.3,
            "low": start_price,
            "close": start_price + 0.2,
            "volume": 120,
            "amount": 1200,
            "turnover": 0.2,
        },
        {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "exchange": exchange,
            "trade_date": pd.Timestamp("2026-06-24").date(),
            "bar_time": pd.Timestamp("2026-06-24 09:45:00"),
            "open": start_price + 0.2,
            "high": start_price + 0.4,
            "low": start_price + 0.1,
            "close": start_price + 0.3,
            "volume": 140,
            "amount": 1400,
            "turnover": 0.3,
        },
    ]
    return normalize_kline_frame(pd.DataFrame(rows), source="unit_test", timeframe="5m")


def _build_service(tmp_path) -> LocalDataWorkbenchService:
    db_path = tmp_path / "mns.duckdb"
    parquet_root = tmp_path / "parquet"
    store = DuckDBStore(db_path)
    store.initialize()
    frame = pd.concat(
        [
            _sample_frame("600000.SH", stock_name="浦发银行", exchange="SH", start_price=10.0),
            _sample_frame("510300.SH", stock_name="沪深300ETF", exchange="SH", start_price=4.0),
        ],
        ignore_index=True,
    )
    store.replace_kline_bars(frame)
    return LocalDataWorkbenchService(db_path=db_path, parquet_root=parquet_root, workspace_root=tmp_path)


def test_query_local_overview_and_summary_support_market_filters(tmp_path):
    service = _build_service(tmp_path)

    overview = service.query_local_overview()
    assert len(overview) == 1
    assert overview[0].timeframe == "5m"
    assert overview[0].stock_count == 2

    summary = service.query_local_summary(timeframe="5m", market_groups=["all_a"])
    assert [row.stock_code for row in summary] == ["600000.SH"]
    assert summary[0].source == "unit_test"


def test_query_local_bars_returns_latest_rows(tmp_path):
    service = _build_service(tmp_path)

    frame = service.query_local_bars(
        timeframe="5m",
        stock_codes_text="600000.SH",
        start_time=datetime(2026, 6, 24, 9, 30, 0),
        end_time=datetime(2026, 6, 24, 15, 0, 0),
        limit=2,
    )

    assert len(frame) == 2
    assert frame.iloc[0]["stock_code"] == "600000.SH"
    assert pd.Timestamp(frame.iloc[0]["bar_time"]).strftime("%H:%M:%S") == "09:45:00"


def test_convert_local_timeframes_writes_target_rows(tmp_path):
    service = _build_service(tmp_path)

    result = service.convert_local_timeframes(
        source_timeframe="5m",
        target_timeframes=["15m"],
        stock_codes_text="600000.SH",
        start_time=datetime(2026, 6, 24, 9, 30, 0),
        end_time=datetime(2026, 6, 24, 15, 0, 0),
    )

    assert result.total_rows_written == 1
    summary = service.query_local_summary(timeframe="15m", stock_codes_text="600000.SH")
    assert len(summary) == 1
    assert summary[0].bar_count == 1


def test_convert_local_timeframes_emits_progress_events(tmp_path):
    service = _build_service(tmp_path)
    events: list[dict[str, object]] = []

    result = service.convert_local_timeframes(
        source_timeframe="5m",
        target_timeframes=["15m"],
        stock_codes_text="600000.SH",
        start_time=datetime(2026, 6, 24, 9, 30, 0),
        end_time=datetime(2026, 6, 24, 15, 0, 0),
        progress_callback=events.append,
    )

    assert result.total_rows_written == 1
    assert [event["stage"] for event in events] == ["start", "step", "done"]
    assert events[0]["total_steps"] == 1
    assert events[1]["stock_code"] == "600000.SH"
    assert events[1]["target_timeframe"] == "15m"


def test_build_baostock_bulk_sync_command_supports_market_groups(tmp_path):
    service = _build_service(tmp_path)

    command = service.build_baostock_bulk_sync_command(
        start_time=datetime(2020, 1, 2, 9, 30, 0),
        end_time=datetime(2026, 6, 24, 15, 0, 0),
        fetch_timeframes=["5m", "1d"],
        derive_source_timeframe="5m",
        derive_timeframes=["15m", "30m", "1h"],
        market_groups=["sh_etf"],
        state_path="data/logs/test_state.json",
        reset_state=True,
    )

    joined = " ".join(command)
    assert "tools" in joined
    assert "--market-groups sh_etf" in joined
    assert "--reset-state" in joined


def test_inspect_baostock_state_file_detects_config_mismatch(tmp_path):
    service = _build_service(tmp_path)
    state_path = tmp_path / "state.json"
    existing_run_config = {
        "db": str(service.db_path),
        "parquet_root": str(service.parquet_root),
        "stock_selection_mode": "explicit",
        "stock_codes": ["000001.SZ", "600000.SH"],
        "sync_all": False,
        "market_groups": [],
        "start": "2020-01-02T09:30:00",
        "end": "2026-06-24T15:00:00",
        "fetch_timeframes": ["5m", "1d"],
        "derive_source_timeframe": "5m",
        "derive_timeframes": ["15m", "30m", "1h"],
        "adjustflag": "2",
        "user_id": "",
        "has_password": False,
        "max_retries": 2,
    }
    state_path.write_text(
        json.dumps(
            {
                "created_at": "2026-06-24 23:05:01",
                "updated_at": "2026-06-24 23:08:51",
                "run_config": existing_run_config,
                "phases": {},
                "completed": True,
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    current_run_config = service.build_baostock_bulk_sync_run_config(
        start_time=datetime(2020, 1, 2, 9, 30, 0),
        end_time=datetime(2026, 6, 25, 15, 0, 0),
        fetch_timeframes=["1d"],
        derive_source_timeframe="5m",
        derive_timeframes=[],
        market_groups=["all_a"],
    )
    inspection = service.inspect_baostock_state_file(
        state_path=state_path,
        run_config=current_run_config,
    )

    assert inspection["exists"] is True
    assert inspection["matches"] is False
    assert "different sync task" in str(inspection["message"])


def test_suggest_baostock_state_path_returns_new_json_name(tmp_path):
    service = _build_service(tmp_path)
    run_config = service.build_baostock_bulk_sync_run_config(
        start_time=datetime(2020, 1, 2, 9, 30, 0),
        end_time=datetime(2026, 6, 25, 15, 0, 0),
        fetch_timeframes=["1d"],
        derive_source_timeframe="5m",
        derive_timeframes=[],
        market_groups=["all_a"],
    )

    suggested = service.suggest_baostock_state_path(
        state_path=tmp_path / "state.json",
        run_config=run_config,
    )

    assert suggested.endswith(".json")
    assert "all_a" in suggested


def test_qmt_helpers_support_connection_and_sync(monkeypatch, tmp_path):
    service = _build_service(tmp_path)

    class FakeQMTProvider:
        def __init__(self, *, dividend_type="front", ip="", port=None, **kwargs):
            self.dividend_type = dividend_type
            self.ip = ip
            self.port = port

        def connection_info(self):
            return {
                "connected": True,
                "peer_addr": f"{self.ip or '127.0.0.1'}:{self.port or 58610}",
            }

        def get_stock_list(self, *, include_etf=False):
            codes = ["000001.SZ", "600000.SH"]
            if include_etf:
                codes.append("510300.SH")
            return pd.DataFrame({"stock_code": codes})

    class FakeDailyKlineSyncService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def sync(
            self,
            *,
            stock_codes,
            start_time,
            end_time,
            timeframe,
            resume_from_latest_local=True,
            progress_callback=None,
        ):
            if progress_callback is not None:
                progress_callback(DataSyncProgress(1, len(stock_codes), stock_codes[0], "synced", "ok"))
            return DataSyncResult(
                rows_written=10,
                parquet_files=["a.parquet"],
                quality_issue_count=0,
                requested_stock_count=len(stock_codes),
                synced_stock_count=len(stock_codes),
            )

    monkeypatch.setattr("mns.qt_local_data.service.QMTProvider", FakeQMTProvider)
    monkeypatch.setattr("mns.qt_local_data.service.DailyKlineSyncService", FakeDailyKlineSyncService)

    info = service.get_qmt_connection_info(ip="10.0.0.8", port=58611)
    assert info["connected"] is True
    assert info["peer_addr"] == "10.0.0.8:58611"

    codes = service.resolve_qmt_stock_codes(sync_all=True)
    assert codes == ["000001.SZ", "600000.SH"]
    codes_with_etf = service.resolve_qmt_stock_codes(sync_all=True, include_etf=True)
    assert codes_with_etf == ["000001.SZ", "600000.SH", "510300.SH"]

    progress_events = []
    log_lines = []
    results_by_timeframe, synced_codes = service.sync_qmt_kline(
        sync_all=True,
        start_time=datetime(2026, 6, 1, 9, 30, 0),
        end_time=datetime(2026, 6, 2, 15, 0, 0),
        timeframes=["5m", "15m"],
        progress_callback=progress_events.append,
        log_callback=log_lines.append,
    )

    assert sorted(results_by_timeframe.keys()) == ["15m", "5m"]
    assert results_by_timeframe["5m"].rows_written == 10
    assert synced_codes == ["000001.SZ", "600000.SH"]
    assert progress_events[0].status == "5m:synced"
    assert any("miniQMT sync start" in line for line in log_lines)
