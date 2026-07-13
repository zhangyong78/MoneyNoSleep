from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import sys
from typing import Callable

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.intraday_resample import can_resample_timeframe, resample_kline_frame
from mns.data.local_data import LocalMarketData
from mns.data.market_scope import filter_stock_codes_by_market_groups, normalize_market_groups
from mns.data.normalizer import normalize_kline_frame
from mns.data.parquet_store import ParquetStore
from mns.data.providers.qmt_provider import QMTProvider
from mns.data.sync import DailyKlineSyncService, DataSyncProgress
from mns.data.timeframes import normalize_timeframe


MARKET_GROUP_DISPLAY_ORDER = ["all_a", "sh_a", "sz_a", "bj_a", "all_etf", "sh_etf", "sz_etf"]
DEFAULT_BAOSTOCK_STATE_PATH = "data/logs/baostock_bulk_sync_state.json"

TIMEFRAME_SORT_ORDER = {
    "1m": 1,
    "5m": 2,
    "15m": 3,
    "30m": 4,
    "1h": 5,
    "1d": 6,
}


@dataclass(frozen=True)
class LocalOverviewRow:
    timeframe: str
    stock_count: int
    bar_count: int
    first_trade_date: str | None
    latest_trade_date: str | None


@dataclass(frozen=True)
class LocalSummaryRow:
    stock_code: str
    stock_name: str
    timeframe: str
    bar_count: int
    first_trade_date: str | None
    latest_trade_date: str | None
    first_bar_time: str | None
    latest_bar_time: str | None
    source: str


@dataclass(frozen=True)
class ConversionRow:
    stock_code: str
    source_timeframe: str
    target_timeframe: str
    status: str
    rows_written: int
    parquet_file_count: int
    latest_trade_date: str | None
    message: str


@dataclass(frozen=True)
class ConversionResult:
    rows: list[ConversionRow]

    @property
    def total_rows_written(self) -> int:
        return sum(row.rows_written for row in self.rows)

    @property
    def stock_count(self) -> int:
        return len({row.stock_code for row in self.rows})


ConversionProgressCallback = Callable[[dict[str, object]], None]


