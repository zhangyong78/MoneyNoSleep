from __future__ import annotations

import pandas as pd

from mns.strategies.daily_trend_following import DailyTrendFollowingStrategy


def test_daily_trend_following_strategy_generates_condition_a_signal():
    data = pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "stock_name": "浦发银行",
                "trade_date": pd.Timestamp("2026-03-18").date(),
                "bar_time": pd.Timestamp("2026-03-18"),
                "close": 10.00,
                "low": 9.90,
                "volume": 100000,
                "ema20": 9.70,
                "ema50": 9.30,
                "ema20_slope_5": 0.04,
                "ema50_slope_5": 0.03,
                "ema20_ema50_bias": 0.043,
                "volume_ratio_20": 1.30,
                "atr14": 0.40,
                "recent_close_above_ema20_3": True,
            },
            {
                "stock_code": "600000.SH",
                "stock_name": "浦发银行",
                "trade_date": pd.Timestamp("2026-03-19").date(),
                "bar_time": pd.Timestamp("2026-03-19"),
                "close": 10.10,
                "low": 9.95,
                "volume": 150000,
                "ema20": 10.05,
                "ema50": 9.60,
                "ema20_slope_5": 0.03,
                "ema50_slope_5": 0.02,
                "ema20_ema50_bias": 0.046,
                "volume_ratio_20": 1.50,
                "atr14": 0.42,
                "recent_close_above_ema20_3": True,
            },
        ]
    )

    signals = DailyTrendFollowingStrategy().generate_signals(data)

    assert len(signals) == 1
    assert signals.iloc[0]["entry_condition"] in {"A", "A+B"}
    assert signals.iloc[0]["stop_loss"] < signals.iloc[0]["entry_price"]
