from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from mns.data.timeframes import normalize_timeframe, timeframe_aliases


CORE_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS screening_candidates (
        run_id TEXT,
        stock_code TEXT,
        stock_name TEXT,
        trade_date DATE,
        bar_time TIMESTAMP,
        timeframe TEXT,
        close DOUBLE,
        score DOUBLE,
        candidate_reason TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kline_bars (
        stock_code TEXT,
        stock_name TEXT,
        exchange TEXT,
        trade_date DATE,
        bar_time TIMESTAMP,
        timeframe TEXT,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        close DOUBLE,
        volume DOUBLE,
        amount DOUBLE,
        turnover DOUBLE,
        pre_close DOUBLE,
        adj_factor DOUBLE,
        limit_up_price DOUBLE,
        limit_down_price DOUBLE,
        is_suspended BOOLEAN,
        source TEXT,
        updated_at TIMESTAMP,
        data_quality TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS securities (
        stock_code TEXT PRIMARY KEY,
        stock_name TEXT,
        exchange TEXT,
        list_date DATE,
        delist_date DATE,
        is_st BOOLEAN,
        is_active BOOLEAN
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS factor_values (
        stock_code TEXT,
        factor_name TEXT,
        timeframe TEXT,
        calc_time TIMESTAMP,
        value DOUBLE,
        source TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_daily_features (
        stock_code TEXT,
        stock_name TEXT,
        trade_date DATE,
        bar_time TIMESTAMP,
        timeframe TEXT,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        close DOUBLE,
        volume DOUBLE,
        amount DOUBLE,
        turnover DOUBLE,
        pre_close DOUBLE,
        pct_chg DOUBLE,
        upper_shadow_pct DOUBLE,
        lower_shadow_pct DOUBLE,
        body_pct DOUBLE,
        amplitude_pct DOUBLE,
        ma20 DOUBLE,
        ma55 DOUBLE,
        ma120 DOUBLE,
        break_ma20_today BOOLEAN,
        break_ma55_today BOOLEAN,
        last_break_ma20_date DATE,
        last_break_ma55_date DATE,
        days_since_break_ma20 INTEGER,
        days_since_break_ma55 INTEGER,
        limit_up BOOLEAN,
        limit_down BOOLEAN,
        created_time TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_daily_followups (
        stock_code TEXT,
        stock_name TEXT,
        anchor_date DATE,
        timeframe TEXT,
        available_date_5d DATE,
        amount_sum_next_5d DOUBLE,
        return_next_5d DOUBLE,
        max_return_next_5d DOUBLE,
        limit_up_count_next_5d INTEGER,
        created_time TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS signals (
        run_id TEXT,
        signal_id TEXT,
        stock_code TEXT,
        strategy_name TEXT,
        action TEXT,
        timeframe TEXT,
        signal_time TIMESTAMP,
        entry_price DOUBLE,
        stop_loss DOUBLE,
        take_profit DOUBLE,
        score DOUBLE,
        reason TEXT,
        status TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        trade_id TEXT,
        run_id TEXT,
        stock_code TEXT,
        strategy_name TEXT,
        action TEXT,
        price DOUBLE,
        quantity INTEGER,
        trade_time TIMESTAMP,
        commission DOUBLE,
        tax DOUBLE,
        slippage DOUBLE,
        reason TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_runs (
        run_id TEXT PRIMARY KEY,
        run_type TEXT,
        start_date DATE,
        end_date DATE,
        initial_cash DOUBLE,
        config_json TEXT,
        result_json TEXT,
        created_time TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        run_id TEXT,
        snapshot_time TIMESTAMP,
        total_equity DOUBLE,
        cash DOUBLE,
        available_cash DOUBLE,
        market_value DOUBLE,
        daily_pnl DOUBLE,
        cumulative_return DOUBLE,
        drawdown DOUBLE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trade_reviews (
        review_id TEXT,
        trade_id TEXT,
        run_id TEXT,
        stock_code TEXT,
        review_status TEXT,
        buy_point_rating TEXT,
        sell_point_rating TEXT,
        risk_control_rating TEXT,
        market_context_rating TEXT,
        sector_context_rating TEXT,
        manual_note TEXT,
        problem_tags TEXT,
        screenshot_path TEXT,
        reviewed_by TEXT,
        review_time TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trade_screenshots (
        screenshot_id TEXT,
        trade_id TEXT,
        run_id TEXT,
        stock_code TEXT,
        image_path TEXT,
        chart_timeframe TEXT,
        start_time TIMESTAMP,
        end_time TIMESTAMP,
        created_time TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS screening_rule_runs (
        run_id TEXT PRIMARY KEY,
        screening_date DATE,
        strategy_name TEXT,
        universe TEXT,
        timeframe TEXT,
        rule_json TEXT,
        result_json TEXT,
        created_time TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS screening_rule_hits (
        run_id TEXT,
        stock_code TEXT,
        stock_name TEXT,
        trade_date DATE,
        bar_time TIMESTAMP,
        timeframe TEXT,
        close DOUBLE,
        score DOUBLE,
        candidate_reason TEXT,
        hit_groups TEXT,
        payload_json TEXT,
        created_time TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS screening_timeline_runs (
        run_id TEXT PRIMARY KEY,
        start_date DATE,
        end_date DATE,
        strategy_name TEXT,
        universe TEXT,
        timeframe TEXT,
        rule_json TEXT,
        result_json TEXT,
        created_time TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS screening_timeline_hits (
        run_id TEXT,
        stock_code TEXT,
        stock_name TEXT,
        trade_date DATE,
        bar_time TIMESTAMP,
        timeframe TEXT,
        close DOUBLE,
        score DOUBLE,
        candidate_reason TEXT,
        hit_groups TEXT,
        payload_json TEXT,
        created_time TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sectors (
        sector_id TEXT,
        sector_name TEXT,
        canonical_sector_name TEXT,
        sector_type TEXT,
        source TEXT,
        source_sector_code TEXT,
        updated_at TIMESTAMP,
        PRIMARY KEY (sector_id, source)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_sector_map (
        stock_code TEXT,
        stock_name TEXT,
        sector_id TEXT,
        sector_name TEXT,
        sector_type TEXT,
        source TEXT,
        start_date DATE,
        end_date DATE,
        updated_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_daily (
        sector_id TEXT,
        sector_name TEXT,
        trade_date DATE,
        timeframe TEXT,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        close DOUBLE,
        pct_change DOUBLE,
        amount DOUBLE,
        volume DOUBLE,
        turnover_rate DOUBLE,
        up_num INTEGER,
        down_num INTEGER,
        flat_num INTEGER,
        limit_up_num INTEGER,
        limit_down_num INTEGER,
        leading_stock TEXT,
        leading_stock_pct DOUBLE,
        source TEXT,
        updated_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_strength (
        sector_id TEXT,
        sector_name TEXT,
        trade_date DATE,
        timeframe TEXT,
        strength_score DOUBLE,
        relative_return DOUBLE,
        three_bar_score DOUBLE,
        amount_score DOUBLE,
        limit_up_score DOUBLE,
        leader_score DOUBLE,
        rank INTEGER,
        source TEXT,
        updated_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_leaders (
        sector_id TEXT,
        sector_name TEXT,
        trade_date DATE,
        stock_code TEXT,
        stock_name TEXT,
        leader_type TEXT,
        leader_score DOUBLE,
        pct_change DOUBLE,
        amount DOUBLE,
        turnover_rate DOUBLE,
        reason TEXT,
        updated_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_name_alias (
        alias_name TEXT,
        canonical_name TEXT,
        source TEXT,
        updated_at TIMESTAMP
    )
    """,
]


class DuckDBStore:
    def __init__(self, path: str | Path = "data/duckdb/mns.duckdb") -> None:
        self.path = Path(path)

    def connect(self):
        try:
            import duckdb
        except ModuleNotFoundError as exc:
            raise RuntimeError("duckdb is required for DuckDBStore. Run `pip install -e .`.") from exc

        self.path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(self.path))

    def initialize(self) -> None:
        con = self.connect()
        try:
            for statement in CORE_SCHEMA:
                con.execute(statement)
            self._run_migrations(con)
        finally:
            con.close()

    @staticmethod
    def _run_migrations(con) -> None:
        try:
            con.execute("ALTER TABLE signals ADD COLUMN run_id TEXT")
        except Exception as exc:
            if "already exists" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                raise

        DuckDBStore._migrate_hourly_timeframe_aliases(con)

    @staticmethod
    def _migrate_hourly_timeframe_aliases(con) -> None:
        legacy_count = con.execute("SELECT COUNT(*) FROM kline_bars WHERE timeframe = '60m'").fetchone()[0]
        if legacy_count:
            con.execute(
                """
                CREATE OR REPLACE TEMP TABLE _mns_hourly_kline AS
                SELECT
                    stock_code,
                    stock_name,
                    exchange,
                    trade_date,
                    bar_time,
                    '1h' AS timeframe,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    amount,
                    turnover,
                    pre_close,
                    adj_factor,
                    limit_up_price,
                    limit_down_price,
                    is_suspended,
                    source,
                    updated_at,
                    data_quality
                FROM (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY stock_code, bar_time
                               ORDER BY CASE WHEN timeframe = '60m' THEN 0 ELSE 1 END, updated_at DESC
                           ) AS row_num
                    FROM kline_bars
                    WHERE timeframe IN ('1h', '60m')
                ) ranked
                WHERE row_num = 1
                """
            )
            con.execute("DELETE FROM kline_bars WHERE timeframe IN ('1h', '60m')")
            con.execute("INSERT INTO kline_bars SELECT * FROM _mns_hourly_kline")
            con.execute("DROP TABLE _mns_hourly_kline")

        for table_name, column_name in (
            ("screening_candidates", "timeframe"),
            ("factor_values", "timeframe"),
            ("stock_daily_features", "timeframe"),
            ("stock_daily_followups", "timeframe"),
            ("signals", "timeframe"),
            ("screening_rule_runs", "timeframe"),
            ("screening_rule_hits", "timeframe"),
            ("screening_timeline_runs", "timeframe"),
            ("screening_timeline_hits", "timeframe"),
            ("trade_screenshots", "chart_timeframe"),
        ):
            try:
                con.execute(f"UPDATE {table_name} SET {column_name} = '1h' WHERE {column_name} = '60m'")
            except Exception:
                continue

    def insert_frame(self, table_name: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        con = self.connect()
        try:
            con.register("incoming_df", df)
            con.execute(f"INSERT INTO {table_name} SELECT * FROM incoming_df")
        finally:
            con.close()

    def replace_kline_bars(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0

        required = {"stock_code", "trade_date", "timeframe"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"missing kline columns for replace: {sorted(missing)}")

        prepared = df.copy()
        prepared["timeframe"] = prepared["timeframe"].map(normalize_timeframe)
        prepared = prepared.drop_duplicates(subset=["stock_code", "bar_time", "timeframe"], keep="last").reset_index(drop=True)
        delete_keys = prepared[["stock_code", "timeframe", "trade_date"]].drop_duplicates().copy()

        con = self.connect()
        try:
            con.register("delete_keys", delete_keys)
            con.register("incoming_df", prepared)
            con.execute(
                """
                DELETE FROM kline_bars
                USING delete_keys
                WHERE kline_bars.stock_code = delete_keys.stock_code
                  AND kline_bars.timeframe = delete_keys.timeframe
                  AND kline_bars.trade_date = delete_keys.trade_date
                """
            )
            con.execute("INSERT INTO kline_bars SELECT * FROM incoming_df")
        finally:
            con.close()
        return len(prepared)

    def query_frame(self, sql: str, params: tuple | None = None) -> pd.DataFrame:
        con = self.connect()
        try:
            return con.execute(sql, params or ()).fetchdf()
        finally:
            con.close()

    def replace_stock_daily_features(self, df: pd.DataFrame) -> int:
        self.initialize()
        if df.empty:
            return 0

        required = {"stock_code", "trade_date", "timeframe"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"missing stock_daily_features columns for replace: {sorted(missing)}")

        delete_keys = df[["stock_code", "trade_date", "timeframe"]].drop_duplicates().copy()
        con = self.connect()
        try:
            con.register("delete_keys", delete_keys)
            con.register("incoming_df", df)
            con.execute(
                """
                DELETE FROM stock_daily_features
                USING delete_keys
                WHERE stock_daily_features.stock_code = delete_keys.stock_code
                  AND stock_daily_features.trade_date = delete_keys.trade_date
                  AND stock_daily_features.timeframe = delete_keys.timeframe
                """
            )
            con.execute("INSERT INTO stock_daily_features SELECT * FROM incoming_df")
        finally:
            con.close()
        return len(df)

    def replace_stock_daily_followups(self, df: pd.DataFrame) -> int:
        self.initialize()
        if df.empty:
            return 0

        required = {"stock_code", "anchor_date", "timeframe"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"missing stock_daily_followups columns for replace: {sorted(missing)}")

        delete_keys = df[["stock_code", "anchor_date", "timeframe"]].drop_duplicates().copy()
        con = self.connect()
        try:
            con.register("delete_keys", delete_keys)
            con.register("incoming_df", df)
            con.execute(
                """
                DELETE FROM stock_daily_followups
                USING delete_keys
                WHERE stock_daily_followups.stock_code = delete_keys.stock_code
                  AND stock_daily_followups.anchor_date = delete_keys.anchor_date
                  AND stock_daily_followups.timeframe = delete_keys.timeframe
                """
            )
            con.execute("INSERT INTO stock_daily_followups SELECT * FROM incoming_df")
        finally:
            con.close()
        return len(df)

    def get_latest_trade_dates(self, *, stock_codes: list[str], timeframe: str) -> pd.DataFrame:
        if not stock_codes:
            return pd.DataFrame(columns=["stock_code", "latest_trade_date"])
        aliases = list(timeframe_aliases(timeframe))
        return self.query_frame(
            """
            SELECT stock_code, MAX(trade_date) AS latest_trade_date
            FROM kline_bars
            WHERE timeframe IN (SELECT UNNEST(?))
              AND stock_code IN (SELECT UNNEST(?))
            GROUP BY stock_code
            """,
            (aliases, stock_codes),
        )

    def replace_backtest_run(
        self,
        *,
        run_id: str,
        run_type: str,
        start_date: str | None,
        end_date: str | None,
        initial_cash: float,
        config: dict,
        result: dict,
    ) -> None:
        self.initialize()
        record = pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "run_type": run_type,
                    "start_date": start_date,
                    "end_date": end_date,
                    "initial_cash": initial_cash,
                    "config_json": json.dumps(config, ensure_ascii=True, sort_keys=True),
                    "result_json": json.dumps(result, ensure_ascii=True, sort_keys=True),
                    "created_time": pd.Timestamp.utcnow().tz_localize(None),
                }
            ]
        )
        con = self.connect()
        try:
            con.execute("DELETE FROM backtest_runs WHERE run_id = ?", (run_id,))
            con.register("incoming_df", record)
            con.execute("INSERT INTO backtest_runs SELECT * FROM incoming_df")
        finally:
            con.close()

    def replace_trades_for_run(self, run_id: str, trades: pd.DataFrame) -> int:
        self.initialize()
        con = self.connect()
        try:
            con.execute("DELETE FROM trades WHERE run_id = ?", (run_id,))
            if trades.empty:
                return 0
            con.register("incoming_df", trades)
            con.execute("INSERT INTO trades SELECT * FROM incoming_df")
        finally:
            con.close()
        return len(trades)

    def replace_signals_for_run(self, run_id: str, signals: pd.DataFrame) -> int:
        self.initialize()
        columns = [
            "run_id",
            "signal_id",
            "stock_code",
            "strategy_name",
            "action",
            "timeframe",
            "signal_time",
            "entry_price",
            "stop_loss",
            "take_profit",
            "score",
            "reason",
            "status",
        ]
        con = self.connect()
        try:
            con.execute("DELETE FROM signals WHERE run_id = ?", (run_id,))
            if signals.empty:
                return 0
            prepared = signals.copy()
            prepared["run_id"] = run_id
            if "signal_id" not in prepared.columns:
                prepared["signal_id"] = [
                    f"{run_id}_sig_{idx + 1:04d}" for idx in range(len(prepared))
                ]
            for column in columns:
                if column not in prepared.columns:
                    prepared[column] = None
            prepared = prepared[columns]
            con.register("incoming_df", prepared)
            con.execute(
                """
                INSERT INTO signals (
                    run_id, signal_id, stock_code, strategy_name, action, timeframe,
                    signal_time, entry_price, stop_loss, take_profit, score, reason, status
                )
                SELECT
                    run_id, signal_id, stock_code, strategy_name, action, timeframe,
                    signal_time, entry_price, stop_loss, take_profit, score, reason, status
                FROM incoming_df
                """
            )
        finally:
            con.close()
        return len(signals)

    def replace_candidates_for_run(self, run_id: str, candidates: pd.DataFrame) -> int:
        self.initialize()
        columns = [
            "run_id",
            "stock_code",
            "stock_name",
            "trade_date",
            "bar_time",
            "timeframe",
            "close",
            "score",
            "candidate_reason",
        ]
        con = self.connect()
        try:
            con.execute("DELETE FROM screening_candidates WHERE run_id = ?", (run_id,))
            if candidates.empty:
                return 0
            prepared = candidates.copy()
            prepared["run_id"] = run_id
            for column in columns:
                if column not in prepared.columns:
                    prepared[column] = None
            prepared = prepared[columns]
            con.register("incoming_df", prepared)
            con.execute("INSERT INTO screening_candidates SELECT * FROM incoming_df")
        finally:
            con.close()
        return len(candidates)

    def replace_portfolio_snapshots_for_run(self, run_id: str, snapshots: pd.DataFrame) -> int:
        self.initialize()
        con = self.connect()
        try:
            con.execute("DELETE FROM portfolio_snapshots WHERE run_id = ?", (run_id,))
            if snapshots.empty:
                return 0
            con.register("incoming_df", snapshots)
            con.execute("INSERT INTO portfolio_snapshots SELECT * FROM incoming_df")
        finally:
            con.close()
        return len(snapshots)

    def list_backtest_runs(self, limit: int = 50) -> pd.DataFrame:
        return self.query_frame(
            """
            SELECT run_id, run_type, start_date, end_date, initial_cash, config_json, result_json, created_time
            FROM backtest_runs
            ORDER BY created_time DESC
            LIMIT ?
            """,
            (limit,),
        )

    def get_run_trades(self, run_id: str) -> pd.DataFrame:
        return self.query_frame(
            """
            SELECT *
            FROM trades
            WHERE run_id = ?
            ORDER BY trade_time, trade_id, action
            """,
            (run_id,),
        )

    def get_run_signals(self, run_id: str) -> pd.DataFrame:
        return self.query_frame(
            """
            SELECT *
            FROM signals
            WHERE run_id = ?
            ORDER BY signal_time, signal_id
            """,
            (run_id,),
        )

    def get_run_candidates(self, run_id: str) -> pd.DataFrame:
        return self.query_frame(
            """
            SELECT *
            FROM screening_candidates
            WHERE run_id = ?
            ORDER BY score DESC, stock_code
            """,
            (run_id,),
        )

    def get_run_portfolio_snapshots(self, run_id: str) -> pd.DataFrame:
        return self.query_frame(
            """
            SELECT *
            FROM portfolio_snapshots
            WHERE run_id = ?
            ORDER BY snapshot_time
            """,
            (run_id,),
        )

    def replace_trade_review(self, review: dict) -> None:
        self.initialize()
        columns = [
            "review_id",
            "trade_id",
            "run_id",
            "stock_code",
            "review_status",
            "buy_point_rating",
            "sell_point_rating",
            "risk_control_rating",
            "market_context_rating",
            "sector_context_rating",
            "manual_note",
            "problem_tags",
            "screenshot_path",
            "reviewed_by",
            "review_time",
        ]
        record = pd.DataFrame([review]).reindex(columns=columns)
        con = self.connect()
        try:
            con.execute(
                "DELETE FROM trade_reviews WHERE run_id = ? AND trade_id = ?",
                (review["run_id"], review["trade_id"]),
            )
            con.register("incoming_df", record)
            con.execute("INSERT INTO trade_reviews SELECT * FROM incoming_df")
        finally:
            con.close()

    def get_run_trade_reviews(self, run_id: str) -> pd.DataFrame:
        return self.query_frame(
            """
            SELECT *
            FROM trade_reviews
            WHERE run_id = ?
            ORDER BY review_time DESC
            """,
            (run_id,),
        )

    def replace_trade_screenshot(self, screenshot: dict) -> None:
        self.initialize()
        columns = [
            "screenshot_id",
            "trade_id",
            "run_id",
            "stock_code",
            "image_path",
            "chart_timeframe",
            "start_time",
            "end_time",
            "created_time",
        ]
        record = pd.DataFrame([screenshot]).reindex(columns=columns)
        con = self.connect()
        try:
            con.execute(
                "DELETE FROM trade_screenshots WHERE run_id = ? AND trade_id = ? AND image_path = ?",
                (screenshot["run_id"], screenshot["trade_id"], screenshot["image_path"]),
            )
            con.register("incoming_df", record)
            con.execute("INSERT INTO trade_screenshots SELECT * FROM incoming_df")
        finally:
            con.close()

    def get_run_trade_screenshots(self, run_id: str) -> pd.DataFrame:
        return self.query_frame(
            """
            SELECT *
            FROM trade_screenshots
            WHERE run_id = ?
            ORDER BY created_time DESC
            """,
            (run_id,),
        )

    def replace_screening_rule_run(
        self,
        *,
        run_id: str,
        screening_date: str,
        strategy_name: str,
        universe: str,
        timeframe: str,
        config: dict,
        result: dict,
    ) -> None:
        self.initialize()
        record = pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "screening_date": screening_date,
                    "strategy_name": strategy_name,
                    "universe": universe,
                    "timeframe": timeframe,
                    "rule_json": json.dumps(config, ensure_ascii=True, sort_keys=True),
                    "result_json": json.dumps(result, ensure_ascii=True, sort_keys=True),
                    "created_time": pd.Timestamp.utcnow().tz_localize(None),
                }
            ]
        )
        con = self.connect()
        try:
            con.execute("DELETE FROM screening_rule_runs WHERE run_id = ?", (run_id,))
            con.register("incoming_df", record)
            con.execute("INSERT INTO screening_rule_runs SELECT * FROM incoming_df")
        finally:
            con.close()

    def replace_screening_rule_hits(self, run_id: str, hits: pd.DataFrame) -> int:
        self.initialize()
        columns = [
            "run_id",
            "stock_code",
            "stock_name",
            "trade_date",
            "bar_time",
            "timeframe",
            "close",
            "score",
            "candidate_reason",
            "hit_groups",
            "payload_json",
            "created_time",
        ]
        con = self.connect()
        try:
            con.execute("DELETE FROM screening_rule_hits WHERE run_id = ?", (run_id,))
            if hits.empty:
                return 0
            prepared = hits.copy()
            prepared["run_id"] = run_id
            prepared["hit_groups"] = prepared.get("matched_groups", prepared.get("group_name"))
            prepared["payload_json"] = prepared.apply(
                lambda row: json.dumps(row.to_dict(), ensure_ascii=True, default=str, sort_keys=True),
                axis=1,
            )
            prepared["created_time"] = pd.Timestamp.utcnow().tz_localize(None)
            for column in columns:
                if column not in prepared.columns:
                    prepared[column] = None
            prepared = prepared[columns]
            con.register("incoming_df", prepared)
            con.execute("INSERT INTO screening_rule_hits SELECT * FROM incoming_df")
        finally:
            con.close()
        return len(hits)

    def list_screening_rule_runs(self, limit: int = 50) -> pd.DataFrame:
        return self.query_frame(
            """
            SELECT run_id, screening_date, strategy_name, universe, timeframe, rule_json, result_json, created_time
            FROM screening_rule_runs
            ORDER BY created_time DESC
            LIMIT ?
            """,
            (limit,),
        )

    def get_screening_rule_hits(self, run_id: str) -> pd.DataFrame:
        return self.query_frame(
            """
            SELECT *
            FROM screening_rule_hits
            WHERE run_id = ?
            ORDER BY score DESC, stock_code
            """,
            (run_id,),
        )

    def replace_screening_timeline_run(
        self,
        *,
        run_id: str,
        start_date: str,
        end_date: str,
        strategy_name: str,
        universe: str,
        timeframe: str,
        config: dict,
        result: dict,
    ) -> None:
        self.initialize()
        record = pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "strategy_name": strategy_name,
                    "universe": universe,
                    "timeframe": timeframe,
                    "rule_json": json.dumps(config, ensure_ascii=True, sort_keys=True),
                    "result_json": json.dumps(result, ensure_ascii=True, sort_keys=True),
                    "created_time": pd.Timestamp.utcnow().tz_localize(None),
                }
            ]
        )
        con = self.connect()
        try:
            con.execute("DELETE FROM screening_timeline_runs WHERE run_id = ?", (run_id,))
            con.register("incoming_df", record)
            con.execute("INSERT INTO screening_timeline_runs SELECT * FROM incoming_df")
        finally:
            con.close()

    def replace_screening_timeline_hits(self, run_id: str, hits: pd.DataFrame) -> int:
        self.initialize()
        columns = [
            "run_id",
            "stock_code",
            "stock_name",
            "trade_date",
            "bar_time",
            "timeframe",
            "close",
            "score",
            "candidate_reason",
            "hit_groups",
            "payload_json",
            "created_time",
        ]
        con = self.connect()
        try:
            con.execute("DELETE FROM screening_timeline_hits WHERE run_id = ?", (run_id,))
            if hits.empty:
                return 0
            prepared = hits.copy()
            prepared["run_id"] = run_id
            prepared["payload_json"] = prepared.apply(
                lambda row: json.dumps(row.to_dict(), ensure_ascii=True, default=str, sort_keys=True),
                axis=1,
            )
            prepared["created_time"] = pd.Timestamp.utcnow().tz_localize(None)
            prepared["hit_groups"] = prepared.get("matched_groups", prepared.get("group_name"))
            for column in columns:
                if column not in prepared.columns:
                    prepared[column] = None
            prepared = prepared[columns]
            con.register("incoming_df", prepared)
            con.execute("INSERT INTO screening_timeline_hits SELECT * FROM incoming_df")
        finally:
            con.close()
        return len(hits)

    def list_screening_timeline_runs(self, limit: int = 50) -> pd.DataFrame:
        return self.query_frame(
            """
            SELECT run_id, start_date, end_date, strategy_name, universe, timeframe, rule_json, result_json, created_time
            FROM screening_timeline_runs
            ORDER BY created_time DESC
            LIMIT ?
            """,
            (limit,),
        )

    def get_screening_timeline_hits(self, run_id: str) -> pd.DataFrame:
        return self.query_frame(
            """
            SELECT *
            FROM screening_timeline_hits
            WHERE run_id = ?
            ORDER BY trade_date, score DESC, stock_code
            """,
            (run_id,),
        )
