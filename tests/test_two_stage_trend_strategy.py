from __future__ import annotations

import pandas as pd

from mns.strategies.two_stage_trend import TwoStageTrendStrategy, TwoStageTrendStrategyConfig


def _bars(*, closes: list[float], volumes: list[float], stock_name: str = "样本股") -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=len(closes))
    return pd.DataFrame(
        {
            "stock_code": "600000.SH",
            "stock_name": stock_name,
            "trade_date": dates.date,
            "bar_time": dates,
            "timeframe": "1d",
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": volumes,
            "limit_up_price": [None] * len(closes),
            "is_suspended": False,
        }
    )


def test_two_stage_signal_requires_attention_then_trend_and_two_confirmations():
    data = _bars(
        closes=[10, 10, 10, 10, 10, 10.7, 10.5, 10.4, 10.6, 11.0, 11.3],
        volumes=[100] * 5 + [220, 90, 90, 100, 160, 180],
    )
    strategy = TwoStageTrendStrategy(
        TwoStageTrendStrategyConfig(
            ma10_window=3,
            ma20_window=4,
            ma60_window=5,
            volume_ma_window=3,
            breakout_window=5,
            attention_window=6,
            chase_window=5,
        )
    )

    signals = strategy.generate_signals(data)

    assert signals["trade_date"].tolist() == [pd.Timestamp("2026-01-14").date()]
    assert signals.iloc[0]["attention_reason"] == "strong_bar"
    assert {"trend_base", "range_breakout", "not_chasing"} <= set(signals.iloc[0]["reason"].split(";"))
    assert signals.iloc[0]["entry_date"] == pd.Timestamp("2026-01-15").date()


def test_st_security_never_emits_candidate_or_buy_signal():
    data = _bars(
        closes=[10, 10, 10, 10, 10, 10.7, 10.5, 10.4, 10.6, 11.0, 11.3],
        volumes=[100] * 5 + [220, 90, 90, 100, 160, 180],
        stock_name="*ST样本",
    )
    strategy = TwoStageTrendStrategy(
        TwoStageTrendStrategyConfig(
            ma10_window=3,
            ma20_window=4,
            ma60_window=5,
            volume_ma_window=3,
            breakout_window=5,
            attention_window=6,
            chase_window=5,
        )
    )

    assert strategy.build_candidates(data).empty
    assert strategy.generate_signals(data).empty


def test_each_attention_episode_emits_only_first_buy_signal():
    data = _bars(
        closes=[10, 10, 10, 10, 10, 10.7, 10.5, 10.4, 10.6, 11.0, 11.3, 11.5, 11.7],
        volumes=[100] * 5 + [220, 90, 90, 100, 100, 180, 170, 160],
    )
    strategy = TwoStageTrendStrategy(
        TwoStageTrendStrategyConfig(
            ma10_window=3,
            ma20_window=4,
            ma60_window=5,
            volume_ma_window=3,
            breakout_window=5,
            attention_window=10,
            chase_window=5,
        )
    )

    signals = strategy.generate_signals(data)

    assert len(signals) == 2
    assert not signals.duplicated(["stock_code", "watch_event_id"]).any()


def test_entry_quality_rejects_excess_volume_and_overextended_breakout():
    data = _bars(
        closes=[10, 10, 10, 10, 10, 10.7, 10.5, 10.4, 10.6, 11.0, 11.8],
        volumes=[100] * 5 + [220, 90, 90, 100, 450, 500],
    )
    strategy = TwoStageTrendStrategy(
        TwoStageTrendStrategyConfig(
            ma10_window=3,
            ma20_window=4,
            ma60_window=5,
            volume_ma_window=3,
            breakout_window=5,
            attention_window=6,
            chase_window=5,
            entry_volume_ratio_max=3.0,
            entry_breakout_pct_max=0.03,
        )
    )

    assert strategy.generate_signals(data).empty


def test_signal_score_is_finite_when_prior_volume_is_zero():
    data = _bars(
        closes=[10, 10, 10, 10, 10, 10.7, 10.5, 10.4, 10.6, 11.0, 11.2],
        volumes=[0, 0, 0, 0, 100, 220, 90, 90, 100, 160, 180],
    )
    strategy = TwoStageTrendStrategy(
        TwoStageTrendStrategyConfig(ma10_window=3, ma20_window=4, ma60_window=5, volume_ma_window=3, breakout_window=5, attention_window=6, chase_window=5)
    )

    signals = strategy.generate_signals(data)

    assert signals["score"].map(lambda value: value != float("inf")).all()
