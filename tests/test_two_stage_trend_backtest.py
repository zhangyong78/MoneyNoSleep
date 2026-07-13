from __future__ import annotations

import pandas as pd

from mns.backtest.two_stage_trend import TwoStageTrendBacktestConfig, TwoStageTrendBacktester


def _signal(code: str, signal_date: str = "2026-01-02", score: float = 3.0) -> dict:
    return {"stock_code": code, "stock_name": code, "trade_date": pd.Timestamp(signal_date).date(), "entry_date": pd.Timestamp("2026-01-05").date(), "score": score, "volume_ratio_5": 1.2, "breakout_pct": 0.02, "reason": "fixture"}


def _bar(code: str, date: str, open_price: float, close: float, atr14: float = 1.0, ma20: float | None = None) -> dict:
    return {"stock_code": code, "trade_date": date, "bar_time": date, "open": open_price, "high": max(open_price, close), "low": min(open_price, close), "close": close, "atr14": atr14, "ma20": ma20, "is_suspended": False, "limit_up_price": None, "limit_down_price": None}


def test_backtester_fills_only_ten_equal_slots_at_next_open():
    codes = [f"600{i:03d}.SH" for i in range(11)]
    signals = pd.DataFrame([_signal(code, score=20 - index) for index, code in enumerate(codes)])
    bars = pd.DataFrame([_bar(code, "2026-01-05", 10.0, 10.0) for code in codes])

    result = TwoStageTrendBacktester(
        TwoStageTrendBacktestConfig(initial_cash=200_000, max_positions=10, commission_rate=0, stamp_tax_rate=0, transfer_fee_rate=0, slippage_rate=0)
    ).run(signals, bars, run_id="slots")

    buys = result["trade_actions"].query("action == 'BUY'")
    assert len(buys) == 10
    assert set(buys["quantity"]) == {2000}
    assert {"strategy_name", "slippage"} <= set(result["trade_actions"].columns)
    assert result["skipped_orders"].iloc[0]["reason"] == "position_limit"


def test_backtester_trails_after_two_r_and_sells_on_following_open():
    signal = pd.DataFrame([_signal("600000.SH")])
    bars = pd.DataFrame(
        [
            _bar("600000.SH", "2026-01-05", 10.0, 10.0),
            _bar("600000.SH", "2026-01-06", 10.0, 11.1),
            _bar("600000.SH", "2026-01-07", 11.1, 12.2),
            _bar("600000.SH", "2026-01-08", 12.2, 13.0),
            _bar("600000.SH", "2026-01-09", 13.0, 10.4),
            _bar("600000.SH", "2026-01-12", 10.1, 10.1),
        ]
    )

    result = TwoStageTrendBacktester(
        TwoStageTrendBacktestConfig(commission_rate=0, stamp_tax_rate=0, transfer_fee_rate=0, slippage_rate=0)
    ).run(signal, bars, run_id="trail")

    trade = result["trades"].iloc[0]
    assert trade["exit_reason"] == "atr_trailing_stop"
    assert trade["sell_price"] == 11.0
    assert trade["r_multiple"] > 0


def test_initial_stop_uses_stop_price_or_gap_open_from_day_after_entry():
    signal = pd.DataFrame([_signal("600000.SH")])
    bars = pd.DataFrame(
        [
            _bar("600000.SH", "2026-01-05", 10.0, 9.0),
            _bar("600000.SH", "2026-01-06", 8.5, 8.7),
        ]
    )

    result = TwoStageTrendBacktester(
        TwoStageTrendBacktestConfig(commission_rate=0, stamp_tax_rate=0, transfer_fee_rate=0, slippage_rate=0)
    ).run(signal, bars, run_id="gap_stop")

    trade = result["trades"].iloc[0]
    assert trade["exit_reason"] == "initial_stop"
    assert trade["sell_price"] == 8.5


def test_missing_bar_carries_last_close_for_portfolio_valuation():
    signal = pd.DataFrame([_signal("600000.SH")])
    bars = pd.DataFrame(
        [
            _bar("600000.SH", "2026-01-05", 10.0, 10.0),
            _bar("000001.SZ", "2026-01-06", 8.0, 8.0),
            _bar("600000.SH", "2026-01-07", 10.0, 10.0),
        ]
    )

    result = TwoStageTrendBacktester(
        TwoStageTrendBacktestConfig(commission_rate=0, stamp_tax_rate=0, transfer_fee_rate=0, slippage_rate=0)
    ).run(signal, bars, run_id="missing_bar")

    missing_day = result["portfolio_snapshots"].loc[
        result["portfolio_snapshots"]["snapshot_time"] == pd.Timestamp("2026-01-06")
    ].iloc[0]
    assert missing_day["total_equity"] == 200_000


