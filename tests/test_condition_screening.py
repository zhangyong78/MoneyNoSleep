from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from mns.data.khquant_cache import rebuild_screening_cache
from mns.data.duckdb_store import DuckDBStore
from mns.pipelines.condition_screening import (
    ConditionCombo1Config,
    ConditionCombo1Runner,
    ConditionGroupConfig,
    ConditionScreeningConfig,
    ConditionScreeningRunner,
    ConditionTimelineConfig,
    ConditionTimelineRunner,
)
from mns.pipelines.stock_feature_store import StockFeatureStoreBuilder, StockFeatureStoreConfig


def _build_khquant_cache(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute(
        """
        CREATE TABLE daily_bars (
            code VARCHAR,
            trade_date DATE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            amount DOUBLE,
            turn DOUBLE,
            pct_chg DOUBLE
        )
        """
    )
    con.execute(
        """
        CREATE TABLE stock_master (
            code VARCHAR,
            name VARCHAR,
            is_st BOOLEAN,
            last_seen DATE,
            updated_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE forecast_reports (
            code VARCHAR,
            pub_date DATE,
            stat_date DATE,
            forecast_type VARCHAR,
            forecast_abstract VARCHAR,
            chg_pct_up DOUBLE,
            chg_pct_dwn DOUBLE,
            updated_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE performance_express_reports (
            code VARCHAR,
            pub_date DATE,
            stat_date DATE,
            update_date DATE,
            total_asset DOUBLE,
            net_asset DOUBLE,
            eps_chg_pct DOUBLE,
            roe_wa DOUBLE,
            eps_diluted DOUBLE,
            gryoy DOUBLE,
            opyoy DOUBLE,
            updated_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE growth_reports (
            code VARCHAR,
            pub_date DATE,
            stat_date DATE,
            yoy_equity DOUBLE,
            yoy_asset DOUBLE,
            yoy_ni DOUBLE,
            yoy_eps_basic DOUBLE,
            yoy_pni DOUBLE,
            updated_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE universe_members (
            universe VARCHAR,
            snapshot_date DATE,
            code VARCHAR,
            name VARCHAR
        )
        """
    )

    dates = pd.bdate_range("2026-04-01", periods=35)
    rows: list[dict] = []
    for index, trade_date in enumerate(dates, start=1):
        close_a = 10.0 + index * 0.35
        volume_a = 1000.0 if index < 35 else 5000.0
        rows.append(
            {
                "code": "sh.600000",
                "trade_date": str(trade_date.date()),
                "open": close_a - 0.1,
                "high": close_a + 0.2,
                "low": close_a - 0.2,
                "close": close_a,
                "volume": volume_a,
                "amount": close_a * volume_a,
                "turn": 12.0,
                "pct_chg": 0.02,
            }
        )

        close_b = 20.0 + index * 0.03
        volume_b = 1200.0
        rows.append(
            {
                "code": "sz.000001",
                "trade_date": str(trade_date.date()),
                "open": close_b - 0.05,
                "high": close_b + 0.1,
                "low": close_b - 0.1,
                "close": close_b,
                "volume": volume_b,
                "amount": close_b * volume_b,
                "turn": 4.0,
                "pct_chg": 0.003,
            }
        )

    daily_bars = pd.DataFrame(rows)
    con.register("daily_bars_df", daily_bars)
    con.execute("INSERT INTO daily_bars SELECT * FROM daily_bars_df")

    stock_master = pd.DataFrame(
        [
            {"code": "sh.600000", "name": "娴﹀彂閾惰", "is_st": False, "last_seen": None, "updated_at": pd.Timestamp("2026-05-01")},
            {"code": "sz.000001", "name": "骞冲畨閾惰", "is_st": False, "last_seen": None, "updated_at": pd.Timestamp("2026-05-01")},
        ]
    )
    con.register("stock_master_df", stock_master)
    con.execute("INSERT INTO stock_master SELECT * FROM stock_master_df")

    forecast = pd.DataFrame(
        [
            {
                "code": "sh.600000",
                "pub_date": "2026-05-15",
                "stat_date": "2026-03-31",
                "forecast_type": "棰勫",
                "forecast_abstract": "娴嬭瘯",
                "chg_pct_up": 35.0,
                "chg_pct_dwn": 25.0,
                "updated_at": pd.Timestamp("2026-05-15"),
            },
            {
                "code": "sz.000001",
                "pub_date": "2026-05-15",
                "stat_date": "2026-03-31",
                "forecast_type": "鐣ュ",
                "forecast_abstract": "娴嬭瘯",
                "chg_pct_up": 12.0,
                "chg_pct_dwn": 8.0,
                "updated_at": pd.Timestamp("2026-05-15"),
            },
        ]
    )
    con.register("forecast_df", forecast)
    con.execute("INSERT INTO forecast_reports SELECT * FROM forecast_df")
    con.close()


def _build_local_screening_db(path: Path) -> None:
    store = DuckDBStore(path)
    store.initialize()

    dates = pd.bdate_range("2026-04-01", periods=35)
    rows: list[dict] = []
    for index, trade_date in enumerate(dates, start=1):
        close_a = 10.0 + index * 0.35
        volume_a = 1000.0 if index < 35 else 5000.0
        rows.append(
            {
                "stock_code": "600000.SH",
                "stock_name": "娴﹀彂閾惰",
                "exchange": "SH",
                "trade_date": str(trade_date.date()),
                "bar_time": pd.Timestamp(trade_date),
                "timeframe": "1d",
                "open": close_a - 0.1,
                "high": close_a + 0.2,
                "low": close_a - 0.2,
                "close": close_a,
                "volume": volume_a,
                "amount": close_a * volume_a,
                "turnover": 12.0,
                "pre_close": close_a - 0.2,
                "adj_factor": 1.0,
                "limit_up_price": None,
                "limit_down_price": None,
                "is_suspended": False,
                "source": "test",
                "updated_at": pd.Timestamp("2026-05-15 15:00:00"),
                "data_quality": "ok",
            }
        )

        close_b = 20.0 + index * 0.03
        rows.append(
            {
                "stock_code": "000001.SZ",
                "stock_name": "骞冲畨閾惰",
                "exchange": "SZ",
                "trade_date": str(trade_date.date()),
                "bar_time": pd.Timestamp(trade_date),
                "timeframe": "1d",
                "open": close_b - 0.05,
                "high": close_b + 0.1,
                "low": close_b - 0.1,
                "close": close_b,
                "volume": 1200.0,
                "amount": close_b * 1200.0,
                "turnover": 4.0,
                "pre_close": close_b - 0.05,
                "adj_factor": 1.0,
                "limit_up_price": None,
                "limit_down_price": None,
                "is_suspended": False,
                "source": "test",
                "updated_at": pd.Timestamp("2026-05-15 15:00:00"),
                "data_quality": "ok",
            }
        )
    store.replace_kline_bars(pd.DataFrame(rows))

    securities = pd.DataFrame(
        [
            {"stock_code": "600000.SH", "stock_name": "娴﹀彂閾惰", "exchange": "SH", "list_date": None, "delist_date": None, "is_st": False, "is_active": True},
            {"stock_code": "000001.SZ", "stock_name": "骞冲畨閾惰", "exchange": "SZ", "list_date": None, "delist_date": None, "is_st": False, "is_active": True},
        ]
    )
    con = store.connect()
    try:
        con.execute("DELETE FROM securities")
        con.register("securities_df", securities)
        con.execute("INSERT INTO securities SELECT * FROM securities_df")
    finally:
        con.close()


def _seed_sector_tables(path: Path, *, trade_dates: list[str]) -> None:
    store = DuckDBStore(path)
    store.initialize()
    sectors = pd.DataFrame(
        [
            {
                "sector_id": "qmt:industry:semi",
                "sector_name": "半导体",
                "canonical_sector_name": "半导体",
                "sector_type": "industry",
                "source": "qmt",
                "source_sector_code": "semi",
                "updated_at": pd.Timestamp("2026-05-19 15:00:00"),
            },
            {
                "sector_id": "qmt:industry:bank",
                "sector_name": "银行",
                "canonical_sector_name": "银行",
                "sector_type": "industry",
                "source": "qmt",
                "source_sector_code": "bank",
                "updated_at": pd.Timestamp("2026-05-19 15:00:00"),
            },
        ]
    )
    stock_sector_map = pd.DataFrame(
        [
            {
                "stock_code": "600000.SH",
                "stock_name": "浦发银行",
                "sector_id": "qmt:industry:semi",
                "sector_name": "半导体",
                "sector_type": "industry",
                "source": "qmt",
                "start_date": None,
                "end_date": None,
                "updated_at": pd.Timestamp("2026-05-19 15:00:00"),
            },
            {
                "stock_code": "000001.SZ",
                "stock_name": "平安银行",
                "sector_id": "qmt:industry:bank",
                "sector_name": "银行",
                "sector_type": "industry",
                "source": "qmt",
                "start_date": None,
                "end_date": None,
                "updated_at": pd.Timestamp("2026-05-19 15:00:00"),
            },
        ]
    )
    sector_strength = pd.DataFrame(
        [
            {
                "sector_id": "qmt:industry:semi",
                "sector_name": "半导体",
                "trade_date": trade_date,
                "timeframe": "1d",
                "strength_score": 0.82,
                "relative_return": 0.03,
                "three_bar_score": 0.03,
                "amount_score": 0.80,
                "limit_up_score": 0.75,
                "leader_score": 0.70,
                "rank": 3,
                "source": "qmt",
                "updated_at": pd.Timestamp("2026-05-19 15:00:00"),
            }
            for trade_date in trade_dates
        ]
        + [
            {
                "sector_id": "qmt:industry:bank",
                "sector_name": "银行",
                "trade_date": trade_date,
                "timeframe": "1d",
                "strength_score": 0.15,
                "relative_return": 0.005,
                "three_bar_score": 0.005,
                "amount_score": 0.20,
                "limit_up_score": 0.10,
                "leader_score": 0.05,
                "rank": 20,
                "source": "qmt",
                "updated_at": pd.Timestamp("2026-05-19 15:00:00"),
            }
            for trade_date in trade_dates
        ]
    )
    con = store.connect()
    try:
        con.execute("DELETE FROM sectors")
        con.execute("DELETE FROM stock_sector_map")
        con.execute("DELETE FROM sector_strength")
        con.register("sectors_df", sectors)
        con.register("stock_sector_map_df", stock_sector_map)
        con.register("sector_strength_df", sector_strength)
        con.execute("INSERT INTO sectors SELECT * FROM sectors_df")
        con.execute("INSERT INTO stock_sector_map SELECT * FROM stock_sector_map_df")
        con.execute("INSERT INTO sector_strength SELECT * FROM sector_strength_df")
    finally:
        con.close()


def _build_feature_case_db(path: Path) -> str:
    store = DuckDBStore(path)
    store.initialize()

    dates = pd.bdate_range("2026-01-05", periods=80)
    close_a = [20.0 - 0.15 * idx for idx in range(60)] + [11.0, 10.9, 10.8, 10.9, 11.0, 12.2, 11.5, 11.8, 12.2, 12.6, 12.8, 13.0, 13.2, 13.4, 13.8, 15.2, 15.4, 15.6, 15.8, 16.0]
    close_b = [8.0 + 0.02 * idx for idx in range(80)]
    amount_a = [2.2e8] * 80
    amount_b = [1.5e8] * 80
    amount_a[69] = 1.3e9
    for idx in range(70, 75):
        amount_a[idx] = 1.2e9

    rows: list[dict] = []
    for index, trade_date in enumerate(dates):
        for stock_code, stock_name, closes, amounts, turnover in [
            ("600010.SH", "特征样本A", close_a, amount_a, 8.0),
            ("000002.SZ", "特征样本B", close_b, amount_b, 5.0),
        ]:
            close = closes[index]
            pre_close = closes[index - 1] if index > 0 else close
            open_price = pre_close * 0.995 if index > 0 else close * 0.99
            high = max(open_price, close) * 1.01
            low = min(open_price, close) * 0.99
            limit_up_price = None

            if stock_code == "600010.SH" and index in {65, 75}:
                limit_up_price = close
            if stock_code == "600010.SH" and index in {71, 73}:
                high = max(open_price, close) * 1.08
            if stock_code == "600010.SH" and index in {72, 74}:
                low = min(open_price, close) * 0.90

            volume = amounts[index] / close
            rows.append(
                {
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "exchange": stock_code.split(".")[1],
                    "trade_date": str(trade_date.date()),
                    "bar_time": pd.Timestamp(trade_date),
                    "timeframe": "1d",
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amounts[index],
                    "turnover": turnover,
                    "pre_close": pre_close,
                    "adj_factor": 1.0,
                    "limit_up_price": limit_up_price,
                    "limit_down_price": None,
                    "is_suspended": False,
                    "source": "feature_test",
                    "updated_at": pd.Timestamp("2026-05-23 15:00:00"),
                    "data_quality": "ok",
                }
            )

    store.replace_kline_bars(pd.DataFrame(rows))
    securities = pd.DataFrame(
        [
            {"stock_code": "600010.SH", "stock_name": "特征样本A", "exchange": "SH", "list_date": None, "delist_date": None, "is_st": False, "is_active": True},
            {"stock_code": "000002.SZ", "stock_name": "特征样本B", "exchange": "SZ", "list_date": None, "delist_date": None, "is_st": False, "is_active": True},
        ]
    )
    con = store.connect()
    try:
        con.execute("DELETE FROM securities")
        con.register("securities_df", securities)
        con.execute("INSERT INTO securities SELECT * FROM securities_df")
    finally:
        con.close()
    return str(dates[-1].date())


def test_condition_combo1_runner_persists_hits(tmp_path):
    khquant_cache = tmp_path / "market_data.duckdb"
    db_path = tmp_path / "mns.duckdb"
    export_root = tmp_path / "exports"
    _build_khquant_cache(khquant_cache)
    _build_local_screening_db(db_path)

    runner = ConditionCombo1Runner(
        ConditionCombo1Config(
            db_path=str(db_path),
            khquant_cache_path=str(khquant_cache),
            export_root=str(export_root),
            signal_date="2026-05-19",
            ema_period=21,
            volume_ma_window=20,
            volume_ratio_min=3.0,
            daily_k_angle_window=5,
            daily_k_angle_min=40.0,
            relative_low_window=10,
            relative_low_position_max=0.30,
            enable_relative_low=False,
            earnings_forecast_change_min=20.0,
            earnings_yoy_min=10.0,
            price_max=50.0,
            turnover_min=12.0,
            hold_days=2,
        )
    )

    result = runner.run()

    assert result["summary"]["hit_count"] == 1
    assert result["hits"]["stock_code"].tolist() == ["600000.SH"]
    assert "量比" in result["hits"].iloc[0]["candidate_reason"]
    assert Path(result["export_path"]).exists()

    store = DuckDBStore(db_path)
    runs = store.list_screening_rule_runs()
    hits = store.get_screening_rule_hits(result["run_id"])
    assert runs.iloc[0]["run_id"] == result["run_id"]
    assert hits.iloc[0]["stock_code"] == "600000.SH"


def test_condition_screening_runner_supports_multiple_groups(tmp_path):
    khquant_cache = tmp_path / "market_data.duckdb"
    db_path = tmp_path / "mns.duckdb"
    _build_khquant_cache(khquant_cache)
    _build_local_screening_db(db_path)

    runner = ConditionScreeningRunner(
        ConditionScreeningConfig(
            db_path=str(db_path),
            khquant_cache_path=str(khquant_cache),
            signal_date="2026-05-19",
            combine_mode="all",
            groups=[
                ConditionGroupConfig(
                    name="缁勫悎1",
                    enable_volume_ratio=True,
                    volume_ratio_min=3.0,
                    enable_daily_k_angle=True,
                    daily_k_angle_min=40.0,
                    enable_relative_low=False,
                    enable_earnings_filter=True,
                    enable_turnover=True,
                    turnover_min=12.0,
                ),
                ConditionGroupConfig(
                    name="缁勫悎2",
                    enable_volume_ratio=False,
                    enable_daily_k_angle=False,
                    enable_relative_low=False,
                    enable_earnings_filter=True,
                    enable_price_max=True,
                    price_max=30.0,
                    enable_turnover=True,
                    turnover_min=12.0,
                ),
            ],
        )
    )

    result = runner.run()

    assert result["summary"]["hit_count"] == 1
    assert result["hits"].iloc[0]["matched_groups"] == "缁勫悎1;缁勫悎2"


def test_condition_screening_runner_supports_recent_amount_spike_filter(tmp_path):
    khquant_cache = tmp_path / "market_data.duckdb"
    db_path = tmp_path / "mns.duckdb"
    _build_khquant_cache(khquant_cache)
    _build_local_screening_db(db_path)

    runner = ConditionScreeningRunner(
        ConditionScreeningConfig(
            db_path=str(db_path),
            khquant_cache_path=str(khquant_cache),
            signal_date="2026-05-19",
            groups=[
                ConditionGroupConfig(
                    name="缁勫悎1",
                    enable_volume_ratio=False,
                    enable_daily_k_angle=False,
                    enable_relative_low=False,
                    enable_earnings_filter=False,
                    enable_price_max=False,
                    enable_turnover=False,
                    enable_recent_volume_spike=True,
                    recent_volume_spike_window=20,
                    recent_volume_spike_min=100000.0,
                )
            ],
        )
    )

    result = runner.run()

    assert result["summary"]["hit_count"] == 1
    assert result["hits"]["stock_code"].tolist() == ["600000.SH"]
    assert result["hits"].iloc[0]["recent_amount_max"] == 111250.0
    assert "最近20天内有一天成交额>=0.00亿" in result["hits"].iloc[0]["candidate_reason"]


def test_condition_screening_runner_supports_sector_strength_filter(tmp_path):
    khquant_cache = tmp_path / "market_data.duckdb"
    db_path = tmp_path / "mns.duckdb"
    _build_khquant_cache(khquant_cache)
    _build_local_screening_db(db_path)
    _seed_sector_tables(db_path, trade_dates=["2026-05-19"])

    runner = ConditionScreeningRunner(
        ConditionScreeningConfig(
            db_path=str(db_path),
            khquant_cache_path=str(khquant_cache),
            signal_date="2026-05-19",
            groups=[
                ConditionGroupConfig(
                    name="组合1",
                    enable_volume_ratio=False,
                    enable_daily_k_angle=False,
                    enable_relative_low=False,
                    enable_earnings_filter=False,
                    enable_price_max=False,
                    enable_turnover=False,
                    enable_sector_strength_filter=True,
                    sector_source="qmt",
                    sector_type="industry",
                    max_sector_rank=5,
                    min_sector_strength_score=0.50,
                    required_sector_name_keywords="半导体",
                )
            ],
        )
    )

    result = runner.run()

    assert result["summary"]["hit_count"] == 1
    assert result["hits"]["stock_code"].tolist() == ["600000.SH"]
    assert result["hits"].iloc[0]["primary_sector_name"] == "半导体"
    assert int(result["hits"].iloc[0]["sector_rank"]) == 3


def test_stock_feature_store_builder_generates_as_of_snapshots(tmp_path):
    db_path = tmp_path / "feature_case.duckdb"
    signal_date = _build_feature_case_db(db_path)

    result = StockFeatureStoreBuilder(
        StockFeatureStoreConfig(
            db_path=str(db_path),
            end_date=signal_date,
        )
    ).run()

    assert result["feature_rows"] > 0
    assert result["followup_rows"] > 0

    store = DuckDBStore(db_path)
    features = store.query_frame(
        """
        SELECT days_since_break_ma20, days_since_break_ma55, last_break_ma20_date, last_break_ma55_date
        FROM stock_daily_features
        WHERE stock_code = '600010.SH' AND trade_date = ?
        """,
        (signal_date,),
    )
    assert not features.empty
    assert int(features.iloc[0]["days_since_break_ma20"]) <= 20
    assert int(features.iloc[0]["days_since_break_ma55"]) <= 10
    assert pd.Timestamp(features.iloc[0]["last_break_ma55_date"]) >= pd.Timestamp(features.iloc[0]["last_break_ma20_date"])

    followups = store.query_frame(
        """
        SELECT available_date_5d, amount_sum_next_5d
        FROM stock_daily_followups
        WHERE stock_code = '600010.SH' AND anchor_date = '2026-04-10'
        """,
    )
    assert not followups.empty
    assert pd.notna(followups.iloc[0]["available_date_5d"])
    assert float(followups.iloc[0]["amount_sum_next_5d"]) > 5_000_000_000.0


def test_condition_screening_runner_supports_feature_store_conditions(tmp_path):
    db_path = tmp_path / "feature_case.duckdb"
    signal_date = _build_feature_case_db(db_path)

    result = ConditionScreeningRunner(
        ConditionScreeningConfig(
            db_path=str(db_path),
            signal_date=signal_date,
            groups=[
                ConditionGroupConfig(
                    name="组合1",
                    enable_volume_ratio=False,
                    enable_daily_k_angle=False,
                    enable_relative_low=False,
                    enable_earnings_filter=False,
                    enable_price_max=False,
                    enable_turnover=False,
                    enable_recent_volume_spike=True,
                    recent_volume_spike_window=20,
                    recent_volume_spike_min=1_000_000_000.0,
                    enable_limit_up_count=True,
                    limit_up_count_window=30,
                    limit_up_count_min=2,
                    enable_upper_shadow_count=True,
                    upper_shadow_window=30,
                    upper_shadow_threshold_pct=5.0,
                    upper_shadow_count_min=2,
                    enable_lower_shadow_count=True,
                    lower_shadow_window=30,
                    lower_shadow_threshold_pct=5.0,
                    lower_shadow_count_min=2,
                    enable_amount_followup=True,
                    amount_followup_lookback_window=30,
                    amount_followup_trigger_min=1_000_000_000.0,
                    amount_followup_sum_min=5_000_000_000.0,
                    amount_followup_days=5,
                    enable_breakout_sequence=True,
                    breakout_ma20_within_days=20,
                    breakout_ma55_within_days=10,
                )
            ],
        )
    ).run()

    assert result["summary"]["hit_count"] == 1
    assert result["hits"]["stock_code"].tolist() == ["600010.SH"]
    assert "涨停次数" in result["hits"].iloc[0]["candidate_reason"]
    assert "后5日成交额和" in result["hits"].iloc[0]["candidate_reason"]

def test_condition_timeline_runner_writes_timeline_hits(tmp_path):
    khquant_cache = tmp_path / "market_data.duckdb"
    db_path = tmp_path / "mns.duckdb"
    export_root = tmp_path / "exports"
    _build_khquant_cache(khquant_cache)
    _build_local_screening_db(db_path)

    runner = ConditionTimelineRunner(
        ConditionTimelineConfig(
            db_path=str(db_path),
            khquant_cache_path=str(khquant_cache),
            export_root=str(export_root),
            start_date="2026-05-15",
            end_date="2026-05-19",
            groups=[
                ConditionGroupConfig(
                    name="缁勫悎1",
                    enable_volume_ratio=False,
                    enable_daily_k_angle=True,
                    daily_k_angle_min=40.0,
                    enable_relative_low=False,
                    enable_earnings_filter=True,
                    enable_price_max=True,
                    price_max=50.0,
                    enable_turnover=True,
                    turnover_min=12.0,
                )
            ],
        )
    )

    result = runner.run()

    assert result["summary"]["hit_count"] >= 1
    assert result["summary"]["date_count"] >= 1
    assert Path(result["export_path"]).exists()

    store = DuckDBStore(db_path)
    timeline_runs = store.list_screening_timeline_runs()
    timeline_hits = store.get_screening_timeline_hits(result["run_id"])
    assert timeline_runs.iloc[0]["run_id"] == result["run_id"]
    assert not timeline_hits.empty


def test_condition_timeline_runner_supports_sector_strength_filter(tmp_path):
    khquant_cache = tmp_path / "market_data.duckdb"
    db_path = tmp_path / "mns.duckdb"
    _build_khquant_cache(khquant_cache)
    _build_local_screening_db(db_path)
    _seed_sector_tables(db_path, trade_dates=["2026-05-15", "2026-05-16", "2026-05-19"])

    runner = ConditionTimelineRunner(
        ConditionTimelineConfig(
            db_path=str(db_path),
            khquant_cache_path=str(khquant_cache),
            start_date="2026-05-15",
            end_date="2026-05-19",
            groups=[
                ConditionGroupConfig(
                    name="组合1",
                    enable_volume_ratio=False,
                    enable_daily_k_angle=False,
                    enable_relative_low=False,
                    enable_earnings_filter=False,
                    enable_price_max=False,
                    enable_turnover=False,
                    enable_sector_strength_filter=True,
                    sector_source="qmt",
                    sector_type="industry",
                    max_sector_rank=5,
                    min_sector_strength_score=0.50,
                    required_sector_name_keywords="半导体",
                )
            ],
        )
    )

    result = runner.run()

    assert result["summary"]["hit_count"] >= 1
    assert set(result["hits"]["primary_sector_name"].dropna().tolist()) == {"半导体"}


def test_rebuild_screening_cache_clones_source_tables(tmp_path):
    source_path = tmp_path / "source.duckdb"
    target_path = tmp_path / "target.duckdb"
    _build_khquant_cache(source_path)

    result = rebuild_screening_cache(target_path=target_path, source_path=source_path)

    assert target_path.exists()
    assert result["daily_bars"] > 0
    con = duckdb.connect(str(target_path), read_only=True)
    try:
        count = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        assert count == result["daily_bars"]
    finally:
        con.close()

