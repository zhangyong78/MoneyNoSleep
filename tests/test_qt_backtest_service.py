from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mns.qt_backtest.charts import build_kline_chart_html
from mns.qt_backtest.service import QtBacktestRequest, QtBacktestService


def test_parse_stock_codes_accepts_chinese_comma():
    assert QtBacktestService.parse_stock_codes("000001.SZ， 600000.SH,,") == ["000001.SZ", "600000.SH"]
    assert QtBacktestService.parse_stock_codes("  ") is None


def test_run_backtest_normalizes_runner_result(monkeypatch):
    class FakeRunner:
        def __init__(self, config):
            self.config = config

        def run(self):
            return {
                "run_id": "qt_case",
                "signals": pd.DataFrame([{"stock_code": "000001.SZ", "entry_price": 10.0}]),
                "trades": pd.DataFrame([{"stock_code": "000001.SZ", "pnl": 100.0}]),
                "portfolio_snapshots": pd.DataFrame([{"total_equity": 1_000_100.0}]),
                "summary": {"trade_count": 1, "total_pnl": 100.0},
                "outputs": {"trades": Path("trades.csv")},
            }

    monkeypatch.setattr("mns.qt_backtest.service.DailyTrendFollowingReviewRunner", FakeRunner)
    monkeypatch.setattr(QtBacktestService, "_load_result_kline", lambda self, request, raw: pd.DataFrame())

    result = QtBacktestService().run_backtest(QtBacktestRequest(strategy_id="daily_trend_following"))

    assert result.run_id == "qt_case"
    assert result.summary["trade_count"] == 1
    assert len(result.signals) == 1
    assert result.outputs["trades"] == Path("trades.csv")


def test_empty_kline_chart_returns_placeholder_html():
    html = build_kline_chart_html(pd.DataFrame())

    assert "暂无可展示的 K 线数据" in html


def test_ema_cross_config_clamps_invalid_periods():
    config = QtBacktestService._ema_cross_config(  # noqa: SLF001 - private helper is the behavior under test
        QtBacktestRequest(
            strategy_id="ema_cross",
            params={"fast_period": 0, "slow_period": 1, "risk_per_trade": -5},
        )
    )

    assert config.fast_period == 2
    assert config.slow_period == 3
    assert config.risk_per_trade == 0.0


def test_validate_request_data_reports_available_timeframes(monkeypatch):
    service = QtBacktestService()

    def fake_describe(db_path, *, stock_codes=None, timeframe=None, start_date=None, end_date=None):
        if timeframe == "1d":
            return pd.DataFrame(columns=["stock_code", "timeframe", "min_date", "max_date", "bars"])
        return pd.DataFrame(
            [
                {"stock_code": "588000.SH", "timeframe": "15m", "min_date": "2025-06-20", "max_date": "2026-06-18", "bars": 3870},
                {"stock_code": "588000.SH", "timeframe": "1h", "min_date": "2025-06-20", "max_date": "2026-06-22", "bars": 970},
            ]
        )

    monkeypatch.setattr(service, "describe_available_data", fake_describe)

    with pytest.raises(ValueError) as exc_info:
        service.run_backtest(
            QtBacktestRequest(
                strategy_id="daily_trend_following",
                timeframe="1d",
                stock_codes=["588000.SH"],
            )
        )

    message = str(exc_info.value)
    assert "588000.SH" in message
    assert "1h" in message
    assert "日线趋势跟随需要 1d 数据" in message
