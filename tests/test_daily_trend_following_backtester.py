from __future__ import annotations

import pandas as pd

from mns.backtest.daily_trend_following import DailyTrendBacktestConfig, DailyTrendFollowingBacktester


def test_daily_trend_following_backtester_empty_result_includes_trade_actions():
    result = DailyTrendFollowingBacktester().run(pd.DataFrame(), pd.DataFrame(), run_id="empty_case")

    assert result["run_id"] == "empty_case"
    assert result["trades"].empty
    assert result["trade_actions"].empty
    assert result["portfolio_snapshots"].empty


def test_daily_trend_following_backtester_partial_then_trend_exit():
    kline = pd.DataFrame(
        [
            {"stock_code": "600000.SH", "trade_date": "2026-01-01", "bar_time": "2026-01-01", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "ema20": 9.8},
            {"stock_code": "600000.SH", "trade_date": "2026-01-02", "bar_time": "2026-01-02", "open": 10.1, "high": 12.5, "low": 10.2, "close": 12.2, "ema20": 10.5},
            {"stock_code": "600000.SH", "trade_date": "2026-01-05", "bar_time": "2026-01-05", "open": 12.0, "high": 12.1, "low": 11.3, "close": 11.4, "ema20": 11.8},
        ]
    )
    signals = pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "stock_name": "浦发银行",
                "trade_date": "2026-01-01",
                "bar_time": "2026-01-01",
                "strategy_name": "daily_trend_following",
                "entry_price": 10.0,
                "stop_loss": 9.0,
                "take_profit": 12.0,
                "atr14": 0.66,
                "ema20": 9.8,
                "ema50": 9.3,
                "ema20_slope_5": 0.03,
                "ema50_slope_5": 0.02,
                "volume_ratio_20": 1.5,
                "entry_condition": "A",
                "score": 1.0,
            }
        ]
    )

    result = DailyTrendFollowingBacktester(
        DailyTrendBacktestConfig(
            initial_cash=1_000_000,
            risk_per_trade_pct=0.008,
            max_position_pct=0.20,
            max_total_risk_pct=0.025,
            commission_rate=0.0,
            stamp_tax_rate=0.0,
            slippage_rate=0.0,
        )
    ).run(signals, kline, run_id="trend_case")

    trades = result["trades"]
    actions = result["trade_actions"]

    assert len(trades) == 1
    assert trades.iloc[0]["exit_type"] == "trend_stop"
    assert actions[actions["action"] == "SELL"].shape[0] == 2
    assert trades.iloc[0]["pnl"] > 0
