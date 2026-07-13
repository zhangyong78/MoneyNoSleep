from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from mns.data.duckdb_store import DuckDBStore
from mns.data.parquet_store import ParquetStore
from mns.data.providers.akshare_provider import AKShareProvider
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


def _parse_stock_codes(stock_codes_text: str, stock_file: str) -> list[str]:
    raw_items: list[str] = []
    if stock_codes_text.strip():
        raw_items.extend(stock_codes_text.replace("\n", ",").split(","))
    if stock_file.strip():
        raw_items.extend(Path(stock_file).read_text(encoding="utf-8").replace("\n", ",").split(","))

    normalized = [
        AKShareProvider.normalize_stock_code(item)
        for item in raw_items
        if str(item).strip()
    ]
    return sorted(dict.fromkeys(normalized))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bulk sync AKShare K-line data with resumable batches.")
    parser.add_argument("--db", default="data/duckdb/mns.duckdb")
    parser.add_argument("--parquet-root", default="data/parquet")
    parser.add_argument("--stock-codes", default="", help="Comma-separated stock codes, e.g. 588000,159915.SZ,600000.SH.")
    parser.add_argument("--stock-file", default="", help="Optional UTF-8 text file with comma-separated or line-separated stock codes.")
    parser.add_argument("--start", required=True, help="Start time, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")
    parser.add_argument("--end", required=True, help="End time, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")
    parser.add_argument("--timeframes", default="15m")
    parser.add_argument("--adjust", default="qfq")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--state-path", default="data/logs/akshare_bulk_sync_state.json")
    parser.add_argument("--log-stock-sample", type=int, default=10)
    parser.add_argument("--allow-quality-issues", action="store_true")
    parser.add_argument("--full-refresh", action="store_true", help="Ignore local latest-trade-date resume and pull the requested range again.")
    args = parser.parse_args(argv)

    stock_codes = _parse_stock_codes(args.stock_codes, args.stock_file)
    if not stock_codes:
        raise RuntimeError("No stock codes provided. Use --stock-codes or --stock-file.")

    start_time = datetime.fromisoformat(args.start)
    end_time = datetime.fromisoformat(args.end)
    timeframes = [item.strip() for item in args.timeframes.split(",") if item.strip()]
    state_path = Path(args.state_path)

    run_config = {
        "db": args.db,
        "parquet_root": args.parquet_root,
        "stock_codes": stock_codes,
        "start": args.start,
        "end": args.end,
        "timeframes": timeframes,
        "adjust": args.adjust,
        "batch_size": args.batch_size,
        "max_workers": args.max_workers,
        "max_retries": args.max_retries,
        "full_refresh": bool(args.full_refresh),
    }
    state = _load_or_create_state(state_path, run_config=run_config)

    _print(f"AKShare stock count: {len(stock_codes)}")
    _print(f"Stock sample: {', '.join(stock_codes[: max(args.log_stock_sample, 1)])}")
    _print(f"Timeframes: {', '.join(timeframes)}")
    _print(f"Date range: {args.start} -> {args.end}")
    _print(f"Adjust: {args.adjust}")
    _print(f"State file: {state_path}")

    batches = _chunked(stock_codes, max(1, args.batch_size))
    batch_count = len(batches)
    _print(f"Batch size: {max(1, args.batch_size)}; batch count: {batch_count}")

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
            _print(f"{prefix} syncing {len(batch_codes)} stocks: {', '.join(batch_codes)}")
            service = DailyKlineSyncService(
                provider=AKShareProvider(adjust=args.adjust),
                provider_factory=lambda: AKShareProvider(adjust=args.adjust),
                duckdb_store=DuckDBStore(args.db),
                parquet_store=ParquetStore(args.parquet_root),
                strict_quality=not args.allow_quality_issues,
                max_workers=max(1, args.max_workers),
                max_retries=max(0, args.max_retries),
            )
            result = service.sync(
                stock_codes=batch_codes,
                start_time=start_time,
                end_time=end_time,
                timeframe=timeframe,
                resume_from_latest_local=not args.full_refresh,
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
    _print("Bulk AKShare sync completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