def test_backtester_skips_main_board_buy_when_next_open_is_limit_up():
    signal = pd.DataFrame([_signal("600000.SH")])
    bars = pd.DataFrame([
        _bar("600000.SH", "2026-01-02", 10.0, 10.0),
        _bar("600000.SH", "2026-01-05", 11.0, 11.0),
    ])

    result = TwoStageTrendBacktester(
        TwoStageTrendBacktestConfig(commission_rate=0, stamp_tax_rate=0, transfer_fee_rate=0, slippage_rate=0)
    ).run(signal, bars, run_id="main_limit_up")

    assert result["trade_actions"].empty
    assert result["skipped_orders"].iloc[0]["reason"] == "limit_up_unbuyable"


def test_backtester_skips_chinext_buy_when_next_open_is_limit_up():
    signal = pd.DataFrame([_signal("300001.SZ")])
    bars = pd.DataFrame([
        _bar("300001.SZ", "2026-01-02", 10.0, 10.0),
        _bar("300001.SZ", "2026-01-05", 12.0, 12.0),
    ])

    result = TwoStageTrendBacktester(
        TwoStageTrendBacktestConfig(commission_rate=0, stamp_tax_rate=0, transfer_fee_rate=0, slippage_rate=0)
    ).run(signal, bars, run_id="chinext_limit_up")

    assert result["trade_actions"].empty
    assert result["skipped_orders"].iloc[0]["reason"] == "limit_up_unbuyable"


def test_backtester_uses_fixed_per_position_cash_when_configured():
    signal = pd.DataFrame([_signal("600000.SH")])
    bars = pd.DataFrame([_bar("600000.SH", "2026-01-05", 10.0, 10.0)])

    result = TwoStageTrendBacktester(
        TwoStageTrendBacktestConfig(
            initial_cash=1_000_000,
            max_positions=10,
            per_position_cash=20_000,
            commission_rate=0,
            stamp_tax_rate=0,
            transfer_fee_rate=0,
            slippage_rate=0,
        )
    ).run(signal, bars, run_id="fixed_amount")

    buy = result["trade_actions"].query("action == 'BUY'").iloc[0]
    assert buy["quantity"] == 2000
    assert buy["quantity"] * buy["price"] == 20_000


def test_backtester_exits_at_next_open_after_close_breaks_ma20_when_always_enabled():
    signal = pd.DataFrame([_signal("600000.SH")])
    bars = pd.DataFrame([
        _bar("600000.SH", "2026-01-05", 10.0, 10.0, ma20=9.5),
        _bar("600000.SH", "2026-01-06", 10.0, 10.5, ma20=10.2),
        _bar("600000.SH", "2026-01-07", 10.5, 10.0, ma20=10.2),
        _bar("600000.SH", "2026-01-08", 9.8, 9.8, ma20=10.1),
    ])

    result = TwoStageTrendBacktester(
        TwoStageTrendBacktestConfig(
            ma20_exit_mode="always", commission_rate=0, stamp_tax_rate=0, transfer_fee_rate=0, slippage_rate=0
        )
    ).run(signal, bars, run_id="ma20_always")

    trade = result["trades"].iloc[0]
    assert trade["exit_reason"] == "ma20_exit"
    assert trade["sell_time"] == pd.Timestamp("2026-01-08")
    assert trade["sell_price"] == 9.8


def test_backtester_exits_at_next_open_after_ma20_break_only_when_position_is_profitable():
    signal = pd.DataFrame([_signal("600000.SH")])
    bars = pd.DataFrame([
        _bar("600000.SH", "2026-01-05", 10.0, 10.0, ma20=9.5),
        _bar("600000.SH", "2026-01-06", 10.0, 9.8, ma20=10.0),
        _bar("600000.SH", "2026-01-07", 9.7, 9.7, ma20=9.9),
        _bar("600000.SH", "2026-01-08", 9.7, 10.5, ma20=10.4),
        _bar("600000.SH", "2026-01-09", 10.5, 10.1, ma20=10.3),
        _bar("600000.SH", "2026-01-12", 10.0, 10.0, ma20=10.2),
    ])

    result = TwoStageTrendBacktester(
        TwoStageTrendBacktestConfig(
            ma20_exit_mode="profit_only", commission_rate=0, stamp_tax_rate=0, transfer_fee_rate=0, slippage_rate=0
        )
    ).run(signal, bars, run_id="ma20_profit_only")

    trade = result["trades"].iloc[0]
    assert trade["exit_reason"] == "ma20_profit_exit"
    assert trade["sell_time"] == pd.Timestamp("2026-01-12")
    assert trade["sell_price"] == 10.0
