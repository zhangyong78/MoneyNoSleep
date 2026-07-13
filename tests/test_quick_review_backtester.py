import pandas as pd

from mns.backtest.quick_review import QuickReviewBacktester, QuickReviewConfig


def test_quick_review_uses_next_bar_after_signal():
    kline = pd.DataFrame(
        [
            {"stock_code": "600000.SH", "bar_time": "2026-05-19", "open": 10.0, "close": 10.0},
            {"stock_code": "600000.SH", "bar_time": "2026-05-20", "open": 11.0, "close": 11.5},
            {"stock_code": "600000.SH", "bar_time": "2026-05-21", "open": 12.0, "close": 12.5},
            {"stock_code": "600000.SH", "bar_time": "2026-05-22", "open": 13.0, "close": 13.5},
        ]
    )
    signals = pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "strategy_name": "next_open_hold_n",
                "signal_time": "2026-05-19",
                "reason": "fixture",
            }
        ]
    )

    backtester = QuickReviewBacktester(QuickReviewConfig(initial_cash=100000, hold_days=2, per_trade_cash=11000))
    result = backtester.run(signals, kline, run_id="test_run")
    trades = result["trades"]

    assert len(trades) == 1
    assert trades.iloc[0]["buy_time"] == pd.Timestamp("2026-05-20")
    assert trades.iloc[0]["buy_price"] == 11.0
    assert trades.iloc[0]["sell_time"] == pd.Timestamp("2026-05-22")
    assert trades.iloc[0]["sell_price"] == 13.5
    assert trades.iloc[0]["quantity"] == 1000


def test_quick_review_applies_basic_costs():
    kline = pd.DataFrame(
        [
            {"stock_code": "600000.SH", "bar_time": "2026-05-19", "open": 10.0, "close": 10.0},
            {"stock_code": "600000.SH", "bar_time": "2026-05-20", "open": 10.0, "close": 10.0},
            {"stock_code": "600000.SH", "bar_time": "2026-05-21", "open": 11.0, "close": 11.0},
        ]
    )
    signals = pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "strategy_name": "next_open_hold_n",
                "signal_time": "2026-05-19",
                "reason": "fixture",
            }
        ]
    )

    backtester = QuickReviewBacktester(
        QuickReviewConfig(
            initial_cash=100000,
            hold_days=1,
            per_trade_cash=10000,
            commission_rate=0.001,
            stamp_tax_rate=0.001,
        )
    )
    trades = backtester.run(signals, kline, run_id="cost_run")["trades"]

    assert trades.iloc[0]["quantity"] == 1000
    assert trades.iloc[0]["commission"] == 21.0
    assert trades.iloc[0]["tax"] == 11.0
    assert trades.iloc[0]["pnl"] == 968.0


def test_quick_review_respects_signal_levels_and_risk_position():
    kline = pd.DataFrame(
        [
            {"stock_code": "600000.SH", "bar_time": "2026-05-19 09:35:00", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0},
            {"stock_code": "600000.SH", "bar_time": "2026-05-19 09:40:00", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1},
            {"stock_code": "600000.SH", "bar_time": "2026-05-19 09:45:00", "open": 10.1, "high": 10.1, "low": 8.8, "close": 9.0},
            {"stock_code": "600000.SH", "bar_time": "2026-05-19 09:50:00", "open": 9.0, "high": 9.5, "low": 8.9, "close": 9.2},
        ]
    )
    signals = pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "strategy_name": "ema21_ma55_pullback",
                "signal_time": "2026-05-19 09:35:00",
                "stop_loss": 9.0,
                "take_profit": 12.0,
                "reason": "fixture",
            }
        ]
    )

    trades = QuickReviewBacktester(
        QuickReviewConfig(
            hold_days=1,
            max_hold_bars=2,
            per_trade_cash=100000,
            risk_per_trade=1000,
            respect_signal_levels=True,
        )
    ).run(signals, kline, run_id="risk_run")["trades"]

    assert trades.iloc[0]["quantity"] == 1000
    assert trades.iloc[0]["sell_price"] == 9.0
    assert trades.iloc[0]["exit_reason"] == "stop_loss"
