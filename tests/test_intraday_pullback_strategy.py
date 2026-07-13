from __future__ import annotations

import pandas as pd

from mns.factors.technical import add_intraday_trend_factors
from mns.strategies.base import StrategyContext
from mns.strategies.ema21_ma55_pullback import Ema21Ma55PullbackStrategy


def test_intraday_pullback_strategy_generates_signal():
    rows = []
    start = pd.Timestamp("2026-03-02 09:35:00")
    for idx in range(70):
        close = 10 + idx * 0.03
        rows.append(
            {
                "stock_code": "600000.SH",
                "stock_name": "浦发银行",
                "exchange": "SH",
                "trade_date": start.date(),
                "bar_time": start + pd.Timedelta(minutes=5 * idx),
                "timeframe": "5m",
                "open": close - 0.02,
                "high": close + 0.05,
                "low": close - 0.05,
                "close": close,
                "volume": 100000 + idx * 100,
                "amount": close * (100000 + idx * 100),
                "turnover": None,
                "pre_close": None,
                "adj_factor": None,
                "limit_up_price": None,
                "limit_down_price": None,
                "is_suspended": False,
                "source": "fixture",
                "updated_at": pd.Timestamp("2026-03-02 16:00:00"),
                "data_quality": "OK",
            }
        )

    raw = pd.DataFrame(rows)
    baseline = add_intraday_trend_factors(raw)
    last_idx = raw.index[-1]
    raw.loc[last_idx, "low"] = float(baseline.iloc[-1]["ema21"]) * 0.999
    raw.loc[last_idx, "close"] = max(float(baseline.iloc[-1]["ema21"]) * 1.002, float(baseline.iloc[-1]["ma55"]) * 1.01)
    raw.loc[last_idx, "open"] = raw.loc[last_idx, "close"] - 0.02
    raw.loc[last_idx, "high"] = raw.loc[last_idx, "close"] + 0.05

    enriched = add_intraday_trend_factors(raw)
    strategy = Ema21Ma55PullbackStrategy()
    signals = strategy.generate_signals(enriched.tail(5), StrategyContext())

    assert len(signals) >= 1
    assert signals.iloc[-1]["stock_code"] == "600000.SH"
    assert signals.iloc[-1]["stop_loss"] < signals.iloc[-1]["entry_price"]
    assert signals.iloc[-1]["take_profit"] > signals.iloc[-1]["entry_price"]
