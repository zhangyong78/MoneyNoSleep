from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd


DEFAULT_SCREENING_CACHE_PATH = r"data\cache\screening_cache.duckdb"
DEFAULT_KHQUANT_SOURCE_PATH = r"D:\khQuant\oskhquant\stock_screener\cache\market_data.duckdb"
DEFAULT_KHQUANT_CACHE_PATH = DEFAULT_SCREENING_CACHE_PATH

A_SHARE_PREFIXES = (
    "sh.600",
    "sh.601",
    "sh.603",
    "sh.605",
    "sh.688",
    "sz.000",
    "sz.001",
    "sz.002",
    "sz.003",
    "sz.300",
    "sz.301",
)


def bs_to_mns_code(code: str) -> str:
    lowered = str(code).lower()
    if lowered.startswith(("sh.", "sz.", "bj.")) and len(lowered) >= 9:
        return f"{lowered[3:9]}.{lowered[:2].upper()}"
    return str(code).upper()


def mns_to_bs_code(code: str) -> str:
    uppered = str(code).upper()
    if uppered.endswith((".SH", ".SZ", ".BJ")) and len(uppered) >= 9:
        return f"{uppered[-2:].lower()}.{uppered[:6]}"
    return str(code).lower()


@dataclass(frozen=True)
class KhQuantCacheInfo:
    latest_trade_date: str | None
    stock_count: int


SCREENING_CACHE_TABLES = {
    "daily_bars": """
        CREATE TABLE IF NOT EXISTS daily_bars (
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
    """,
    "stock_master": """
        CREATE TABLE IF NOT EXISTS stock_master (
            code VARCHAR,
            name VARCHAR,
            is_st BOOLEAN,
            last_seen DATE,
            updated_at TIMESTAMP
        )
    """,
    "forecast_reports": """
        CREATE TABLE IF NOT EXISTS forecast_reports (
            code VARCHAR,
            pub_date DATE,
            stat_date DATE,
            forecast_type VARCHAR,
            forecast_abstract VARCHAR,
            chg_pct_up DOUBLE,
            chg_pct_dwn DOUBLE,
            updated_at TIMESTAMP
        )
    """,
    "performance_express_reports": """
        CREATE TABLE IF NOT EXISTS performance_express_reports (
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
    """,
    "growth_reports": """
        CREATE TABLE IF NOT EXISTS growth_reports (
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
    """,
    "universe_members": """
        CREATE TABLE IF NOT EXISTS universe_members (
            universe VARCHAR,
            snapshot_date DATE,
            code VARCHAR,
            name VARCHAR
        )
    """,
}


