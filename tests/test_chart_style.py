from __future__ import annotations

import pandas as pd

from mns.review.chart_style import DOWN_COLOR, LIMIT_UP_COLOR, UP_COLOR, build_kline_colors, build_limit_up_mask


def test_build_limit_up_mask_prefers_limit_up_price_when_available():
    frame = pd.DataFrame(
        [
            {"open": 10.0, "close": 11.0, "pre_close": 10.0, "limit_up_price": 11.0},
            {"open": 10.2, "close": 10.4, "pre_close": 10.0, "limit_up_price": 11.0},
        ]
    )

    result = build_limit_up_mask(frame)

    assert result.tolist() == [True, False]


def test_build_limit_up_mask_falls_back_to_pre_close_pct_change():
    frame = pd.DataFrame(
        [
            {"open": 10.0, "close": 10.96, "pre_close": 10.0, "limit_up_price": None},
            {"open": 10.0, "close": 10.8, "pre_close": 10.0, "limit_up_price": None},
            {"open": 10.0, "close": 10.96, "pre_close": None, "limit_up_price": None},
        ]
    )

    result = build_limit_up_mask(frame)

    assert result.tolist() == [True, False, False]


def test_build_kline_colors_marks_limit_up_with_distinct_color():
    frame = pd.DataFrame(
        [
            {"open": 10.0, "close": 11.0, "pre_close": 10.0, "limit_up_price": 11.0},
            {"open": 10.0, "close": 10.5, "pre_close": 10.0, "limit_up_price": None},
            {"open": 10.5, "close": 10.0, "pre_close": 10.5, "limit_up_price": None},
        ]
    )

    result = build_kline_colors(frame)

    assert result == [LIMIT_UP_COLOR, UP_COLOR, DOWN_COLOR]
