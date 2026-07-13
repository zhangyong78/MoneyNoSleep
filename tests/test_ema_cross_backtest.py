from __future__ import annotations

import pandas as pd
import pytest

from mns.backtest.ema_cross import EmaCrossBacktestConfig, EmaCrossBacktester, build_ema_cross_signals


def test_build_ema_cross_signals_uses_last_three_bar_low_as_stop():
    enriched = pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "stock_name": "浦发银行",
                "trade_date": pd.Timestamp("2026-03-18").date(),
                "bar_time": pd.Timestamp("2026-03-18 10:00:00"),
                "timeframe": "1h",
                "golden_cross": True,
                "next_bar_time": pd.Timestamp("2026-03-18 11:00:00"),
                "next_trade_date": pd.Timestamp("2026-03-18").date(),
                "next_open": 10.2,
                "pre_entry_3bar_low": 9.5,
                "ema_fast": 10.1,
                "ema_slow": 10.0,
            }
        ]
    )

    signals = build_ema_cross_signals(enriched)

    assert len(signals) == 1
    assert signals.iloc[0]["entry_price"] == 10.2
    assert signals.iloc[0]["stop_loss"] == 9.5
    assert signals.iloc[0]["risk_per_share_est"] == pytest.approx(0.7)


def test_ema_cross_backtester_trails_after_2r_and_exits_at_1r():
    kline = pd.DataFrame(
        [
            {"stock_code": "600000.SH", "stock_name": "浦发银行", "trade_date": "2026-03-18", "bar_time": "2026-03-18 10:00:00", "open": 9.9, "high": 10.0, "low": 9.8, "close": 10.0},
            {"stock_code": "600000.SH", "stock_name": "浦发银行", "trade_date": "2026-03-18", "bar_time": "2026-03-18 11:00:00", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.4},
            {"stock_code": "600000.SH", "stock_name": "浦发银行", "trade_date": "2026-03-18", "bar_time": "2026-03-18 12:00:00", "open": 10.4, "high": 11.2, "low": 10.3, "close": 11.0},
            {"stock_code": "600000.SH", "stock_name": "浦发银行", "trade_date": "2026-03-18", "bar_time": "2026-03-18 13:00:00", "open": 11.0, "high": 12.2, "low": 10.9, "close": 12.0},
            {"stock_code": "600000.SH", "stock_name": "浦发银行", "trade_date": "2026-03-18", "bar_time": "2026-03-18 14:00:00", "open": 11.4, "high": 11.6, "low": 10.9, "close": 11.1},
        ]
    )
    signals = pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "stock_name": "浦发银行",
                "trade_date": pd.Timestamp("2026-03-18").date(),
                "bar_time": pd.Timestamp("2026-03-18 10:00:00"),
                "strategy_name": "ema21_ema55_cross",
                "action": "BUY",
                "timeframe": "1h",
                "signal_time": pd.Timestamp("2026-03-18 10:00:00"),
                "entry_time": pd.Timestamp("2026-03-18 11:00:00"),
                "entry_price": 10.0,
                "stop_loss": 9.0,
                "take_profit": None,
                "score": 1.0,
                "reason": "fixture",
                "status": "NEW",
                "risk_per_share_est": 1.0,
            }
        ]
    )

    result = EmaCrossBacktester(
        EmaCrossBacktestConfig(
            initial_cash=1_000_000,
            risk_per_trade=5_000,
            commission_rate=0.0,
            stamp_tax_rate=0.0,
            transfer_fee_rate=0.0,
            slippage_rate=0.0,
        )
    ).run(signals, kline, run_id="ema_cross_case")

    trades = result["trades"]
    assert len(trades) == 1
    assert trades.iloc[0]["quantity"] == 5000
    assert trades.iloc[0]["sell_price"] == 11.0
    assert trades.iloc[0]["exit_reason"] == "TRAILING_STOP_1R"
    assert trades.iloc[0]["r_multiple"] == 1.0
