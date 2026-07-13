from __future__ import annotations

from uuid import uuid4

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.local_data import LocalMarketData
from mns.review.chart_indicators import ChartIndicatorSpec
from mns.review.screenshot_exporter import ScreenshotExporter
from mns.review.trade_pairs import pair_trade_actions


def indicators_for_strategy(strategy_name: str) -> tuple[ChartIndicatorSpec, ...] | None:
    if strategy_name != "two_stage_trend":
        return None
    return (
        ChartIndicatorSpec(kind="ma", period=10, color="#f2c744"),
        ChartIndicatorSpec(kind="ma", period=20, color="#e849a1"),
        ChartIndicatorSpec(kind="ma", period=60, color="#2a9df4"),
    )


class BulkScreenshotExporter:
    def __init__(self, *, store: DuckDBStore, screenshot_exporter: ScreenshotExporter | None = None) -> None:
        self.store = store
        self.market_data = LocalMarketData(store)
        self.screenshot_exporter = screenshot_exporter or ScreenshotExporter()

    def export_run(self, run_id: str, *, timeframe: str = "1d") -> pd.DataFrame:
        actions = self.store.get_run_trades(run_id)
        trades = pair_trade_actions(actions)
        if trades.empty:
            return pd.DataFrame()

        kline = self.market_data.get_kline(timeframe=timeframe)
        indicators = indicators_for_strategy(str(trades["strategy_name"].iloc[0]))
        records: list[dict] = []
        for _, trade in trades.iterrows():
            stock_kline = kline[kline["stock_code"] == trade["stock_code"]]
            if stock_kline.empty:
                continue
            image_path = self.screenshot_exporter.export_trade_chart(
                trade,
                stock_kline,
                run_id=run_id,
                indicators=indicators,
            )
            record = {
                "screenshot_id": uuid4().hex,
                "trade_id": str(trade["trade_id"]),
                "run_id": str(run_id),
                "stock_code": str(trade["stock_code"]),
                "image_path": str(image_path),
                "chart_timeframe": timeframe,
                "start_time": pd.to_datetime(stock_kline["bar_time"]).min(),
                "end_time": pd.to_datetime(stock_kline["bar_time"]).max(),
                "created_time": pd.Timestamp.now(),
            }
            self.store.replace_trade_screenshot(record)
            records.append(record)

        return pd.DataFrame(records)