def rebuild_screening_cache(
    *,
    target_path: str | Path = DEFAULT_SCREENING_CACHE_PATH,
    source_path: str | Path = DEFAULT_KHQUANT_SOURCE_PATH,
) -> dict[str, int | str]:
    source = Path(source_path)
    target = Path(target_path)
    if not source.exists():
        raise FileNotFoundError(f"screening cache source not found: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    src = duckdb.connect(str(source), read_only=True)
    dst = duckdb.connect(str(target))
    row_counts: dict[str, int | str] = {"target_path": str(target)}
    try:
        for table_name, create_sql in SCREENING_CACHE_TABLES.items():
            dst.execute(create_sql)
            dst.execute(f"DELETE FROM {table_name}")
            try:
                frame = src.execute(f"SELECT * FROM {table_name}").fetchdf()
            except Exception:
                frame = pd.DataFrame()
            if frame.empty:
                row_counts[table_name] = 0
                continue
            dst.register("incoming_df", frame)
            dst.execute(f"INSERT INTO {table_name} SELECT * FROM incoming_df")
            try:
                dst.unregister("incoming_df")
            except Exception:
                pass
            row_counts[table_name] = int(len(frame))
    finally:
        dst.close()
        src.close()
    return row_counts


class KhQuantCacheStore:
    def __init__(self, path: str | Path = DEFAULT_SCREENING_CACHE_PATH) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def connect(self):
        if not self.exists():
            raise FileNotFoundError(f"screening cache DB not found: {self.path}")
        return duckdb.connect(str(self.path), read_only=True)

    def ensure_local_cache(self, *, source_path: str | Path = DEFAULT_KHQUANT_SOURCE_PATH) -> dict[str, int | str] | None:
        if self.exists():
            return None
        return rebuild_screening_cache(target_path=self.path, source_path=source_path)

    def get_cache_info(self, *, exclude_st: bool = True) -> KhQuantCacheInfo:
        con = self.connect()
        try:
            latest = con.execute(
                """
                SELECT MAX(trade_date) AS latest_trade_date
                FROM daily_bars
                """
            ).fetchdf()
            latest_trade_date = latest.iloc[0]["latest_trade_date"]
            if pd.isna(latest_trade_date):
                return KhQuantCacheInfo(latest_trade_date=None, stock_count=0)

            stock_count = con.execute(
                f"""
                SELECT COUNT(DISTINCT b.code) AS stock_count
                FROM daily_bars AS b
                LEFT JOIN stock_master AS s ON s.code = b.code
                WHERE b.trade_date = ?
                  AND ({'COALESCE(s.is_st, FALSE) = FALSE AND' if exclude_st else ''} TRUE)
                  AND (
                    {" OR ".join([f"b.code LIKE '{prefix}%'" for prefix in A_SHARE_PREFIXES])}
                  )
                """,
                [latest_trade_date],
            ).fetchdf()
            return KhQuantCacheInfo(
                latest_trade_date=str(pd.Timestamp(latest_trade_date).date()),
                stock_count=int(stock_count.iloc[0]["stock_count"]),
            )
        finally:
            con.close()

    def resolve_signal_date(self, signal_date: str) -> str | None:
        con = self.connect()
        try:
            df = con.execute(
                """
                SELECT MAX(trade_date) AS trade_date
                FROM daily_bars
                WHERE trade_date <= ?
                """,
                [signal_date],
            ).fetchdf()
            value = df.iloc[0]["trade_date"]
            if pd.isna(value):
                return None
            return str(pd.Timestamp(value).date())
        finally:
            con.close()

    def load_universe(
        self,
        *,
        signal_date: str,
        universe: str = "all_a",
        exclude_st: bool = True,
    ) -> pd.DataFrame:
        con = self.connect()
        try:
            if universe == "all_a":
                query = f"""
                    SELECT DISTINCT b.code, COALESCE(s.name, b.code) AS name
                    FROM daily_bars AS b
                    LEFT JOIN stock_master AS s ON s.code = b.code
                    WHERE b.trade_date = ?
                      AND ({'COALESCE(s.is_st, FALSE) = FALSE AND' if exclude_st else ''} TRUE)
                      AND (
                        {" OR ".join([f"b.code LIKE '{prefix}%'" for prefix in A_SHARE_PREFIXES])}
                      )
                    ORDER BY b.code
                """
                return con.execute(query, [signal_date]).fetchdf()

            snapshot = con.execute(
                """
                SELECT MAX(snapshot_date) AS snapshot_date
                FROM universe_members
                WHERE universe = ? AND snapshot_date <= ?
                """,
                [universe, signal_date],
            ).fetchdf()
            snapshot_date = snapshot.iloc[0]["snapshot_date"]
            if pd.isna(snapshot_date):
                return pd.DataFrame(columns=["code", "name"])

            query = """
                SELECT u.code, COALESCE(s.name, u.name, u.code) AS name
                FROM universe_members AS u
                LEFT JOIN stock_master AS s ON s.code = u.code
                WHERE u.universe = ?
                  AND u.snapshot_date = ?
                  AND (? = FALSE OR COALESCE(s.is_st, FALSE) = FALSE)
                ORDER BY u.code
            """
            return con.execute(query, [universe, snapshot_date, exclude_st]).fetchdf()
        finally:
            con.close()

    def load_daily_history(self, *, codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        if not codes:
            return pd.DataFrame()

        codes_df = pd.DataFrame({"code": [mns_to_bs_code(code) for code in codes]})
        con = self.connect()
        try:
            con.register("codes_df", codes_df)
            frame = con.execute(
                """
                SELECT
                    b.code,
                    COALESCE(s.name, b.code) AS name,
                    b.trade_date AS date,
                    b.open,
                    b.high,
                    b.low,
                    b.close,
                    b.volume,
                    b.amount,
                    b.turn
                FROM daily_bars AS b
                INNER JOIN codes_df AS c ON c.code = b.code
                LEFT JOIN stock_master AS s ON s.code = b.code
                WHERE b.trade_date BETWEEN ? AND ?
                ORDER BY b.code, b.trade_date
                """,
                [start_date, end_date],
            ).fetchdf()
            if frame.empty:
                return frame
            frame["date"] = pd.to_datetime(frame["date"])
            frame["stock_code"] = frame["code"].map(bs_to_mns_code)
            frame["stock_name"] = frame["name"]
            return frame
        finally:
            try:
                con.unregister("codes_df")
            except Exception:
                pass
            con.close()

    def load_latest_earnings(self, *, codes: list[str], signal_date: str) -> pd.DataFrame:
        if not codes:
            return pd.DataFrame()

        codes_df = pd.DataFrame({"code": [mns_to_bs_code(code) for code in codes]})
        con = self.connect()
        try:
            con.register("codes_df", codes_df)

            forecast = con.execute(
                """
                WITH ranked AS (
                    SELECT
                        f.code,
                        f.pub_date AS forecast_pub_date,
                        f.stat_date AS forecast_stat_date,
                        f.forecast_type,
                        f.chg_pct_up AS forecast_chg_pct_up,
                        f.chg_pct_dwn AS forecast_chg_pct_dwn,
                        ROW_NUMBER() OVER (
                            PARTITION BY f.code
                            ORDER BY f.pub_date DESC, f.stat_date DESC
                        ) AS row_num
                    FROM forecast_reports AS f
                    INNER JOIN codes_df AS c ON c.code = f.code
                    WHERE f.pub_date <= ?
                )
                SELECT *
                FROM ranked
                WHERE row_num = 1
                """,
                [signal_date],
            ).fetchdf()

            express = con.execute(
                """
                WITH ranked AS (
                    SELECT
                        e.code,
                        e.pub_date AS express_pub_date,
                        e.stat_date AS express_stat_date,
                        e.gryoy AS express_gryoy,
                        e.opyoy AS express_opyoy,
                        ROW_NUMBER() OVER (
                            PARTITION BY e.code
                            ORDER BY e.pub_date DESC, e.stat_date DESC
                        ) AS row_num
                    FROM performance_express_reports AS e
                    INNER JOIN codes_df AS c ON c.code = e.code
                    WHERE e.pub_date <= ?
                )
                SELECT *
                FROM ranked
                WHERE row_num = 1
                """,
                [signal_date],
            ).fetchdf()

            growth = con.execute(
                """
                WITH ranked AS (
                    SELECT
                        g.code,
                        g.pub_date AS growth_pub_date,
                        g.stat_date AS growth_stat_date,
                        g.yoy_ni AS growth_yoy_ni,
                        ROW_NUMBER() OVER (
                            PARTITION BY g.code
                            ORDER BY g.pub_date DESC, g.stat_date DESC
                        ) AS row_num
                    FROM growth_reports AS g
                    INNER JOIN codes_df AS c ON c.code = g.code
                    WHERE g.pub_date <= ?
                )
                SELECT *
                FROM ranked
                WHERE row_num = 1
                """,
                [signal_date],
            ).fetchdf()
        finally:
            try:
                con.unregister("codes_df")
            except Exception:
                pass
            con.close()

        merged = codes_df.copy()
        merged = merged.merge(forecast, on="code", how="left")
        merged = merged.merge(express, on="code", how="left")
        merged = merged.merge(growth, on="code", how="left")
        merged["stock_code"] = merged["code"].map(bs_to_mns_code)
        return merged

    def load_earnings_history(self, *, codes: list[str], end_date: str) -> dict[str, pd.DataFrame]:
        if not codes:
            return {"forecast": pd.DataFrame(), "express": pd.DataFrame(), "growth": pd.DataFrame()}

        codes_df = pd.DataFrame({"code": [mns_to_bs_code(code) for code in codes]})
        con = self.connect()
        try:
            con.register("codes_df", codes_df)
            forecast = con.execute(
                """
                SELECT
                    f.code,
                    f.pub_date AS forecast_pub_date,
                    f.stat_date AS forecast_stat_date,
                    f.forecast_type,
                    f.chg_pct_up AS forecast_chg_pct_up,
                    f.chg_pct_dwn AS forecast_chg_pct_dwn
                FROM forecast_reports AS f
                INNER JOIN codes_df AS c ON c.code = f.code
                WHERE f.pub_date <= ?
                ORDER BY f.code, f.pub_date, f.stat_date
                """,
                [end_date],
            ).fetchdf()
            express = con.execute(
                """
                SELECT
                    e.code,
                    e.pub_date AS express_pub_date,
                    e.stat_date AS express_stat_date,
                    e.gryoy AS express_gryoy,
                    e.opyoy AS express_opyoy
                FROM performance_express_reports AS e
                INNER JOIN codes_df AS c ON c.code = e.code
                WHERE e.pub_date <= ?
                ORDER BY e.code, e.pub_date, e.stat_date
                """,
                [end_date],
            ).fetchdf()
            growth = con.execute(
                """
                SELECT
                    g.code,
                    g.pub_date AS growth_pub_date,
                    g.stat_date AS growth_stat_date,
                    g.yoy_ni AS growth_yoy_ni
                FROM growth_reports AS g
                INNER JOIN codes_df AS c ON c.code = g.code
                WHERE g.pub_date <= ?
                ORDER BY g.code, g.pub_date, g.stat_date
                """,
                [end_date],
            ).fetchdf()
        finally:
            try:
                con.unregister("codes_df")
            except Exception:
                pass
            con.close()

        for frame, date_columns in (
            (forecast, ("forecast_pub_date", "forecast_stat_date")),
            (express, ("express_pub_date", "express_stat_date")),
            (growth, ("growth_pub_date", "growth_stat_date")),
        ):
            if frame.empty:
                continue
            frame["stock_code"] = frame["code"].map(bs_to_mns_code)
            for column in date_columns:
                if column in frame.columns:
                    frame[column] = pd.to_datetime(frame[column], errors="coerce")

        return {
            "forecast": forecast,
            "express": express,
            "growth": growth,
        }
