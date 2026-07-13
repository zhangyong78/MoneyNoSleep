from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
import logging
import time
from typing import Callable

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.normalizer import normalize_kline_frame
from mns.data.parquet_store import ParquetStore
from mns.data.providers.base import DataProvider
from mns.data.timeframes import normalize_timeframe
from mns.data.validator import validate_kline_frame
from mns.pipelines.stock_feature_store import StockFeatureStoreBuilder, StockFeatureStoreConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DataSyncResult:
    rows_written: int
    parquet_files: list[str] = field(default_factory=list)
    quality_issue_count: int = 0
    latest_trade_date: str | None = None
    expected_latest_trade_date: str | None = None
    lagging_stock_codes: list[str] = field(default_factory=list)
    requested_stock_count: int = 0
    synced_stock_count: int = 0
    empty_stock_codes: list[str] = field(default_factory=list)
    failed_stock_codes: list[str] = field(default_factory=list)
    skipped_stock_codes: list[str] = field(default_factory=list)
    feature_rows_written: int = 0
    followup_rows_written: int = 0
    feature_refresh_attempted: bool = False
    feature_refresh_success: bool | None = None
    feature_refresh_message: str = ""


@dataclass(frozen=True)
class DataSyncProgress:
    current: int
    total: int
    stock_code: str
    status: str
    message: str = ""


