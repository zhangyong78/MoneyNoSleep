from __future__ import annotations

from mns.pipelines.two_stage_trend_review import (
    clean_two_stage_daily_bars,
    code_batches,
    non_st_mns_codes,
    prepare_trade_actions,
    select_backtest_bars,
)


class _Cache:
    def __init__(self):
        self.signal_date = None

    def resolve_signal_date(self, signal_date):
        return "2026-01-02"

    def load_universe(self, **kwargs):
        import pandas as pd
        self.signal_date = kwargs["signal_date"]
        return pd.DataFrame({"code": ["sh.600000", "sh.600001"], "name": ["浦发银行", "ST样本"]})


def test_non_st_code_conversion_keeps_only_cache_filtered_codes():
    cache = _Cache()
    assert non_st_mns_codes(cache, "2026-01-05") == ["600000.SH", "600001.SH"]
    assert cache.signal_date == "2026-01-02"


def test_code_batches_bounds_each_market_data_request():
    assert list(code_batches(["a", "b", "c", "d", "e"], 2)) == [["a", "b"], ["c", "d"], ["e"]]


def test_select_backtest_bars_drops_rich_feature_columns():
    import pandas as pd
    frame = pd.DataFrame({"stock_code": ["a"], "trade_date": ["2026-01-01"], "bar_time": ["2026-01-01"], "open": [1.0], "close": [1.0], "atr14": [0.1], "is_suspended": [False], "limit_up_price": [1.1], "limit_down_price": [0.9], "unused_rich_factor": [99]})
    result = select_backtest_bars(frame, pd.Series(["a"]))
    assert "unused_rich_factor" not in result.columns
    assert {"stock_code", "open", "close", "atr14"} <= set(result.columns)


def test_prepare_trade_actions_matches_duckdb_positional_schema():
    import pandas as pd
    frame = pd.DataFrame([{"run_id": "r", "trade_id": "t", "stock_code": "x", "strategy_name": "s", "action": "BUY", "price": 1.0, "quantity": 100, "trade_time": "2026-01-01", "commission": 0.0, "tax": 0.0, "slippage": 0.0, "reason": "test"}])
    assert prepare_trade_actions(frame).columns.tolist()[:2] == ["trade_id", "run_id"]


def test_clean_daily_bars_removes_invalid_rows_and_marketwide_zero_volume_placeholder():
    import pandas as pd

    valid = [
        {"stock_code": "600000.SH", "trade_date": "2026-01-02", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "volume": 100.0, "amount": 1000.0},
        {"stock_code": "600000.SH", "trade_date": "2026-01-05", "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "volume": 100.0, "amount": 1000.0},
    ]
    invalid = [{"stock_code": "600001.SH", "trade_date": "2026-01-02", "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0.0, "amount": 0.0}]
    no_trade = [{"stock_code": "600002.SH", "trade_date": "2026-01-05", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 0.0, "amount": 0.0}]
    placeholder = [
        {"stock_code": f"60{index:04d}.SH", "trade_date": "2026-01-03", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 0.0, "amount": 0.0}
        for index in range(50)
    ]

    cleaned, stats = clean_two_stage_daily_bars(pd.DataFrame(valid + invalid + no_trade + placeholder))

    assert cleaned["trade_date"].astype(str).tolist() == ["2026-01-02", "2026-01-05"]
    assert stats == {"dropped_placeholder_rows": 50, "dropped_zero_activity_rows": 1, "dropped_invalid_ohlc_rows": 1}
