from __future__ import annotations

import pandas as pd

from mns.review.chart_indicators import (
    BUILTIN_PRICE_OVERLAY_INDICATORS,
    DEFAULT_PRICE_OVERLAY_INDICATORS,
    ChartIndicatorSpec,
    add_price_overlay_indicators,
    available_price_overlay_indicators,
    indicator_display_names,
    load_default_price_overlay_indicators,
    required_indicator_history,
    resolve_price_overlay_indicators,
)


def test_add_price_overlay_indicators_calculates_each_stock_independently():
    frame = pd.DataFrame(
        [
            {"stock_code": "000001.SZ", "bar_time": "2026-01-01", "close": 10.0},
            {"stock_code": "000001.SZ", "bar_time": "2026-01-02", "close": 11.0},
            {"stock_code": "000001.SZ", "bar_time": "2026-01-03", "close": 12.0},
            {"stock_code": "000002.SZ", "bar_time": "2026-01-01", "close": 20.0},
            {"stock_code": "000002.SZ", "bar_time": "2026-01-02", "close": 21.0},
            {"stock_code": "000002.SZ", "bar_time": "2026-01-03", "close": 22.0},
        ]
    )
    frame["bar_time"] = pd.to_datetime(frame["bar_time"])

    indicators = [ChartIndicatorSpec(kind="ema", period=2, color="#000000")]
    enriched = add_price_overlay_indicators(frame, indicators)

    first_stock = enriched[enriched["stock_code"] == "000001.SZ"]["ema2"].reset_index(drop=True)
    second_stock = enriched[enriched["stock_code"] == "000002.SZ"]["ema2"].reset_index(drop=True)

    expected_first = frame[frame["stock_code"] == "000001.SZ"]["close"].ewm(span=2, adjust=False, min_periods=2).mean().reset_index(drop=True)
    expected_second = frame[frame["stock_code"] == "000002.SZ"]["close"].ewm(span=2, adjust=False, min_periods=2).mean().reset_index(drop=True)

    pd.testing.assert_series_equal(first_stock, expected_first, check_names=False)
    pd.testing.assert_series_equal(second_stock, expected_second, check_names=False)


def test_required_indicator_history_uses_indicator_configuration():
    assert required_indicator_history(DEFAULT_PRICE_OVERLAY_INDICATORS) == 165


def test_load_default_price_overlay_indicators_reads_review_yaml(tmp_path):
    config_path = tmp_path / "review.yaml"
    config_path.write_text(
        "chart:\n  price_overlay_indicators:\n    - EMA21\n    - MA55\n",
        encoding="utf-8",
    )
    load_default_price_overlay_indicators.cache_clear()

    indicators = load_default_price_overlay_indicators(config_path)

    assert indicator_display_names(indicators) == ["EMA21", "MA55"]


def test_available_and_resolved_indicators_support_ui_selection(tmp_path):
    config_path = tmp_path / "review.yaml"
    config_path.write_text(
        "chart:\n  price_overlay_indicators:\n    - EMA55\n",
        encoding="utf-8",
    )
    load_default_price_overlay_indicators.cache_clear()

    available = available_price_overlay_indicators(config_path)
    resolved = resolve_price_overlay_indicators(["EMA21", "MA55"], config_path=config_path)

    assert {"EMA21", "EMA55", "MA55"}.issubset(set(indicator_display_names(available)))
    assert indicator_display_names(resolved) == ["EMA21", "MA55"]
    assert any(spec.kind == "ma" and spec.period == 55 for spec in BUILTIN_PRICE_OVERLAY_INDICATORS)
