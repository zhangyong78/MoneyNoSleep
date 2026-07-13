from mns import __version__
from mns.data.duckdb_store import CORE_SCHEMA


def test_package_imports():
    assert __version__ == "0.1.0"


def test_core_schema_has_phase_one_tables():
    schema_text = "\n".join(CORE_SCHEMA)
    for table in [
        "screening_candidates",
        "kline_bars",
        "securities",
        "factor_values",
        "stock_daily_features",
        "stock_daily_followups",
        "signals",
        "trades",
        "backtest_runs",
        "portfolio_snapshots",
        "trade_reviews",
        "trade_screenshots",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema_text
