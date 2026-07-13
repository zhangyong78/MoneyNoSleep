from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def load_qmt_sector_snapshot(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load a local raw QMT/exported sector snapshot into sector + mapping frames."""

    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"sector snapshot not found: {target}")

    if target.is_dir():
        return _load_from_dir(target)
    if target.suffix.lower() == ".json":
        return _load_from_json(target)
    if target.suffix.lower() in {".csv", ".tsv"}:
        frame = _read_table(target)
        return _split_flat_frame(frame)
    raise ValueError(f"unsupported sector snapshot format: {target.suffix}")


def _load_from_dir(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    json_candidates = ["sector_snapshot.json", "sectors.json", "sector_dump.json", "qmt_sector_snapshot.json"]
    for name in json_candidates:
        candidate = path / name
        if candidate.exists():
            return _load_from_json(candidate)

    sector_candidates = ["sectors.csv", "sector_list.csv"]
    map_candidates = ["stock_sector_map.csv", "sector_map.csv", "sector_members.csv"]
    sectors = pd.DataFrame()
    sector_map = pd.DataFrame()
    for name in sector_candidates:
        candidate = path / name
        if candidate.exists():
            sectors = _read_table(candidate)
            break
    for name in map_candidates:
        candidate = path / name
        if candidate.exists():
            sector_map = _read_table(candidate)
            break
    if not sectors.empty or not sector_map.empty:
        return sectors, sector_map
    raise ValueError(f"no recognizable sector snapshot files found in: {path}")


def _load_from_json(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        sectors_frame, sector_map_frame = _extract_from_sector_entries(payload)
        return sectors_frame, sector_map_frame
    if not isinstance(payload, dict):
        raise ValueError(f"unsupported sector snapshot JSON structure in: {path}")

    explicit_sectors = payload.get("sectors") or payload.get("sector_list")
    explicit_map = payload.get("stock_sector_map") or payload.get("sector_map") or payload.get("members")
    if explicit_sectors is not None and explicit_map is not None:
        return pd.DataFrame(explicit_sectors), pd.DataFrame(explicit_map)

    nested = payload.get("data") or payload.get("result") or payload.get("payload") or payload
    if isinstance(nested, dict):
        explicit_sectors = nested.get("sectors") or nested.get("sector_list")
        explicit_map = nested.get("stock_sector_map") or nested.get("sector_map") or nested.get("members")
        if explicit_sectors is not None and explicit_map is not None:
            return pd.DataFrame(explicit_sectors), pd.DataFrame(explicit_map)
        candidate_entries = (
            nested.get("items")
            or nested.get("list")
            or nested.get("rows")
            or nested.get("sectors")
            or nested.get("sector_list")
        )
        if isinstance(candidate_entries, list):
            return _extract_from_sector_entries(candidate_entries)
    if isinstance(nested, list):
        return _extract_from_sector_entries(nested)
    raise ValueError(f"unable to parse sector snapshot JSON: {path}")


def _extract_from_sector_entries(entries: list[Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    sector_rows: list[dict[str, Any]] = []
    map_rows: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sector_name = _first(entry, ["sector_name", "name", "板块名称", "板块", "行业名称"])
        source_sector_code = _first(entry, ["source_sector_code", "sector_code", "code", "板块代码", "id"])
        sector_type = _first(entry, ["sector_type", "type", "category", "板块类型"])
        sector_rows.append(
            {
                "sector_name": sector_name,
                "source_sector_code": source_sector_code,
                "sector_type": sector_type,
            }
        )
        members = _first(entry, ["stocks", "members", "constituents", "components", "stock_list", "list"])
        if isinstance(members, list):
            for member in members:
                if isinstance(member, dict):
                    map_rows.append(
                        {
                            "sector_name": sector_name,
                            "sector_type": sector_type,
                            "source_sector_code": source_sector_code,
                            "stock_code": _first(member, ["stock_code", "code", "股票代码", "证券代码"]),
                            "stock_name": _first(member, ["stock_name", "name", "股票名称", "证券简称"]),
                            "start_date": _first(member, ["start_date", "纳入日期"]),
                            "end_date": _first(member, ["end_date", "移除日期"]),
                        }
                    )
                else:
                    map_rows.append(
                        {
                            "sector_name": sector_name,
                            "sector_type": sector_type,
                            "source_sector_code": source_sector_code,
                            "stock_code": member,
                            "stock_name": None,
                            "start_date": None,
                            "end_date": None,
                        }
                    )
    return pd.DataFrame(sector_rows), pd.DataFrame(map_rows)


def _split_flat_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return pd.DataFrame(), pd.DataFrame()
    columns = set(frame.columns)
    stock_code_columns = {"stock_code", "code", "raw_code", "代码", "股票代码", "证券代码"}
    if columns & stock_code_columns:
        sector_name = _first_record_value(frame, ["sector_name", "board_name", "name", "板块名称", "板块", "行业名称"])
        source_sector_code = _first_record_value(frame, ["source_sector_code", "board_code", "sector_code", "code", "板块代码", "id"])
        sector_type = _first_record_value(frame, ["sector_type", "type", "category", "板块类型"]) or "industry"
        sectors = pd.DataFrame(
            [
                {
                    "sector_name": sector_name,
                    "source_sector_code": source_sector_code,
                    "sector_type": sector_type,
                }
            ]
        )
        mappings = frame.copy()
        if "board_name" in mappings.columns and "sector_name" not in mappings.columns:
            mappings["sector_name"] = mappings["board_name"]
        if "board_code" in mappings.columns and "source_sector_code" not in mappings.columns:
            mappings["source_sector_code"] = mappings["board_code"]
        if "sector_type" not in mappings.columns:
            mappings["sector_type"] = sector_type
        return sectors, mappings
    return frame, pd.DataFrame()


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".tsv":
        return pd.read_csv(path, sep="\t")
    return pd.read_csv(path)


def _first(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _first_record_value(frame: pd.DataFrame, keys: list[str]) -> Any:
    for key in keys:
        if key in frame.columns and not frame.empty:
            value = frame.iloc[0][key]
            if pd.notna(value):
                return value
    return None