class DailyKlineSyncService:
    def __init__(
        self,
        *,
        provider: DataProvider,
        duckdb_store: DuckDBStore,
        parquet_store: ParquetStore,
        strict_quality: bool = True,
        provider_factory: Callable[[], DataProvider] | None = None,
        max_workers: int = 1,
        max_retries: int = 0,
    ) -> None:
        self.provider = provider
        self.duckdb_store = duckdb_store
        self.parquet_store = parquet_store
        self.strict_quality = strict_quality
        self.provider_factory = provider_factory
        self.max_workers = max(1, int(max_workers))
        self.max_retries = max(0, int(max_retries))

    def _refresh_feature_store(self, *, merged: pd.DataFrame, timeframe: str) -> tuple[int, int, bool, bool | None, str]:
        if timeframe != "1d" or merged.empty:
            return 0, 0, False, None, ""

        start_date = str(pd.to_datetime(merged["trade_date"], errors="coerce").min().date())
        end_date = str(pd.to_datetime(merged["trade_date"], errors="coerce").max().date())
        stock_codes = sorted(merged["stock_code"].astype(str).drop_duplicates().tolist())
        try:
            result = StockFeatureStoreBuilder(
                StockFeatureStoreConfig(
                    db_path=str(self.duckdb_store.path),
                    timeframe=timeframe,
                    start_date=start_date,
                    end_date=end_date,
                    stock_codes=stock_codes,
                )
            ).run()
            feature_rows = int(result["feature_rows"])
            followup_rows = int(result["followup_rows"])
            message = (
                f"Feature refresh succeeded for {len(stock_codes)} stocks, "
                f"{start_date} -> {end_date}: "
                f"{feature_rows} feature rows, {followup_rows} followup rows."
            )
            logger.info(message)
            print(message)
            return feature_rows, followup_rows, True, True, message
        except Exception as exc:
            message = (
                f"Feature refresh failed for {len(stock_codes)} stocks, "
                f"{start_date} -> {end_date}: {exc}"
            )
            logger.exception(message)
            print(message)
            return 0, 0, True, False, message

    def _sync_one_stock(
        self,
        *,
        stock_code: str,
        start_time: datetime,
        end_time: datetime,
        timeframe: str,
    ) -> tuple[str, pd.DataFrame | None, int, str]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            provider = self.provider_factory() if self.provider_factory is not None else self.provider
            try:
                raw = provider.get_kline(stock_code, start_time, end_time, timeframe)
                normalized = normalize_kline_frame(raw, source=provider.name, timeframe=timeframe)
                if normalized.empty:
                    return "empty", None, 0, ""
                issues = validate_kline_frame(normalized)
                if issues and self.strict_quality:
                    sample = issues[0]
                    raise ValueError(
                        f"kline quality check failed for {stock_code}: row={sample.row_index}, "
                        f"field={sample.field}, message={sample.message}"
                    )
                message = ""
                if attempt > 0:
                    message = f"第 {attempt + 1} 次重试成功"
                return "synced", normalized, len(issues), message
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
                time.sleep(min(0.5 * (attempt + 1), 2.0))
            finally:
                if provider is not self.provider and hasattr(provider, "logout"):
                    try:
                        provider.logout()
                    except Exception:
                        pass
        if last_error is not None:
            raise last_error
        return "empty", None, 0, ""

    def sync(
        self,
        *,
        stock_codes: list[str],
        start_time: datetime,
        end_time: datetime,
        timeframe: str = "1d",
        resume_from_latest_local: bool = True,
        progress_callback: Callable[[DataSyncProgress], None] | None = None,
    ) -> DataSyncResult:
        timeframe = normalize_timeframe(timeframe)
        frames: list[pd.DataFrame] = []
        quality_issue_count = 0
        expected_latest_trade_date: str | None = None
        empty_stock_codes: list[str] = []
        failed_stock_codes: list[str] = []
        skipped_stock_codes: list[str] = []
        requested_stock_count = len(stock_codes)

        if progress_callback is not None:
            progress_callback(
                DataSyncProgress(
                    current=0,
                    total=requested_stock_count,
                    stock_code="",
                    status="preparing",
                    message="正在准备同步任务...",
                )
            )

        try:
            trade_calendar = self.provider.get_trade_calendar(start_time.date(), end_time.date())
            if not trade_calendar.empty and "trade_date" in trade_calendar.columns:
                expected_trade_dates = pd.to_datetime(trade_calendar["trade_date"], errors="coerce").dropna()
                if not expected_trade_dates.empty:
                    expected_latest_trade_date = str(expected_trade_dates.max().date())
        except Exception:
            expected_latest_trade_date = None

        latest_local_by_stock: dict[str, pd.Timestamp] = {}
        if resume_from_latest_local:
            try:
                latest_local = self.duckdb_store.get_latest_trade_dates(stock_codes=stock_codes, timeframe=timeframe)
                if not latest_local.empty:
                    for _, row in latest_local.iterrows():
                        stock_code = str(row.get("stock_code", "")).strip()
                        latest_trade_date = pd.to_datetime(row.get("latest_trade_date"), errors="coerce")
                        if stock_code and pd.notna(latest_trade_date):
                            latest_local_by_stock[stock_code] = pd.Timestamp(latest_trade_date)
            except Exception:
                latest_local_by_stock = {}

        plans: list[tuple[int, str, datetime]] = []
        for index, stock_code in enumerate(stock_codes, start=1):
            effective_start_time = start_time
            latest_local_trade_date = latest_local_by_stock.get(stock_code)
            if latest_local_trade_date is not None:
                next_trade_time = (latest_local_trade_date + pd.Timedelta(days=1)).to_pydatetime()
                if next_trade_time.date() > end_time.date():
                    skipped_stock_codes.append(stock_code)
                    if progress_callback is not None:
                        progress_callback(
                            DataSyncProgress(
                                index,
                                requested_stock_count,
                                stock_code,
                                "skipped",
                                f"已覆盖到 {latest_local_trade_date.date()}",
                            )
                        )
                    continue
                if next_trade_time > effective_start_time:
                    effective_start_time = next_trade_time
            plans.append((index, stock_code, effective_start_time))

        if self.max_workers > 1 and self.provider_factory is not None and len(plans) > 1:
            if progress_callback is not None:
                progress_callback(
                    DataSyncProgress(
                        current=len(skipped_stock_codes),
                        total=requested_stock_count,
                        stock_code="",
                        status="running",
                        message=f"正在并发同步 {len(plans)} 只股票...",
                    )
                )
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_map = {
                    executor.submit(
                        self._sync_one_stock,
                        stock_code=stock_code,
                        start_time=effective_start_time,
                        end_time=end_time,
                        timeframe=timeframe,
                    ): (index, stock_code)
                    for index, stock_code, effective_start_time in plans
                }
                for future in as_completed(future_map):
                    index, stock_code = future_map[future]
                    try:
                        status, normalized, issue_count, message = future.result()
                        quality_issue_count += issue_count
                        if status == "empty":
                            empty_stock_codes.append(stock_code)
                            if progress_callback is not None:
                                progress_callback(DataSyncProgress(index, requested_stock_count, stock_code, "empty"))
                            continue
                        if normalized is not None:
                            frames.append(normalized)
                        if progress_callback is not None:
                            progress_callback(DataSyncProgress(index, requested_stock_count, stock_code, "synced", message))
                    except Exception as exc:
                        failed_stock_codes.append(stock_code)
                        if progress_callback is not None:
                            progress_callback(DataSyncProgress(index, requested_stock_count, stock_code, "failed", str(exc)))
        else:
            for index, stock_code, effective_start_time in plans:
                try:
                    if progress_callback is not None:
                        progress_callback(
                            DataSyncProgress(
                                current=index - 1,
                                total=requested_stock_count,
                                stock_code=stock_code,
                                status="running",
                                message=f"正在拉取 {effective_start_time.date()} 到 {end_time.date()} 的行情数据...",
                            )
                        )
                    status, normalized, issue_count, message = self._sync_one_stock(
                        stock_code=stock_code,
                        start_time=effective_start_time,
                        end_time=end_time,
                        timeframe=timeframe,
                    )
                    quality_issue_count += issue_count
                    if status == "empty":
                        empty_stock_codes.append(stock_code)
                        if progress_callback is not None:
                            progress_callback(DataSyncProgress(index, requested_stock_count, stock_code, "empty"))
                        continue
                    if normalized is not None:
                        frames.append(normalized)
                    if progress_callback is not None:
                        progress_callback(DataSyncProgress(index, requested_stock_count, stock_code, "synced", message))
                except Exception as exc:
                    failed_stock_codes.append(stock_code)
                    if progress_callback is not None:
                        progress_callback(DataSyncProgress(index, requested_stock_count, stock_code, "failed", str(exc)))

        if not frames:
            return DataSyncResult(
                rows_written=0,
                quality_issue_count=quality_issue_count,
                expected_latest_trade_date=expected_latest_trade_date,
                requested_stock_count=requested_stock_count,
                synced_stock_count=0,
                empty_stock_codes=empty_stock_codes,
                failed_stock_codes=failed_stock_codes,
                skipped_stock_codes=skipped_stock_codes,
            )

        merged = pd.concat(frames, ignore_index=True)
        merged = merged.sort_values(["trade_date", "stock_code", "bar_time"]).reset_index(drop=True)
        self.duckdb_store.initialize()
        rows_written = self.duckdb_store.replace_kline_bars(merged)
        (
            feature_rows_written,
            followup_rows_written,
            feature_refresh_attempted,
            feature_refresh_success,
            feature_refresh_message,
        ) = self._refresh_feature_store(merged=merged, timeframe=timeframe)

        parquet_files: list[str] = []
        for trade_date, daily in merged.groupby("trade_date"):
            path = self.parquet_store.write_kline(
                daily.reset_index(drop=True),
                timeframe=timeframe,
                trade_date=str(trade_date),
            )
            parquet_files.append(str(path))

        latest_trade_date = str(pd.to_datetime(merged["trade_date"], errors="coerce").max().date())
        lagging_stock_codes: list[str] = []
        if expected_latest_trade_date:
            latest_by_stock = (
                merged.assign(trade_date=pd.to_datetime(merged["trade_date"], errors="coerce"))
                .groupby("stock_code", as_index=False)["trade_date"]
                .max()
            )
            lagging_stock_codes = (
                latest_by_stock.loc[
                    latest_by_stock["trade_date"].dt.date < pd.Timestamp(expected_latest_trade_date).date(),
                    "stock_code",
                ]
                .astype(str)
                .sort_values()
                .tolist()
            )

        return DataSyncResult(
            rows_written=rows_written,
            parquet_files=parquet_files,
            quality_issue_count=quality_issue_count,
            latest_trade_date=latest_trade_date,
            expected_latest_trade_date=expected_latest_trade_date,
            lagging_stock_codes=lagging_stock_codes,
            requested_stock_count=requested_stock_count,
            synced_stock_count=len(frames),
            empty_stock_codes=empty_stock_codes,
            failed_stock_codes=failed_stock_codes,
            skipped_stock_codes=skipped_stock_codes,
            feature_rows_written=feature_rows_written,
            followup_rows_written=followup_rows_written,
            feature_refresh_attempted=feature_refresh_attempted,
            feature_refresh_success=feature_refresh_success,
            feature_refresh_message=feature_refresh_message,
        )
