from __future__ import annotations

import pandas as pd

from mns.backtest.semiconductor_ema import (
    SemiconductorEmaBaseConfig,
    add_semiconductor_ema_factors,
    build_signal_log,
    run_single_param_backtest,
)


def _make_daily_frame() -> pd.DataFrame:
    rows: list[dict] = []
    dates = pd.bdate_range("2025-01-01", periods=80)
    for idx, day in enumerate(dates):
        if idx < 60:
            close = 100 + idx * 0.12
        elif idx == 60:
            close = 106.8
        elif idx == 61:
            close = 106.9
        else:
            close = 106.9 - (idx - 61) * 0.55
        rows.append(
            {
                "stock_code": "300001.SZ",
                "stock_name": "Test Semi",
                "trade_date": day.date(),
                "bar_time": day,
                "open": close - 0.05,
                "high": close + 0.25,
                "low": close - (0.65 if idx == 60 else 0.18),
                "close": close,
                "volume": 1_000_000 + idx * 1_000,
                "amount": (1_000_000 + idx * 1_000) * close,
                "turnover": 1.0,
                "pre_close": None,
                "adj_factor": None,
                "limit_up_price": None,
                "limit_down_price": None,
                "is_suspended": False,
                "source": "test",
                "data_quality": "OK",
            }
        )
    return pd.DataFrame(rows)


def test_semiconductor_ema_backtest_generates_signal_and_trade():
    enriched = add_semiconductor_ema_factors(_make_daily_frame(), ema55_slope_days=5)
    params = {
        "name": "focus",
        "pullback_atr_buffer": 0.2,
        "atr_stop_multiple": 1.5,
        "use_ema55_slope_filter": True,
    }

    signal_log = build_signal_log(enriched, params=params)
    assert signal_log["entry_signal"].any()

    result = run_single_param_backtest(
        enriched,
        params=params,
        config=SemiconductorEmaBaseConfig(initial_cash=1_000_000, risk_pct=0.01),
    )

    assert not result["trades"].empty
    assert not result["equity_curve"].empty
    assert result["summary"]["trade_count"] >= 1
    assert set(result["trades"]["exit_reason"]).issubset({"ATR_STOP", "EMA_DEAD_CROSS", "END_OF_TEST"})
