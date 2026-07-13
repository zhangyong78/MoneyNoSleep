from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from mns.backtest.ema_cross import EmaCrossBacktestConfig, EmaCrossBacktestRunner
from mns.data.duckdb_store import DuckDBStore
from mns.data.local_data import LocalMarketData
from mns.pipelines.daily_trend_following_review import (
    DailyTrendFollowingReviewConfig,
    DailyTrendFollowingReviewRunner,
)


@dataclass(frozen=True)
class BacktestStrategySpec:
    strategy_id: str
    display_name: str
    default_timeframe: str
    description: str


@dataclass(frozen=True)
class QtBacktestRequest:
    db_path: str = "data/duckdb/mns.duckdb"
    strategy_id: str = "daily_trend_following"
    timeframe: str = "1d"
    start_date: str | None = None
    end_date: str | None = None
    stock_codes: list[str] | None = None
    initial_cash: float = 1_000_000
    commission_rate: float = 0.0005
    stamp_tax_rate: float = 0.001
    transfer_fee_rate: float = 0.0
    slippage_rate: float = 0.001
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QtBacktestResult:
    run_id: str
    strategy_id: str
    summary: dict[str, float | int]
    kline: pd.DataFrame
    signals: pd.DataFrame
    trades: pd.DataFrame
    portfolio_snapshots: pd.DataFrame
    outputs: dict[str, Path]


