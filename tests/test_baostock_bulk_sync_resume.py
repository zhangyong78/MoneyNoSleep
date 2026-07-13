from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.normalizer import normalize_kline_frame


def _load_baostock_bulk_sync_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "baostock_bulk_sync.py"
    spec = importlib.util.spec_from_file_location("baostock_bulk_sync_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sample_kline(stock_code: str) -> pd.DataFrame:
    rows = [
        {
            "stock_code": stock_code,
            "stock_name": stock_code,
            "exchange": stock_code.split(".")[-1],
            "trade_date": pd.Timestamp("2026-06-24").date(),
            "bar_time": pd.Timestamp("2026-06-24 09:35:00"),
            "open": 10.0,
            "high": 10.2,
            "low": 9.9,
            "close": 10.1,
            "volume": 100,
            "amount": 1000,
            "turnover": 0.1,
        },
        {
            "stock_code": stock_code,
            "stock_name": stock_code,
            "exchange": stock_code.split(".")[-1],
            "trade_date": pd.Timestamp("2026-06-25").date(),
            "bar_time": pd.Timestamp("2026-06-25 14:55:00"),
            "open": 10.1,
            "high": 10.3,
            "low": 10.0,
            "close": 10.2,
            "volume": 120,
            "amount": 1200,
            "turnover": 0.2,
        },
    ]
    return normalize_kline_frame(pd.DataFrame(rows), source="unit_test", timeframe="5m")


def test_load_or_create_state_allows_run_config_change(tmp_path):
    module = _load_baostock_bulk_sync_module()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "created_at": "2026-06-25 21:00:00",
                "updated_at": "2026-06-25 21:05:00",
                "run_config": {"start": "2026-06-24T09:30:00", "end": "2026-06-24T15:00:00"},
                "phases": {},
                "completed": True,
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    state, config_mismatch = module._load_or_create_state(
        state_path,
        run_config={"start": "2026-06-24T09:30:00", "end": "2026-06-25T15:00:00"},
        reset_state=False,
    )

    assert config_mismatch is True
    assert state["run_config"]["end"] == "2026-06-25T15:00:00"
    assert state["completed"] is False
    assert len(state.get("run_config_history", [])) == 1


def test_reconcile_fetch_phase_progress_uses_local_coverage_and_empty_state(tmp_path):
    module = _load_baostock_bulk_sync_module()
    db_path = tmp_path / "mns.duckdb"
    store = DuckDBStore(db_path)
    store.initialize()
    store.replace_kline_bars(_sample_kline("600000.SH"))

    phase_state = {
        "completed_stock_codes": ["600000.SH", "000001.SZ"],
        "summaries": [
            {"stock_code": "600000.SH", "status": "synced"},
            {"stock_code": "000001.SZ", "status": "empty"},
        ],
        "completed": True,
    }
    pending, local_completed, preserved_state_only = module._reconcile_phase_progress(
        phase_state=phase_state,
        phase="fetch",
        timeframe="5m",
        stock_codes=["600000.SH", "000001.SZ", "000002.SZ"],
        store=store,
        start_time=datetime(2026, 6, 24, 9, 30, 0),
        end_time=datetime(2026, 6, 25, 15, 0, 0),
    )

    assert pending == ["000002.SZ"]
    assert local_completed == {"600000.SH"}
    assert preserved_state_only == {"000001.SZ"}
    assert phase_state["completed_stock_codes"] == ["600000.SH", "000001.SZ"]


def test_reconcile_derive_phase_progress_rechecks_previous_empty_symbols(tmp_path):
    module = _load_baostock_bulk_sync_module()
    db_path = tmp_path / "mns.duckdb"
    store = DuckDBStore(db_path)
    store.initialize()

    phase_state = {
        "completed_stock_codes": ["600000.SH"],
        "summaries": [{"stock_code": "600000.SH", "status": "empty"}],
        "completed": True,
    }
    pending, local_completed, preserved_state_only = module._reconcile_phase_progress(
        phase_state=phase_state,
        phase="derive",
        timeframe="15m",
        stock_codes=["600000.SH"],
        store=store,
        start_time=datetime(2026, 6, 24, 9, 30, 0),
        end_time=datetime(2026, 6, 25, 15, 0, 0),
    )

    assert pending == ["600000.SH"]
    assert local_completed == set()
    assert preserved_state_only == set()
    assert phase_state["completed_stock_codes"] == []