class LocalDataWorkbenchService:
    def __init__(
        self,
        *,
        db_path: str | Path = "data/duckdb/mns.duckdb",
        parquet_root: str | Path = "data/parquet",
        workspace_root: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.parquet_root = Path(parquet_root)
        self.workspace_root = Path(workspace_root) if workspace_root is not None else Path(__file__).resolve().parents[2]
        self.store = DuckDBStore(self.db_path)
        self.local_data = LocalMarketData(self.store)
        self.parquet_store = ParquetStore(self.parquet_root)

    @staticmethod
    def normalize_stock_codes(values: list[str] | tuple[str, ...] | set[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            code = LocalDataWorkbenchService.normalize_stock_code(value)
            if code and code not in seen:
                normalized.append(code)
                seen.add(code)
        return normalized

    @staticmethod
    def normalize_stock_code(value: str) -> str:
        raw = str(value).strip()
        if not raw:
            return ""
        uppered = raw.upper()
        if uppered.endswith((".SH", ".SZ", ".BJ")) and "." in uppered:
            return uppered

        lowered = raw.lower()
        if lowered.startswith(("sh.", "sz.", "bj.")) and len(lowered) >= 9:
            return f"{lowered[3:9]}.{lowered[:2].upper()}"

        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) != 6:
            return uppered
        if digits.startswith(("5", "6", "9")):
            return f"{digits}.SH"
        if digits.startswith(("4", "8")):
            return f"{digits}.BJ"
        return f"{digits}.SZ"

    @staticmethod
    def parse_text_list(text: str) -> list[str]:
        return [item.strip() for item in str(text).replace("\n", ",").split(",") if item.strip()]

    def query_local_overview(self) -> list[LocalOverviewRow]:
        frame = self.store.query_frame(
            """
            SELECT
                timeframe,
                COUNT(DISTINCT stock_code) AS stock_count,
                COUNT(*) AS bar_count,
                MIN(trade_date) AS first_trade_date,
                MAX(trade_date) AS latest_trade_date
            FROM kline_bars
            GROUP BY timeframe
            """
        )
        if frame.empty:
            return []
        frame["timeframe"] = frame["timeframe"].map(normalize_timeframe)
        frame = frame.sort_values(
            by=["timeframe"],
            key=lambda series: series.map(lambda value: TIMEFRAME_SORT_ORDER.get(str(value), 999)),
        ).reset_index(drop=True)
        return [
            LocalOverviewRow(
                timeframe=str(row["timeframe"]),
                stock_count=int(row["stock_count"]),
                bar_count=int(row["bar_count"]),
                first_trade_date=_stringify_date(row.get("first_trade_date")),
                latest_trade_date=_stringify_date(row.get("latest_trade_date")),
            )
            for _, row in frame.iterrows()
        ]

    def resolve_local_stock_codes(
        self,
        *,
        stock_codes_text: str = "",
        market_groups: list[str] | None = None,
        timeframe: str | None = None,
    ) -> list[str]:
        manual_codes = self.normalize_stock_codes(self.parse_text_list(stock_codes_text))
        if manual_codes:
            return manual_codes

        clauses: list[str] = []
        params: list[object] = []
        if timeframe:
            clauses.append("timeframe IN (SELECT UNNEST(?))")
            params.append([normalize_timeframe(timeframe)])
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        frame = self.store.query_frame(
            f"""
            SELECT DISTINCT stock_code
            FROM kline_bars
            {where_clause}
            ORDER BY stock_code
            """,
            tuple(params),
        )
        codes = frame.get("stock_code", pd.Series(dtype=object)).dropna().astype(str).tolist()
        normalized_groups = normalize_market_groups(market_groups or [])
        if normalized_groups:
            return filter_stock_codes_by_market_groups(codes, normalized_groups)
        return self.normalize_stock_codes(codes)

    def query_local_summary(
        self,
        *,
        timeframe: str = "",
        stock_codes_text: str = "",
        market_groups: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 500,
    ) -> list[LocalSummaryRow]:
        clauses: list[str] = []
        params: list[object] = []

        selected_codes = self.resolve_local_stock_codes(
            stock_codes_text=stock_codes_text,
            market_groups=market_groups,
            timeframe=timeframe or None,
        )
        if selected_codes:
            clauses.append("stock_code IN (SELECT UNNEST(?))")
            params.append(selected_codes)

        if timeframe:
            clauses.append("timeframe IN (SELECT UNNEST(?))")
            params.append([normalize_timeframe(timeframe)])
        if start_time is not None:
            clauses.append("bar_time >= ?")
            params.append(pd.Timestamp(start_time).to_pydatetime())
        if end_time is not None:
            clauses.append("bar_time <= ?")
            params.append(pd.Timestamp(end_time).to_pydatetime())

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        frame = self.store.query_frame(
            f"""
            SELECT
                stock_code,
                COALESCE(MAX(stock_name), '') AS stock_name,
                timeframe,
                COUNT(*) AS bar_count,
                MIN(trade_date) AS first_trade_date,
                MAX(trade_date) AS latest_trade_date,
                MIN(bar_time) AS first_bar_time,
                MAX(bar_time) AS latest_bar_time,
                COALESCE(MAX(source), '') AS source
            FROM kline_bars
            {where_clause}
            GROUP BY stock_code, timeframe
            ORDER BY timeframe, stock_code
            LIMIT ?
            """,
            tuple([*params, max(1, int(limit))]),
        )
        if frame.empty:
            return []
        frame["timeframe"] = frame["timeframe"].map(normalize_timeframe)
        timeframe_sort = frame["timeframe"].map(lambda value: TIMEFRAME_SORT_ORDER.get(str(value), 999))
        frame = frame.assign(_timeframe_sort=timeframe_sort).sort_values(["_timeframe_sort", "stock_code"]).reset_index(drop=True)
        return [
            LocalSummaryRow(
                stock_code=str(row["stock_code"]),
                stock_name=str(row.get("stock_name") or ""),
                timeframe=str(row["timeframe"]),
                bar_count=int(row["bar_count"]),
                first_trade_date=_stringify_date(row.get("first_trade_date")),
                latest_trade_date=_stringify_date(row.get("latest_trade_date")),
                first_bar_time=_stringify_timestamp(row.get("first_bar_time")),
                latest_bar_time=_stringify_timestamp(row.get("latest_bar_time")),
                source=str(row.get("source") or ""),
            )
            for _, row in frame.iterrows()
        ]

    def query_local_bars(
        self,
        *,
        timeframe: str,
        stock_codes_text: str = "",
        market_groups: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 300,
    ) -> pd.DataFrame:
        selected_codes = self.resolve_local_stock_codes(
            stock_codes_text=stock_codes_text,
            market_groups=market_groups,
            timeframe=timeframe,
        )
        clauses = ["timeframe IN (SELECT UNNEST(?))"]
        params: list[object] = [[normalize_timeframe(timeframe)]]
        if selected_codes:
            clauses.append("stock_code IN (SELECT UNNEST(?))")
            params.append(selected_codes)
        if start_time is not None:
            clauses.append("bar_time >= ?")
            params.append(pd.Timestamp(start_time).to_pydatetime())
        if end_time is not None:
            clauses.append("bar_time <= ?")
            params.append(pd.Timestamp(end_time).to_pydatetime())
        return self.store.query_frame(
            f"""
            SELECT
                stock_code,
                COALESCE(stock_name, '') AS stock_name,
                timeframe,
                trade_date,
                bar_time,
                open,
                high,
                low,
                close,
                volume,
                amount,
                source
            FROM kline_bars
            WHERE {' AND '.join(clauses)}
            ORDER BY bar_time DESC, stock_code
            LIMIT ?
            """,
            tuple([*params, max(1, int(limit))]),
        )

    def convert_local_timeframes(
        self,
        *,
        source_timeframe: str,
        target_timeframes: list[str],
        stock_codes_text: str = "",
        market_groups: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        progress_callback: ConversionProgressCallback | None = None,
    ) -> ConversionResult:
        source = normalize_timeframe(source_timeframe)
        targets = [normalize_timeframe(item) for item in target_timeframes if item]
        targets = [target for target in dict.fromkeys(targets) if target != source]
        if not targets:
            raise ValueError("Please choose at least one target timeframe.")
        for target in targets:
            if not can_resample_timeframe(source, target):
                raise ValueError(f"Cannot convert {source} to {target}.")

        stock_codes = self.resolve_local_stock_codes(
            stock_codes_text=stock_codes_text,
            market_groups=market_groups,
            timeframe=source,
        )
        if not stock_codes:
            raise ValueError("No local stock codes found for the selected source timeframe.")

        self.store.initialize()
        rows: list[ConversionRow] = []
        total_steps = len(stock_codes) * len(targets)
        current_step = 0
        self._emit_conversion_progress(
            progress_callback,
            stage="start",
            source_timeframe=source,
            target_timeframes=targets,
            stock_count=len(stock_codes),
            total_steps=total_steps,
            current_step=0,
        )
        for stock_code in stock_codes:
            frame = self.local_data.get_kline(
                timeframe=source,
                start_date=start_time.date() if start_time else None,
                end_date=end_time.date() if end_time else None,
                stock_codes=[stock_code],
            )
            if not frame.empty:
                source_name = str(frame["source"].dropna().astype(str).iloc[0]) if "source" in frame.columns and not frame["source"].dropna().empty else "local"
                frame = normalize_kline_frame(frame, source=source_name, timeframe=source)
                frame["bar_time"] = pd.to_datetime(frame["bar_time"], errors="coerce")
                if start_time is not None:
                    frame = frame.loc[frame["bar_time"] >= pd.Timestamp(start_time)]
                if end_time is not None:
                    frame = frame.loc[frame["bar_time"] <= pd.Timestamp(end_time)]
                frame = frame.reset_index(drop=True)

            if frame.empty:
                for target in targets:
                    current_step += 1
                    rows.append(
                        ConversionRow(
                            stock_code=stock_code,
                            source_timeframe=source,
                            target_timeframe=target,
                            status="empty",
                            rows_written=0,
                            parquet_file_count=0,
                            latest_trade_date=None,
                            message="source timeframe not found locally",
                        )
                    )
                    self._emit_conversion_progress(
                        progress_callback,
                        stage="step",
                        stock_code=stock_code,
                        source_timeframe=source,
                        target_timeframe=target,
                        status="empty",
                        current_step=current_step,
                        total_steps=total_steps,
                        message="source timeframe not found locally",
                    )
                continue

            for target in targets:
                resampled = resample_kline_frame(
                    frame,
                    source_timeframe=source,
                    target_timeframe=target,
                    source_label=f"local_resampled_from_{source}",
                )
                rows_written = self.store.replace_kline_bars(resampled)
                parquet_file_count = 0
                for trade_date, daily in resampled.groupby("trade_date"):
                    self.parquet_store.write_kline(daily.reset_index(drop=True), timeframe=target, trade_date=str(trade_date))
                    parquet_file_count += 1
                latest_trade_date = None if resampled.empty else _stringify_date(pd.to_datetime(resampled["trade_date"], errors="coerce").max())
                status = "synced" if rows_written else "empty"
                rows.append(
                    ConversionRow(
                        stock_code=stock_code,
                        source_timeframe=source,
                        target_timeframe=target,
                        status=status,
                        rows_written=int(rows_written),
                        parquet_file_count=parquet_file_count,
                        latest_trade_date=latest_trade_date,
                        message=f"derived from {source}",
                    )
                )
                current_step += 1
                self._emit_conversion_progress(
                    progress_callback,
                    stage="step",
                    stock_code=stock_code,
                    source_timeframe=source,
                    target_timeframe=target,
                    status=status,
                    rows_written=int(rows_written),
                    parquet_file_count=parquet_file_count,
                    latest_trade_date=latest_trade_date,
                    current_step=current_step,
                    total_steps=total_steps,
                    message=f"derived from {source}",
                )
        self._emit_conversion_progress(
            progress_callback,
            stage="done",
            source_timeframe=source,
            target_timeframes=targets,
            stock_count=len(stock_codes),
            total_steps=total_steps,
            current_step=current_step,
        )
        return ConversionResult(rows=rows)

    @staticmethod
    def _emit_conversion_progress(progress_callback: ConversionProgressCallback | None, **payload: object) -> None:
        if progress_callback is None:
            return
        progress_callback(payload)

    def get_qmt_connection_info(
        self,
        *,
        ip: str = "",
        port: int | None = None,
        dividend_type: str = "front",
    ) -> dict[str, object]:
        provider = QMTProvider(dividend_type=dividend_type, ip=ip, port=port)
        return provider.connection_info()

    def resolve_qmt_stock_codes(
        self,
        *,
        stock_codes_text: str = "",
        sync_all: bool = False,
        include_etf: bool = False,
        dividend_type: str = "front",
        ip: str = "",
        port: int | None = None,
    ) -> list[str]:
        manual_codes = self.normalize_stock_codes(self.parse_text_list(stock_codes_text))
        if manual_codes:
            return manual_codes
        if not sync_all:
            raise ValueError("请输入股票代码，或勾选同步全A股。")
        provider = QMTProvider(dividend_type=dividend_type, ip=ip, port=port)
        frame = provider.get_stock_list(include_etf=include_etf)
        codes = frame.get("stock_code", pd.Series(dtype=object)).dropna().astype(str).tolist()
        resolved = self.normalize_stock_codes(codes)
        if not resolved:
            raise ValueError("miniQMT returned no stock codes.")
        return resolved

    def sync_qmt_kline(
        self,
        *,
        stock_codes_text: str = "",
        sync_all: bool = False,
        include_etf: bool = False,
        start_time: datetime,
        end_time: datetime,
        timeframe: str = "",
        timeframes: list[str] | None = None,
        dividend_type: str = "front",
        ip: str = "",
        port: int | None = None,
        allow_quality_issues: bool = False,
        resume_from_latest_local: bool = True,
        progress_callback=None,
        log_callback=None,
    ):
        provider = QMTProvider(dividend_type=dividend_type, ip=ip, port=port)
        stock_codes = self.resolve_qmt_stock_codes(
            stock_codes_text=stock_codes_text,
            sync_all=sync_all,
            include_etf=include_etf,
            dividend_type=dividend_type,
            ip=ip,
            port=port,
        )
        normalized_timeframes = [normalize_timeframe(item) for item in (timeframes or []) if str(item).strip()]
        if not normalized_timeframes and str(timeframe).strip():
            normalized_timeframes = [normalize_timeframe(timeframe)]
        normalized_timeframes = list(dict.fromkeys(normalized_timeframes))
        if not normalized_timeframes:
            raise ValueError("请至少选择一个同步周期。")
        if log_callback is not None:
            log_callback(
                f"miniQMT sync start: timeframes={','.join(normalized_timeframes)} "
                f"stocks={len(stock_codes)} range={pd.Timestamp(start_time):%Y-%m-%d %H:%M:%S} -> {pd.Timestamp(end_time):%Y-%m-%d %H:%M:%S}"
            )
        total_steps = len(stock_codes) * len(normalized_timeframes)
        results_by_timeframe: dict[str, object] = {}
        completed_steps = 0

        for timeframe_value in normalized_timeframes:
            if log_callback is not None:
                log_callback(f"[{timeframe_value}] start {len(stock_codes)} stocks")

            def _progress(event, tf=timeframe_value):
                base_current = completed_steps + int(event.current or 0)
                merged_event = DataSyncProgress(
                    current=base_current,
                    total=total_steps,
                    stock_code=str(event.stock_code or ""),
                    status=f"{tf}:{event.status}",
                    message=str(event.message or ""),
                )
                if log_callback is not None:
                    message = (
                        f"[{tf}][{event.status}] {base_current}/{total_steps} "
                        f"{merged_event.stock_code} {merged_event.message}"
                    ).strip()
                    log_callback(message)
                if progress_callback is not None:
                    progress_callback(merged_event)

            result = DailyKlineSyncService(
                provider=provider,
                duckdb_store=self.store,
                parquet_store=self.parquet_store,
                strict_quality=not allow_quality_issues,
            ).sync(
                stock_codes=stock_codes,
                start_time=start_time,
                end_time=end_time,
                timeframe=timeframe_value,
                resume_from_latest_local=resume_from_latest_local,
                progress_callback=_progress,
            )
            completed_steps += len(stock_codes)
            results_by_timeframe[timeframe_value] = result
            if log_callback is not None:
                log_callback(
                    f"[{timeframe_value}] done rows={result.rows_written} parquet={len(result.parquet_files)} "
                    f"quality={result.quality_issue_count} failed={len(result.failed_stock_codes)} "
                    f"empty={len(result.empty_stock_codes)} skipped={len(result.skipped_stock_codes)}"
                )
        return results_by_timeframe, stock_codes

    def build_baostock_bulk_sync_command(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        fetch_timeframes: list[str],
        derive_source_timeframe: str,
        derive_timeframes: list[str],
        stock_codes_text: str = "",
        market_groups: list[str] | None = None,
        sync_all: bool = False,
        adjustflag: str = "2",
        max_retries: int = 2,
        state_path: str = DEFAULT_BAOSTOCK_STATE_PATH,
        user_id: str = "",
        password: str = "",
        reset_state: bool = False,
        allow_quality_issues: bool = False,
    ) -> list[str]:
        run_config = self.build_baostock_bulk_sync_run_config(
            start_time=start_time,
            end_time=end_time,
            fetch_timeframes=fetch_timeframes,
            derive_source_timeframe=derive_source_timeframe,
            derive_timeframes=derive_timeframes,
            stock_codes_text=stock_codes_text,
            market_groups=market_groups,
            sync_all=sync_all,
            adjustflag=adjustflag,
            max_retries=max_retries,
            user_id=user_id,
            password=password,
        )
        fetch = list(run_config["fetch_timeframes"])
        derive_source = str(run_config["derive_source_timeframe"])
        derive = list(run_config["derive_timeframes"])
        market_groups = list(run_config["market_groups"])
        explicit_stock_codes = list(run_config["stock_codes"])

        if not fetch and not derive:
            raise ValueError("Please choose at least one fetch or derive timeframe.")

        command = [
            sys.executable,
            str(self.workspace_root / "tools" / "baostock_bulk_sync.py"),
            "--db",
            str(self.db_path),
            "--parquet-root",
            str(self.parquet_root),
            "--start",
            str(run_config["start"]),
            "--end",
            str(run_config["end"]),
            "--fetch-timeframes",
            ",".join(fetch),
            "--derive-source-timeframe",
            derive_source,
            "--derive-timeframes",
            ",".join(derive),
            "--adjustflag",
            str(run_config["adjustflag"]),
            "--max-retries",
            str(run_config["max_retries"]),
            "--state-path",
            str(state_path or DEFAULT_BAOSTOCK_STATE_PATH),
        ]
        if bool(run_config["sync_all"]):
            command.append("--sync-all")
        else:
            if market_groups:
                command.extend(["--market-groups", ",".join(market_groups)])
            elif explicit_stock_codes:
                command.extend(["--stock-codes", ",".join(explicit_stock_codes)])
            else:
                raise ValueError("Please choose market groups, input stock codes, or enable sync all.")
        if str(user_id).strip():
            command.extend(["--user-id", str(user_id).strip()])
        if str(password).strip():
            command.extend(["--password", str(password).strip()])
        if reset_state:
            command.append("--reset-state")
        if allow_quality_issues:
            command.append("--allow-quality-issues")
        return command

    def build_baostock_bulk_sync_run_config(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        fetch_timeframes: list[str],
        derive_source_timeframe: str,
        derive_timeframes: list[str],
        stock_codes_text: str = "",
        market_groups: list[str] | None = None,
        sync_all: bool = False,
        adjustflag: str = "2",
        max_retries: int = 2,
        user_id: str = "",
        password: str = "",
    ) -> dict[str, object]:
        fetch = [normalize_timeframe(item) for item in fetch_timeframes if item]
        derive_source = normalize_timeframe(derive_source_timeframe)
        derive = [normalize_timeframe(item) for item in derive_timeframes if item]
        if derive and derive_source not in fetch:
            fetch = [derive_source, *fetch]
        fetch = list(dict.fromkeys(fetch))
        derive = [target for target in dict.fromkeys(derive) if target != derive_source]
        normalized_groups = normalize_market_groups(market_groups or [])
        explicit_stock_codes = self.normalize_stock_codes(self.parse_text_list(stock_codes_text))
        explicit_selection = not sync_all and not normalized_groups

        if explicit_selection and not explicit_stock_codes:
            raise ValueError("Please choose market groups, input stock codes, or enable sync all.")
        return {
            "db": str(self.db_path),
            "parquet_root": str(self.parquet_root),
            "stock_selection_mode": "explicit" if explicit_selection else "market_groups",
            "stock_codes": explicit_stock_codes if explicit_selection else [],
            "sync_all": bool(sync_all),
            "market_groups": normalized_groups,
            "start": pd.Timestamp(start_time).strftime("%Y-%m-%dT%H:%M:%S"),
            "end": pd.Timestamp(end_time).strftime("%Y-%m-%dT%H:%M:%S"),
            "fetch_timeframes": fetch,
            "derive_source_timeframe": derive_source,
            "derive_timeframes": derive,
            "adjustflag": str(adjustflag),
            "user_id": str(user_id).strip(),
            "has_password": bool(str(password).strip()),
            "max_retries": max(0, int(max_retries)),
        }

    def inspect_baostock_state_file(
        self,
        *,
        state_path: str | Path,
        run_config: dict[str, object],
    ) -> dict[str, object]:
        path = Path(state_path)
        if not path.exists():
            return {
                "exists": False,
                "matches": True,
                "path": str(path),
                "message": "State file does not exist yet.",
                "existing_run_config": None,
            }
        state = json.loads(path.read_text(encoding="utf-8"))
        existing_run_config = state.get("run_config", {})
        matches = existing_run_config == run_config
        message = ""
        if not matches:
            message = self.describe_baostock_state_mismatch(
                existing_run_config=existing_run_config,
                run_config=run_config,
            )
        return {
            "exists": True,
            "matches": matches,
            "path": str(path),
            "message": message,
            "created_at": state.get("created_at"),
            "updated_at": state.get("updated_at"),
            "completed": bool(state.get("completed")),
            "existing_run_config": existing_run_config,
        }

    def suggest_baostock_state_path(
        self,
        *,
        state_path: str | Path,
        run_config: dict[str, object],
    ) -> str:
        path = Path(state_path)
        parent = path.parent if str(path.parent) else Path(".")
        stem = path.stem or "baostock_bulk_sync_state"
        suffix = path.suffix or ".json"

        selection_mode = str(run_config.get("stock_selection_mode", "run"))
        market_groups = list(run_config.get("market_groups", []))
        fetch = list(run_config.get("fetch_timeframes", []))
        label_parts: list[str] = []
        if market_groups:
            label_parts.append("-".join(str(item) for item in market_groups[:2]))
        else:
            label_parts.append(selection_mode)
        if fetch:
            label_parts.append("-".join(str(item) for item in fetch[:2]))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = parent / f"{stem}_{'_'.join(label_parts)}_{timestamp}{suffix}"
        return str(candidate)

    @staticmethod
    def describe_baostock_state_mismatch(
        *,
        existing_run_config: dict[str, object],
        run_config: dict[str, object],
    ) -> str:
        existing_summary = LocalDataWorkbenchService._format_baostock_run_config(existing_run_config)
        current_summary = LocalDataWorkbenchService._format_baostock_run_config(run_config)
        return (
            "The selected state file belongs to a different sync task.\n"
            f"Existing: {existing_summary}\n"
            f"Current : {current_summary}\n"
            "The sync tool will re-check local DuckDB coverage on startup and continue from incomplete symbols."
        )

    @staticmethod
    def _format_baostock_run_config(run_config: dict[str, object]) -> str:
        selection_mode = str(run_config.get("stock_selection_mode", ""))
        stock_codes = list(run_config.get("stock_codes", []))
        market_groups = list(run_config.get("market_groups", []))
        if selection_mode == "explicit":
            if len(stock_codes) > 3:
                selection_text = f"explicit:{len(stock_codes)} stocks"
            else:
                selection_text = "explicit:" + ",".join(str(item) for item in stock_codes)
        else:
            if bool(run_config.get("sync_all")):
                selection_text = "sync_all"
            else:
                selection_text = "groups:" + ",".join(str(item) for item in market_groups)
        fetch = ",".join(str(item) for item in run_config.get("fetch_timeframes", []))
        derive = ",".join(str(item) for item in run_config.get("derive_timeframes", []))
        return (
            f"{selection_text}; "
            f"{run_config.get('start')} -> {run_config.get('end')}; "
            f"fetch={fetch}; derive={derive}; "
            f"adjust={run_config.get('adjustflag')}"
        )

    @staticmethod
    def summarize_baostock_state(state_path: str | Path) -> str:
        path = Path(state_path)
        if not path.exists():
            return "状态文件还不存在。"
        state = json.loads(path.read_text(encoding="utf-8"))
        lines = [
            f"状态文件: {path}",
            f"创建时间: {state.get('created_at', '-')}",
            f"更新时间: {state.get('updated_at', '-')}",
            f"是否完成: {'是' if state.get('completed') else '否'}",
        ]
        for phase, sections in state.get("phases", {}).items():
            for timeframe, payload in sections.items():
                completed_count = len(set(payload.get("completed_stock_codes", [])))
                summary_count = len(payload.get("summaries", []))
                done = "是" if payload.get("completed") else "否"
                lines.append(
                    f"{phase}/{timeframe}: 已完成 {completed_count} 只, 记录 {summary_count} 条, 阶段完成 {done}"
                )
        return "\n".join(lines)


def _stringify_timestamp(value: object) -> str | None:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def _stringify_date(value: object) -> str | None:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    return timestamp.strftime("%Y-%m-%d")