class QtBacktestService:
    """Small application service used by the Qt MVP.

    The service deliberately returns pandas frames instead of Qt types. That
    keeps the backtest engine reusable for future miniQMT and live-trading
    orchestration.
    """

    strategies: tuple[BacktestStrategySpec, ...] = (
        BacktestStrategySpec(
            strategy_id="daily_trend_following",
            display_name="日线趋势跟随",
            default_timeframe="1d",
            description="EMA20/EMA50 trend pullback strategy with ATR stop and staged exit.",
        ),
        BacktestStrategySpec(
            strategy_id="ema_cross",
            display_name="EMA 快慢线交叉",
            default_timeframe="1h",
            description="EMA fast/slow golden-cross entry with previous-bar low stop.",
        ),
    )

    def list_strategies(self) -> tuple[BacktestStrategySpec, ...]:
        return self.strategies

    def list_timeframes(self, db_path: str) -> list[str]:
        path = Path(db_path)
        if not path.exists():
            return []
        try:
            import duckdb

            con = duckdb.connect(str(path), read_only=True)
            try:
                frame = con.execute(
                    """
                    SELECT DISTINCT timeframe
                    FROM kline_bars
                    ORDER BY timeframe
                    """
                ).fetchdf()
            finally:
                con.close()
        except Exception:
            return []
        return [str(value) for value in frame["timeframe"].dropna().tolist()]

    def list_symbols(self, db_path: str, *, timeframe: str | None = None, limit: int = 200) -> pd.DataFrame:
        path = Path(db_path)
        if not path.exists():
            return pd.DataFrame(columns=["stock_code", "stock_name"])
        try:
            import duckdb

            con = duckdb.connect(str(path), read_only=True)
            try:
                if timeframe:
                    frame = con.execute(
                        """
                        SELECT stock_code, ANY_VALUE(stock_name) AS stock_name, MAX(trade_date) AS latest_trade_date
                        FROM kline_bars
                        WHERE timeframe = ?
                        GROUP BY stock_code
                        ORDER BY stock_code
                        LIMIT ?
                        """,
                        (timeframe, limit),
                    ).fetchdf()
                else:
                    frame = con.execute(
                        """
                        SELECT stock_code, ANY_VALUE(stock_name) AS stock_name, MAX(trade_date) AS latest_trade_date
                        FROM kline_bars
                        GROUP BY stock_code
                        ORDER BY stock_code
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchdf()
            finally:
                con.close()
        except Exception:
            return pd.DataFrame(columns=["stock_code", "stock_name"])
        return frame

    def run_backtest(self, request: QtBacktestRequest) -> QtBacktestResult:
        self._validate_request_data(request)
        if request.strategy_id == "daily_trend_following":
            raw = DailyTrendFollowingReviewRunner(self._daily_trend_config(request)).run()
        elif request.strategy_id == "ema_cross":
            raw = EmaCrossBacktestRunner(self._ema_cross_config(request)).run()
        else:
            raise ValueError(f"Unsupported strategy: {request.strategy_id}")

        kline = self._load_result_kline(request, raw)
        return QtBacktestResult(
            run_id=str(raw["run_id"]),
            strategy_id=request.strategy_id,
            summary=dict(raw.get("summary", {})),
            kline=kline,
            signals=self._frame(raw.get("signals")),
            trades=self._frame(raw.get("trades")),
            portfolio_snapshots=self._frame(raw.get("portfolio_snapshots")),
            outputs=dict(raw.get("outputs", {})),
        )

    @staticmethod
    def parse_stock_codes(value: str) -> list[str] | None:
        codes = [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
        return codes or None

    def describe_available_data(
        self,
        db_path: str,
        *,
        stock_codes: list[str] | None = None,
        timeframe: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        path = Path(db_path)
        if not path.exists():
            return pd.DataFrame(columns=["stock_code", "timeframe", "min_date", "max_date", "bars"])
        try:
            import duckdb

            con = duckdb.connect(str(path), read_only=True)
            try:
                clauses: list[str] = []
                params: list[Any] = []
                if stock_codes:
                    clauses.append("stock_code IN (SELECT UNNEST(?))")
                    params.append(stock_codes)
                if timeframe:
                    clauses.append("timeframe IN (SELECT UNNEST(?))")
                    params.append([timeframe])
                if start_date:
                    clauses.append("trade_date <= ?")
                    params.append(end_date or start_date)
                if end_date:
                    clauses.append("trade_date >= ?")
                    params.append(start_date or end_date)
                where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                frame = con.execute(
                    f"""
                    SELECT stock_code, timeframe, MIN(trade_date) AS min_date, MAX(trade_date) AS max_date, COUNT(*) AS bars
                    FROM kline_bars
                    {where_sql}
                    GROUP BY stock_code, timeframe
                    ORDER BY stock_code, timeframe
                    """,
                    params,
                ).fetchdf()
            finally:
                con.close()
        except Exception:
            return pd.DataFrame(columns=["stock_code", "timeframe", "min_date", "max_date", "bars"])
        return frame

    def _validate_request_data(self, request: QtBacktestRequest) -> None:
        if request.strategy_id != "daily_trend_following":
            return
        frame = self.describe_available_data(
            request.db_path,
            stock_codes=request.stock_codes,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        if not frame.empty:
            return

        if request.stock_codes:
            available = self.describe_available_data(request.db_path, stock_codes=request.stock_codes)
            if not available.empty:
                pieces = []
                for stock_code, stock_frame in available.groupby("stock_code"):
                    timeframes = ", ".join(stock_frame["timeframe"].astype(str).tolist())
                    pieces.append(f"{stock_code}: {timeframes}")
                joined = "；".join(pieces)
                raise ValueError(
                    "当前选择的股票在这个周期没有本地数据。\n"
                    f"周期: {request.timeframe}\n"
                    f"可用周期: {joined}\n"
                    "日线趋势跟随需要 1d 数据；你可以先同步日线，或改用 EMA 快慢线交叉并切到 1h。"
                )

        raise ValueError(
            "当前条件下没有找到本地 K 线数据。\n"
            f"周期: {request.timeframe}\n"
            "请先同步对应周期数据，或调整股票代码和时间范围。"
        )

    def _load_result_kline(self, request: QtBacktestRequest, raw: dict[str, Any]) -> pd.DataFrame:
        stock_codes = self._chart_stock_codes(request.stock_codes, raw)
        if not stock_codes:
            return pd.DataFrame()
        return LocalMarketData(DuckDBStore(request.db_path)).get_kline(
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            stock_codes=stock_codes,
        )

    @staticmethod
    def _chart_stock_codes(request_codes: list[str] | None, raw: dict[str, Any]) -> list[str]:
        if request_codes:
            return request_codes[:5]

        for key in ("trades", "signals"):
            frame = QtBacktestService._frame(raw.get(key))
            if not frame.empty and "stock_code" in frame.columns:
                return frame["stock_code"].dropna().astype(str).drop_duplicates().head(5).tolist()
        return []

    @staticmethod
    def _frame(value: Any) -> pd.DataFrame:
        if isinstance(value, pd.DataFrame):
            return value
        return pd.DataFrame()

    @staticmethod
    def _daily_trend_config(request: QtBacktestRequest) -> DailyTrendFollowingReviewConfig:
        params = request.params
        return DailyTrendFollowingReviewConfig(
            db_path=request.db_path,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            stock_codes=request.stock_codes,
            initial_cash=request.initial_cash,
            commission_rate=request.commission_rate,
            stamp_tax_rate=request.stamp_tax_rate,
            transfer_fee_rate=request.transfer_fee_rate,
            slippage_rate=request.slippage_rate,
            min_bias=float(params.get("min_bias", 0.02)),
            min_volume_ratio=float(params.get("min_volume_ratio", 1.2)),
            risk_per_trade_pct=float(params.get("risk_per_trade_pct", 0.008)),
            max_position_pct=float(params.get("max_position_pct", 0.20)),
            max_total_risk_pct=float(params.get("max_total_risk_pct", 0.025)),
        )

    @staticmethod
    def _ema_cross_config(request: QtBacktestRequest) -> EmaCrossBacktestConfig:
        params = request.params
        fast_period = max(2, int(params.get("fast_period", 21)))
        slow_period = max(fast_period + 1, int(params.get("slow_period", 55)))
        return EmaCrossBacktestConfig(
            db_path=request.db_path,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            stock_codes=request.stock_codes,
            initial_cash=request.initial_cash,
            commission_rate=request.commission_rate,
            stamp_tax_rate=request.stamp_tax_rate,
            transfer_fee_rate=request.transfer_fee_rate,
            slippage_rate=request.slippage_rate,
            fast_period=fast_period,
            slow_period=slow_period,
            risk_per_trade=max(0.0, float(params.get("risk_per_trade", 5_000))),
        )
