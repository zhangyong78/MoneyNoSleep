from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.parquet_store import ParquetStore
from mns.data.providers.qmt_provider import QMTProvider
from mns.data.sync import DailyKlineSyncService


@dataclass
class BatchSummary:
    timeframe: str
    batch_index: int
    batch_count: int
    stock_count: int
    rows_written: int
    quality_issue_count: int
    synced_stock_count: int
    failed_stock_count: int
    empty_stock_count: int
    skipped_stock_count: int


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _print(message: str) -> None:
    print(f"[{_now_text()}] {message}", flush=True)


def _chunked(items: list[str], chunk_size: int) -> list[list[str]]:
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def _progress_printer(prefix: str):
    def _callback(event) -> None:
        if event.current and event.total:
            _print(f"{prefix} {event.status} {event.current}/{event.total} {event.stock_code} {event.message}".strip())
        else:
            _print(f"{prefix} {event.status} {event.stock_code} {event.message}".strip())

    return _callback


def _load_or_create_state(state_path: Path, *, run_config: dict) -> dict:
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8"))

    state = {
        "created_at": _now_text(),
        "updated_at": _now_text(),
        "run_config": run_config,
        "timeframes": {},
        "completed": False,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")
    return state


def _save_state(state_path: Path, state: dict) -> None:
    state["updated_at"] = _now_text()
    state_path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bulk sync A-share QMT K-line data with resumable batches.")
    parser.add_argument("--db", default="data/duckdb/mns.duckdb")
    parser.add_argument("--parquet-root", default="data/parquet")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD.")
    parser.add_argument("--timeframes", default="15m,30m,1h,1d")
    parser.add_argument("--dividend-type", default="front")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--state-path", default="data/logs/qmt_bulk_sync_state.json")
    parser.add_argument("--log-stock-sample", type=int, default=10)
    parser.add_argument("--allow-quality-issues", action="store_true")
    args = parser.parse_args(argv)

    start_time = datetime.fromisoformat(args.start)
    end_time = datetime.fromisoformat(args.end)
    state_path = Path(args.state_path)
    timeframes = [item.strip() for item in args.timeframes.split(",") if item.strip()]

    provider = QMTProvider(dividend_type=args.dividend_type)
    stock_frame = provider.get_stock_list()
    stock_codes = sorted(stock_frame["stock_code"].dropna().astype(str).tolist())
    if not stock_codes:
        raise RuntimeError("QMT returned no A-share stock codes.")

    run_config = {
        "db": args.db,
        "parquet_root": args.parquet_root,
        "start": args.start,
        "end": args.end,
        "timeframes": timeframes,
        "dividend_type": args.dividend_type,
        "batch_size": args.batch_size,
        "max_workers": args.max_workers,
        "max_retries": args.max_retries,
        "stock_count": len(stock_codes),
    }
    state = _load_or_create_state(state_path, run_config=run_config)

    _print(f"QMT A-share stock count: {len(stock_codes)}")
    _print(f"Stock sample: {', '.join(stock_codes[: max(args.log_stock_sample, 1)])}")
    _print(f"Timeframes: {', '.join(timeframes)}")
    _print(f"Date range: {args.start} -> {args.end}")
    _print(f"State file: {state_path}")

    batches = _chunked(stock_codes, args.batch_size)
    batch_count = len(batches)
    _print(f"Batch size: {args.batch_size}; batch count: {batch_count}")

    for timeframe in timeframes:
        tf_state = state["timeframes"].setdefault(
            timeframe,
            {
                "completed_batches": [],
                "summaries": [],
                "completed": False,
            },
        )
        if tf_state.get("completed"):
            _print(f"Skip timeframe {timeframe}: already completed.")
            continue

        _print(f"Start timeframe {timeframe}")
        for batch_index, batch_codes in enumerate(batches, start=1):
            completed_batches = set(tf_state.get("completed_batches", []))
            if batch_index in completed_batches:
                continue

            prefix = f"[{timeframe}][batch {batch_index}/{batch_count}]"
            _print(f"{prefix} syncing {len(batch_codes)} stocks")
            service = DailyKlineSyncService(
                provider=QMTProvider(dividend_type=args.dividend_type),
                provider_factory=lambda: QMTProvider(dividend_type=args.dividend_type),
                duckdb_store=DuckDBStore(args.db),
                parquet_store=ParquetStore(args.parquet_root),
                strict_quality=not args.allow_quality_issues,
                max_workers=args.max_workers,
                max_retries=args.max_retries,
            )
            result = service.sync(
                stock_codes=batch_codes,
                start_time=start_time,
                end_time=end_time,
                timeframe=timeframe,
                progress_callback=_progress_printer(prefix),
            )
            summary = BatchSummary(
                timeframe=timeframe,
                batch_index=batch_index,
                batch_count=batch_count,
                stock_count=len(batch_codes),
                rows_written=result.rows_written,
                quality_issue_count=result.quality_issue_count,
                synced_stock_count=result.synced_stock_count,
                failed_stock_count=len(result.failed_stock_codes),
                empty_stock_count=len(result.empty_stock_codes),
                skipped_stock_count=len(result.skipped_stock_codes),
            )
            _print(
                f"{prefix} done rows={summary.rows_written} synced={summary.synced_stock_count} "
                f"failed={summary.failed_stock_count} empty={summary.empty_stock_count} skipped={summary.skipped_stock_count}"
            )
            tf_state.setdefault("completed_batches", []).append(batch_index)
            tf_state.setdefault("summaries", []).append(asdict(summary))
            _save_state(state_path, state)

        tf_state["completed"] = True
        _save_state(state_path, state)
        _print(f"Finished timeframe {timeframe}")

    state["completed"] = True
    _save_state(state_path, state)
    _print("Bulk QMT sync completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
