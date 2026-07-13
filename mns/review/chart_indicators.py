from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Sequence

import pandas as pd

from mns.config import load_yaml
from mns.factors.technical import ema, ma

IndicatorKind = Literal["ema", "ma"]


@dataclass(frozen=True)
class ChartIndicatorSpec:
    kind: IndicatorKind
    period: int
    color: str
    width: float = 2.0
    label: str | None = None

    @property
    def column_name(self) -> str:
        return f"{self.kind}{self.period}"

    @property
    def display_name(self) -> str:
        return self.label or f"{self.kind.upper()}{self.period}"

    @property
    def min_history_bars(self) -> int:
        if self.kind == "ema":
            return self.period * 3
        return self.period


DEFAULT_PRICE_OVERLAY_INDICATORS: tuple[ChartIndicatorSpec, ...] = (
    ChartIndicatorSpec(kind="ema", period=21, color="#2563eb"),
    ChartIndicatorSpec(kind="ema", period=55, color="#f59e0b"),
)

BUILTIN_PRICE_OVERLAY_INDICATORS: tuple[ChartIndicatorSpec, ...] = (
    *DEFAULT_PRICE_OVERLAY_INDICATORS,
    ChartIndicatorSpec(kind="ma", period=55, color="#16a34a"),
)


def required_indicator_history(indicators: Sequence[ChartIndicatorSpec]) -> int:
    return max((spec.min_history_bars for spec in indicators), default=0)


def add_price_overlay_indicators(frame: pd.DataFrame, indicators: Sequence[ChartIndicatorSpec]) -> pd.DataFrame:
    if frame.empty or not indicators:
        return frame.copy()

    enriched = frame.sort_values("bar_time").copy()
    if "stock_code" in enriched.columns and enriched["stock_code"].nunique(dropna=True) > 1:
        grouped = enriched.groupby("stock_code", group_keys=False)
        for spec in indicators:
            if _has_populated_column(enriched, spec.column_name):
                continue
            enriched[spec.column_name] = grouped["close"].transform(lambda series: _compute_indicator(series, spec))
        return enriched

    close = pd.to_numeric(enriched["close"], errors="coerce")
    for spec in indicators:
        if _has_populated_column(enriched, spec.column_name):
            continue
        enriched[spec.column_name] = _compute_indicator(close, spec)
    return enriched


def _has_populated_column(frame: pd.DataFrame, column_name: str) -> bool:
    return column_name in frame.columns and frame[column_name].notna().any()


def _compute_indicator(close: pd.Series, spec: ChartIndicatorSpec) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce")
    if spec.kind == "ema":
        return ema(close, spec.period)
    if spec.kind == "ma":
        return ma(close, spec.period)
    raise ValueError(f"unsupported indicator kind: {spec.kind}")


def indicator_display_names(indicators: Sequence[ChartIndicatorSpec]) -> list[str]:
    return [spec.display_name for spec in indicators]


def available_price_overlay_indicators(config_path: str | Path = "config/review.yaml") -> tuple[ChartIndicatorSpec, ...]:
    configured = load_default_price_overlay_indicators(config_path)
    merged: dict[str, ChartIndicatorSpec] = {}
    for spec in (*BUILTIN_PRICE_OVERLAY_INDICATORS, *configured):
        merged[_indicator_key(spec.display_name)] = spec
    return tuple(merged.values())


def resolve_price_overlay_indicators(
    selected_names: Sequence[str],
    *,
    config_path: str | Path = "config/review.yaml",
) -> tuple[ChartIndicatorSpec, ...]:
    available = available_price_overlay_indicators(config_path)
    mapping = {_indicator_key(spec.display_name): spec for spec in available}
    resolved = [mapping[key] for key in (_indicator_key(name) for name in selected_names) if key in mapping]
    return tuple(resolved)


@lru_cache(maxsize=8)
def load_default_price_overlay_indicators(config_path: str | Path = "config/review.yaml") -> tuple[ChartIndicatorSpec, ...]:
    path = Path(config_path)
    if not path.exists():
        return DEFAULT_PRICE_OVERLAY_INDICATORS

    chart_config = load_yaml(path).get("chart", {})
    raw_indicators = chart_config.get("price_overlay_indicators")
    if not isinstance(raw_indicators, list):
        return DEFAULT_PRICE_OVERLAY_INDICATORS

    parsed = [_parse_indicator_entry(entry) for entry in raw_indicators]
    resolved = tuple(spec for spec in parsed if spec is not None)
    return resolved or DEFAULT_PRICE_OVERLAY_INDICATORS


def _parse_indicator_entry(entry: object) -> ChartIndicatorSpec | None:
    if isinstance(entry, str):
        builtin = {_indicator_key(spec.display_name): spec for spec in BUILTIN_PRICE_OVERLAY_INDICATORS}
        return builtin.get(_indicator_key(entry))

    if not isinstance(entry, dict):
        return None

    kind = str(entry.get("kind", "")).strip().lower()
    period = entry.get("period")
    if kind not in {"ema", "ma"}:
        return None
    if not isinstance(period, int) or period < 2:
        return None

    matched_builtin = next((spec for spec in BUILTIN_PRICE_OVERLAY_INDICATORS if spec.kind == kind and spec.period == period), None)
    color = str(entry.get("color") or (matched_builtin.color if matched_builtin else "#64748b"))
    width = float(entry.get("width", matched_builtin.width if matched_builtin else 2.0))
    label = entry.get("label")
    return ChartIndicatorSpec(
        kind=kind,
        period=period,
        color=color,
        width=width,
        label=str(label).strip() if isinstance(label, str) and label.strip() else None,
    )


def _indicator_key(name: str) -> str:
    return name.strip().upper()
