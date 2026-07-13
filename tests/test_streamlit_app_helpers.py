from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.sync import DataSyncResult
from ui.streamlit_app import (
    _build_strategy_event_frame,
    _build_feature_refresh_feedback,
    _build_sync_feedback,
    _get_latest_trade_date,
    _merge_primary_with_export,
    _read_export,
    _resolve_sync_stock_codes,
    _today_date,
)


def test_read_export_returns_empty_frame_for_empty_csv(tmp_path: Path):
    export_root = tmp_path / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    (export_root / "run_1_signals.csv").write_text("", encoding="utf-8")

    result = _read_export(str(export_root), "run_1", "signals")

    assert result.empty


def test_build_sync_feedback_warns_when_latest_trade_date_is_not_fully_covered():
    level, text = _build_sync_feedback(
        DataSyncResult(
            rows_written=44,
            parquet_files=["a.parquet"],
            latest_trade_date="2026-03-30",
            expected_latest_trade_date="2026-03-31",
            lagging_stock_codes=["000001.SZ", "600000.SH"],
        )
    )

    assert level == "warning"
    assert "2026-03-31" in text
    assert "2026-03-30" in text


def test_build_sync_feedback_reports_skipped_up_to_date_stocks():
    level, text = _build_sync_feedback(
        DataSyncResult(
            rows_written=0,
            expected_latest_trade_date="2026-03-31",
            requested_stock_count=2,
            synced_stock_count=0,
            skipped_stock_codes=["000001.SZ", "600000.SH"],
        )
    )

    assert level == "success"
    assert "已覆盖到目标最新交易日 2026-03-31" in text


def test_build_feature_refresh_feedback_reports_success():
    level, text = _build_feature_refresh_feedback(
        DataSyncResult(
            rows_written=44,
            parquet_files=["a.parquet"],
            feature_refresh_attempted=True,
            feature_refresh_success=True,
            feature_rows_written=120,
            followup_rows_written=120,
            feature_refresh_message="Feature refresh succeeded for 2 stocks.",
        )
    )

    assert level == "success"
    assert "120" in text
    assert "Feature refresh succeeded for 2 stocks." in text


def test_build_feature_refresh_feedback_reports_failure():
    level, text = _build_feature_refresh_feedback(
        DataSyncResult(
            rows_written=44,
            parquet_files=["a.parquet"],
            feature_refresh_attempted=True,
            feature_refresh_success=False,
            feature_refresh_message="Feature refresh failed for 2 stocks: boom",
        )
    )

    assert level == "warning"
    assert "失败" in text
    assert "boom" in text


def test_get_latest_trade_date_returns_max_date_for_timeframe(tmp_path: Path):
    store = DuckDBStore(tmp_path / "mns.duckdb")
    store.initialize()
    df = pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "stock_name": "600000.SH",
                "exchange": "SH",
                "trade_date": pd.Timestamp("2026-05-20").date(),
                "bar_time": pd.Timestamp("2026-05-20"),
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
                "source": "test",
                "updated_at": pd.Timestamp("2026-05-21 10:00:00"),
                "data_quality": "OK",
            },
            {
                "stock_code": "600000.SH",
                "stock_name": "600000.SH",
                "exchange": "SH",
                "trade_date": pd.Timestamp("2026-05-21").date(),
                "bar_time": pd.Timestamp("2026-05-21"),
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
                "source": "test",
                "updated_at": pd.Timestamp("2026-05-21 10:00:00"),
                "data_quality": "OK",
            },
        ]
    )
    store.replace_kline_bars(df)

    assert _get_latest_trade_date(str(tmp_path / "mns.duckdb"), "1d") == "2026-05-21"


def test_today_date_returns_date_instance():
    assert isinstance(_today_date(), date)


class _StubProvider:
    def get_stock_list(self):
        return pd.DataFrame({"stock_code": ["600000.SH", "000001.SZ", "600000.SH"]})


def test_resolve_sync_stock_codes_uses_provider_stock_list_in_sync_all_mode():
    result = _resolve_sync_stock_codes(_StubProvider(), "600000.SH", sync_all=True)

    assert result == ["000001.SZ", "600000.SH"]


def test_resolve_sync_stock_codes_uses_manual_input_when_sync_all_disabled():
    result = _resolve_sync_stock_codes(_StubProvider(), "600000.SH, 000001.SZ", sync_all=False)

    assert result == ["600000.SH", "000001.SZ"]


def test_merge_primary_with_export_backfills_missing_fields():
    primary = pd.DataFrame(
        [
            {
                "stock_code": "588000.SH",
                "signal_time": "2026-06-20 10:30:00",
                "strategy_name": "ema_cross",
                "action": "BUY",
                "timeframe": "15m",
                "entry_price": 1.234,
                "stop_loss": None,
            }
        ]
    )
    export_frame = pd.DataFrame(
        [
            {
                "stock_code": "588000.SH",
                "signal_time": "2026-06-20 10:30:00",
                "strategy_name": "ema_cross",
                "action": "BUY",
                "timeframe": "15m",
                "entry_time": "2026-06-20 10:45:00",
                "stop_loss": 1.188,
                "reason": "EMA21 上穿 EMA55",
            }
        ]
    )

    merged = _merge_primary_with_export(
        primary,
        export_frame,
        key_columns=("stock_code", "signal_time", "strategy_name", "action", "timeframe"),
    )

    assert len(merged) == 1
    assert "entry_time" in merged.columns
    assert merged.iloc[0]["reason"] == "EMA21 上穿 EMA55"
    assert merged.iloc[0]["stop_loss"] == 1.188


def test_build_strategy_event_frame_includes_signal_and_trade_events():
    signals = pd.DataFrame(
        [
            {
                "signal_id": "sig_001",
                "stock_code": "588000.SH",
                "strategy_name": "ema_cross",
                "timeframe": "60m",
                "signal_time": "2026-06-20 10:30:00",
                "entry_price": 1.236,
                "stop_loss": 1.19,
                "reason": "交叉开仓",
                "status": "TRIGGERED",
            }
        ]
    )
    trade_actions = pd.DataFrame(
        [
            {
                "trade_id": "trade_001",
                "stock_code": "588000.SH",
                "strategy_name": "ema_cross",
                "timeframe": "60m",
                "trade_time": "2026-06-20 11:30:00",
                "price": 1.238,
                "action": "BUY",
                "reason": "成交开仓",
            },
            {
                "trade_id": "trade_001",
                "stock_code": "588000.SH",
                "strategy_name": "ema_cross",
                "timeframe": "60m",
                "trade_time": "2026-06-23 10:30:00",
                "price": 1.272,
                "action": "SELL",
                "reason": "移动止盈",
            },
        ]
    )

    events = _build_strategy_event_frame(signals, trade_actions)

    assert events["event_type"].tolist() == ["SIGNAL", "BUY", "SELL"]
    assert events["timeframe"].tolist() == ["60m", "60m", "60m"]
    assert events.iloc[0]["stop_loss"] == 1.19
    assert events.iloc[1]["marker_price"] == 1.238
