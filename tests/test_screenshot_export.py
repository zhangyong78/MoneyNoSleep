from __future__ import annotations

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.normalizer import normalize_kline_frame
from mns.review.bulk_screenshot_exporter import BulkScreenshotExporter, indicators_for_strategy
from mns.review.screenshot_exporter import ScreenshotExporter, resolve_chart_font_family, select_trade_chart_window, trade_marker_style


def test_screenshot_export_and_index_round_trip(tmp_path):
    run_id = "run1"
    trade = {
        "trade_id": "t1",
        "run_id": run_id,
        "stock_code": "600000.SH",
        "buy_time": pd.Timestamp("2026-01-02"),
        "buy_price": 10.2,
        "sell_time": pd.Timestamp("2026-01-05"),
        "sell_price": 10.8,
    }
    kline = pd.DataFrame(
        [
            {"stock_code": "600000.SH", "bar_time": "2026-01-01", "close": 10.0},
            {"stock_code": "600000.SH", "bar_time": "2026-01-02", "close": 10.2},
            {"stock_code": "600000.SH", "bar_time": "2026-01-05", "close": 10.8},
        ]
    )

    image_path = ScreenshotExporter(tmp_path / "screenshots").export_trade_chart(trade, kline, run_id=run_id)
    assert image_path.exists()

    store = DuckDBStore(tmp_path / "mns.duckdb")
    store.replace_trade_screenshot(
        {
            "screenshot_id": "s1",
            "trade_id": "t1",
            "run_id": run_id,
            "stock_code": "600000.SH",
            "image_path": str(image_path),
            "chart_timeframe": "1d",
            "start_time": pd.Timestamp("2026-01-01"),
            "end_time": pd.Timestamp("2026-01-05"),
            "created_time": pd.Timestamp("2026-01-06"),
        }
    )
    rows = store.get_run_trade_screenshots(run_id)

    assert len(rows) == 1
    assert rows.iloc[0]["image_path"] == str(image_path)


def test_chart_font_resolver_prefers_installed_chinese_font():
    assert resolve_chart_font_family(("Microsoft YaHei", "DejaVu Sans")) == "Microsoft YaHei"


def test_trade_chart_window_keeps_context_before_buy_and_after_sell():
    dates = pd.bdate_range("2026-01-01", periods=100)
    kline = pd.DataFrame({"stock_code": "600000.SH", "bar_time": dates, "close": range(100)})
    trade = {"buy_time": dates[60], "sell_time": dates[70]}

    window = select_trade_chart_window(kline, trade, lookback_bars=10, after_sell_bars=5)

    assert window["bar_time"].iloc[0] == dates[50]
    assert window["bar_time"].iloc[-1] == dates[75]
    assert len(window) == 26


def test_two_stage_charts_use_strategy_moving_averages():
    indicators = indicators_for_strategy("two_stage_trend")

    assert [indicator.column_name for indicator in indicators] == ["ma10", "ma20", "ma60"]


def test_trade_marker_style_uses_large_high_contrast_arrows():
    buy = trade_marker_style("buy")
    sell = trade_marker_style("sell")

    assert buy["marker"] == "^" and sell["marker"] == "v"
    assert buy["s"] >= 260 and sell["s"] >= 260
    assert buy["edgecolors"] != buy["color"]
    assert sell["edgecolors"] != sell["color"]


def test_bulk_screenshot_exporter_exports_run(tmp_path):
    run_id = "run2"
    store = DuckDBStore(tmp_path / "mns.duckdb")
    kline = normalize_kline_frame(
        pd.DataFrame(
            [
                {"stock_code": "600000.SH", "bar_time": "2026-01-01", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000},
                {"stock_code": "600000.SH", "bar_time": "2026-01-02", "open": 10.1, "high": 10.4, "low": 10.0, "close": 10.2, "volume": 100, "amount": 1020},
                {"stock_code": "600000.SH", "bar_time": "2026-01-05", "open": 10.6, "high": 10.9, "low": 10.4, "close": 10.8, "volume": 100, "amount": 1080},
            ]
        ),
        source="fixture",
        timeframe="1d",
    )
    store.initialize()
    store.replace_kline_bars(kline)
    store.replace_trades_for_run(
        run_id,
        pd.DataFrame(
            [
                {"trade_id": "t2", "run_id": run_id, "stock_code": "600000.SH", "strategy_name": "s", "action": "BUY", "price": 10.1, "quantity": 100, "trade_time": pd.Timestamp("2026-01-02"), "commission": 0.0, "tax": 0.0, "slippage": 0.0, "reason": "test"},
                {"trade_id": "t2", "run_id": run_id, "stock_code": "600000.SH", "strategy_name": "s", "action": "SELL", "price": 10.8, "quantity": 100, "trade_time": pd.Timestamp("2026-01-05"), "commission": 0.0, "tax": 0.0, "slippage": 0.0, "reason": "test"},
            ]
        ),
    )

    records = BulkScreenshotExporter(
        store=store,
        screenshot_exporter=ScreenshotExporter(tmp_path / "screenshots"),
    ).export_run(run_id)

    assert len(records) == 1
    assert store.get_run_trade_screenshots(run_id).shape[0] == 1
