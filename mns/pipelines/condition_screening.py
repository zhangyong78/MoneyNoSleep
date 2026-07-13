from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.khquant_cache import (
    A_SHARE_PREFIXES as KHQUANT_A_SHARE_PREFIXES,
    DEFAULT_SCREENING_CACHE_PATH,
)
from mns.pipelines.stock_feature_store import StockFeatureStoreBuilder, StockFeatureStoreConfig


# Re-export shared market prefixes for UI/CLI callers that import this module directly.
A_SHARE_PREFIXES = KHQUANT_A_SHARE_PREFIXES


POSITIVE_FORECAST_TYPES = {
    "预增",
    "略增",
    "扭亏",
    "续盈",
    "预盈",
    "大幅上升",
    "大幅增长",
    "增长",
    "上升",
}

UNIVERSE_LABELS = {
    "all_a": "沪深所有A股",
    "hs300": "沪深300",
    "zz500": "中证500",
    "sz50": "上证50",
}


@dataclass(frozen=True)
class ConditionGroupConfig:
    name: str = "组合1"
    enabled: bool = True
    ema_period: int = 21
    enable_ema_breakout: bool = False
    volume_ma_window: int = 20
    enable_volume_ratio: bool = True
    volume_ratio_min: float = 3.0
    daily_k_angle_window: int = 5
    enable_daily_k_angle: bool = True
    daily_k_angle_min: float = 40.0
    relative_low_window: int = 120
    enable_relative_low: bool = True
    relative_low_position_max: float = 0.30
    enable_earnings_filter: bool = True
    earnings_forecast_change_min: float = 20.0
    earnings_yoy_min: float = 10.0
    enable_price_max: bool = True
    price_max: float = 50.0
    enable_turnover: bool = True
    turnover_min: float = 10.0
    enable_recent_volume_spike: bool = False
    recent_volume_spike_window: int = 20
    recent_volume_spike_min: float = 1_000_000_000.0
    enable_limit_up_count: bool = False
    limit_up_count_window: int = 30
    limit_up_count_min: int = 1
    enable_upper_shadow_count: bool = False
    upper_shadow_window: int = 30
    upper_shadow_threshold_pct: float = 5.0
    upper_shadow_count_min: int = 1
    enable_lower_shadow_count: bool = False
    lower_shadow_window: int = 30
    lower_shadow_threshold_pct: float = 5.0
    lower_shadow_count_min: int = 1
    enable_amount_followup: bool = False
    amount_followup_lookback_window: int = 30
    amount_followup_trigger_min: float = 1_000_000_000.0
    amount_followup_sum_min: float = 5_000_000_000.0
    amount_followup_days: int = 5
    enable_breakout_sequence: bool = False
    breakout_ma20_within_days: int = 10
    breakout_ma55_within_days: int = 5
    hold_days: int = 0
    enable_sector_strength_filter: bool = False
    sector_source: str = ""
    sector_type: str = ""
    max_sector_rank: int = 0
    min_sector_strength_score: float = 0.0
    required_sector_name_keywords: str = ""


@dataclass(frozen=True)
class ConditionScreeningConfig:
    db_path: str = "data/duckdb/mns.duckdb"
    khquant_cache_path: str = DEFAULT_SCREENING_CACHE_PATH
    export_root: str = "data/reports/exports"
    signal_date: str = ""
    universe: str = "all_a"
    exclude_st: bool = True
    combine_mode: str = "any"
    groups: list[ConditionGroupConfig] = field(default_factory=lambda: [ConditionGroupConfig()])


@dataclass(frozen=True)
class ConditionTimelineConfig:
    db_path: str = "data/duckdb/mns.duckdb"
    khquant_cache_path: str = DEFAULT_SCREENING_CACHE_PATH
    export_root: str = "data/reports/exports"
    start_date: str = ""
    end_date: str = ""
    universe: str = "all_a"
    exclude_st: bool = True
    combine_mode: str = "any"
    groups: list[ConditionGroupConfig] = field(default_factory=lambda: [ConditionGroupConfig()])


@dataclass(frozen=True)
class ConditionCombo1Config:
    db_path: str = "data/duckdb/mns.duckdb"
    khquant_cache_path: str = DEFAULT_SCREENING_CACHE_PATH
    export_root: str = "data/reports/exports"
    signal_date: str = ""
    universe: str = "all_a"
    ema_period: int = 21
    enable_ema_breakout: bool = False
    volume_ma_window: int = 20
    enable_volume_ratio: bool = True
    volume_ratio_min: float = 3.0
    daily_k_angle_window: int = 5
    enable_daily_k_angle: bool = True
    daily_k_angle_min: float = 40.0
    relative_low_window: int = 120
    enable_relative_low: bool = True
    relative_low_position_max: float = 0.30
    enable_earnings_filter: bool = True
    earnings_forecast_change_min: float = 20.0
    earnings_yoy_min: float = 10.0
    enable_price_max: bool = True
    price_max: float = 50.0
    enable_turnover: bool = True
    turnover_min: float = 10.0
    enable_recent_volume_spike: bool = False
    recent_volume_spike_window: int = 20
    recent_volume_spike_min: float = 1_000_000_000.0
    enable_limit_up_count: bool = False
    limit_up_count_window: int = 30
    limit_up_count_min: int = 1
    enable_upper_shadow_count: bool = False
    upper_shadow_window: int = 30
    upper_shadow_threshold_pct: float = 5.0
    upper_shadow_count_min: int = 1
    enable_lower_shadow_count: bool = False
    lower_shadow_window: int = 30
    lower_shadow_threshold_pct: float = 5.0
    lower_shadow_count_min: int = 1
    enable_amount_followup: bool = False
    amount_followup_lookback_window: int = 30
    amount_followup_trigger_min: float = 1_000_000_000.0
    amount_followup_sum_min: float = 5_000_000_000.0
    amount_followup_days: int = 5
    enable_breakout_sequence: bool = False
    breakout_ma20_within_days: int = 10
    breakout_ma55_within_days: int = 5
    hold_days: int = 0
    exclude_st: bool = True
    enable_sector_strength_filter: bool = False
    sector_source: str = ""
    sector_type: str = ""
    max_sector_rank: int = 0
    min_sector_strength_score: float = 0.0
    required_sector_name_keywords: str = ""


def calculate_daily_k_slope_pct(values) -> float:
    window = np.asarray(values, dtype=float)
    if window.size == 0 or np.isnan(window).any():
        return float("nan")
    base_price = window[0]
    if not np.isfinite(base_price) or abs(base_price) < 1e-12:
        return float("nan")
    normalized = window / base_price
    slope = float(np.polyfit(np.arange(window.size, dtype=float), normalized, deg=1)[0])
    return slope * 100.0


def slope_pct_to_angle(slope_pct: float) -> float:
    if pd.isna(slope_pct):
        return float("nan")
    return float(math.degrees(math.atan(float(slope_pct))))


def _normalize_group(group: ConditionGroupConfig) -> ConditionGroupConfig:
    return ConditionGroupConfig(
        name=group.name or "组合",
        enabled=bool(group.enabled),
        ema_period=max(2, int(group.ema_period)),
        enable_ema_breakout=bool(group.enable_ema_breakout),
        volume_ma_window=max(2, int(group.volume_ma_window)),
        enable_volume_ratio=bool(group.enable_volume_ratio),
        volume_ratio_min=float(group.volume_ratio_min),
        daily_k_angle_window=max(2, int(group.daily_k_angle_window)),
        enable_daily_k_angle=bool(group.enable_daily_k_angle),
        daily_k_angle_min=float(group.daily_k_angle_min),
        relative_low_window=max(2, int(group.relative_low_window)),
        enable_relative_low=bool(group.enable_relative_low),
        relative_low_position_max=min(1.0, max(0.0, float(group.relative_low_position_max))),
        enable_earnings_filter=bool(group.enable_earnings_filter),
        earnings_forecast_change_min=max(0.0, float(group.earnings_forecast_change_min)),
        earnings_yoy_min=max(0.0, float(group.earnings_yoy_min)),
        enable_price_max=bool(group.enable_price_max),
        price_max=max(0.0, float(group.price_max)),
        enable_turnover=bool(group.enable_turnover),
        turnover_min=max(0.0, float(group.turnover_min)),
        enable_recent_volume_spike=bool(group.enable_recent_volume_spike),
        recent_volume_spike_window=max(2, int(group.recent_volume_spike_window)),
        recent_volume_spike_min=max(0.0, float(group.recent_volume_spike_min)),
        enable_limit_up_count=bool(group.enable_limit_up_count),
        limit_up_count_window=max(2, int(group.limit_up_count_window)),
        limit_up_count_min=max(0, int(group.limit_up_count_min)),
        enable_upper_shadow_count=bool(group.enable_upper_shadow_count),
        upper_shadow_window=max(2, int(group.upper_shadow_window)),
        upper_shadow_threshold_pct=max(0.0, float(group.upper_shadow_threshold_pct)),
        upper_shadow_count_min=max(0, int(group.upper_shadow_count_min)),
        enable_lower_shadow_count=bool(group.enable_lower_shadow_count),
        lower_shadow_window=max(2, int(group.lower_shadow_window)),
        lower_shadow_threshold_pct=max(0.0, float(group.lower_shadow_threshold_pct)),
        lower_shadow_count_min=max(0, int(group.lower_shadow_count_min)),
        enable_amount_followup=bool(group.enable_amount_followup),
        amount_followup_lookback_window=max(2, int(group.amount_followup_lookback_window)),
        amount_followup_trigger_min=max(0.0, float(group.amount_followup_trigger_min)),
        amount_followup_sum_min=max(0.0, float(group.amount_followup_sum_min)),
        amount_followup_days=max(1, int(group.amount_followup_days)),
        enable_breakout_sequence=bool(group.enable_breakout_sequence),
        breakout_ma20_within_days=max(1, int(group.breakout_ma20_within_days)),
        breakout_ma55_within_days=max(1, int(group.breakout_ma55_within_days)),
        hold_days=max(0, int(group.hold_days)),
        enable_sector_strength_filter=bool(group.enable_sector_strength_filter),
        sector_source=str(group.sector_source or "").strip(),
        sector_type=str(group.sector_type or "").strip(),
        max_sector_rank=max(0, int(group.max_sector_rank)),
        min_sector_strength_score=float(group.min_sector_strength_score),
        required_sector_name_keywords=str(group.required_sector_name_keywords or "").strip(),
    )


def _rule_label(group: ConditionGroupConfig) -> str:
    parts: list[str] = []
    if group.enable_ema_breakout:
        parts.append(f"收盘上穿EMA{group.ema_period}")
    if group.enable_volume_ratio:
        parts.append(f"量比>={group.volume_ratio_min:.2f}")
    if group.enable_daily_k_angle:
        parts.append(f"日K角度({group.daily_k_angle_window}日)>={group.daily_k_angle_min:.2f}度")
    if group.enable_relative_low:
        parts.append(f"近{group.relative_low_window}日区间位置<={group.relative_low_position_max:.2%}")
    if group.enable_earnings_filter:
        parts.append(f"业绩预告>={group.earnings_forecast_change_min:.2f}%或同比>={group.earnings_yoy_min:.2f}%")
    if group.enable_price_max:
        parts.append(f"股价<{group.price_max:.2f}")
    if group.enable_turnover:
        parts.append(f"换手率<={group.turnover_min:.2f}%")
    if group.enable_recent_volume_spike:
        parts.append(f"最近{group.recent_volume_spike_window}天内有一天成交额>={group.recent_volume_spike_min / 100000000:.2f}亿")
    if group.enable_limit_up_count:
        parts.append(f"近{group.limit_up_count_window}天涨停次数>={group.limit_up_count_min}")
    if group.enable_upper_shadow_count:
        parts.append(f"近{group.upper_shadow_window}天上影线>={group.upper_shadow_threshold_pct:.2f}%次数>={group.upper_shadow_count_min}")
    if group.enable_lower_shadow_count:
        parts.append(f"近{group.lower_shadow_window}天下影线>={group.lower_shadow_threshold_pct:.2f}%次数>={group.lower_shadow_count_min}")
    if group.enable_amount_followup:
        parts.append(
            f"近{group.amount_followup_lookback_window}天存在成交额>={group.amount_followup_trigger_min / 100000000:.2f}亿且后{group.amount_followup_days}日成交额和>={group.amount_followup_sum_min / 100000000:.2f}亿"
        )
    if group.enable_breakout_sequence:
        parts.append(f"近{group.breakout_ma20_within_days}天突破MA20且近{group.breakout_ma55_within_days}天突破MA55")
    if group.enable_sector_strength_filter:
        sector_parts: list[str] = []
        if group.sector_source:
            sector_parts.append(f"source={group.sector_source}")
        if group.sector_type:
            sector_parts.append(f"type={group.sector_type}")
        if group.max_sector_rank > 0:
            sector_parts.append(f"rank<={group.max_sector_rank}")
        if group.min_sector_strength_score > 0:
            sector_parts.append(f"score>={group.min_sector_strength_score:.2f}")
        if group.required_sector_name_keywords:
            sector_parts.append(f"keywords={group.required_sector_name_keywords}")
        parts.append("板块强度(" + ",".join(sector_parts or ["enabled"]) + ")")
    return " + ".join(parts) if parts else "无额外过滤"


def _enabled_filters(group: ConditionGroupConfig) -> list[str]:
    filters: list[str] = []
    if group.enable_ema_breakout:
        filters.append("ema_breakout")
    if group.enable_volume_ratio:
        filters.append("volume_ratio")
    if group.enable_daily_k_angle:
        filters.append("daily_k_angle")
    if group.enable_relative_low:
        filters.append("relative_low")
    if group.enable_earnings_filter:
        filters.append("earnings")
    if group.enable_price_max:
        filters.append("price_max")
    if group.enable_turnover:
        filters.append("turnover")
    if group.enable_recent_volume_spike:
        filters.append("recent_volume_spike")
    if group.enable_limit_up_count:
        filters.append("limit_up_count")
    if group.enable_upper_shadow_count:
        filters.append("upper_shadow_count")
    if group.enable_lower_shadow_count:
        filters.append("lower_shadow_count")
    if group.enable_amount_followup:
        filters.append("amount_followup")
    if group.enable_breakout_sequence:
        filters.append("breakout_sequence")
    if group.enable_sector_strength_filter:
        filters.append("sector_strength")
    return filters


def _merge_asof_by_stock(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    right_date_column: str,
    fill_columns: list[str],
) -> pd.DataFrame:
    if right.empty:
        output = left.copy()
        for column in fill_columns:
            output[column] = pd.NaT if column.endswith("_date") else np.nan
        return output

    merged_parts: list[pd.DataFrame] = []
    for stock_code, left_group in left.groupby("stock_code", sort=False):
        right_group = right[right["stock_code"] == stock_code].copy()
        if right_group.empty:
            part = left_group.copy()
            for column in fill_columns:
                part[column] = pd.NaT if column.endswith("_date") else np.nan
            merged_parts.append(part)
            continue

        left_sorted = left_group.sort_values("date").copy()
        right_sorted = right_group.sort_values(right_date_column).copy()
        right_sorted = right_sorted.drop(columns=["stock_code", "code"], errors="ignore")
        merged = pd.merge_asof(
            left_sorted,
            right_sorted,
            left_on="date",
            right_on=right_date_column,
            direction="backward",
        )
        merged_parts.append(merged)
    return pd.concat(merged_parts, ignore_index=True) if merged_parts else left.copy()


class ConditionScreeningRunner:
    def __init__(self, config: ConditionScreeningConfig) -> None:
        self.config = config
        self.store = DuckDBStore(config.db_path)

    def run(self) -> dict[str, object]:
        config = self._normalized_config()
        config = self._resolved_config_date(config)
        universe_df = self._load_universe(signal_date=config.signal_date, universe=config.universe, exclude_st=config.exclude_st)
        if universe_df.empty:
            raise ValueError(f"No stocks found for universe={config.universe} on {config.signal_date}.")

        history = self._load_history(
            codes=universe_df["code"].astype(str).tolist(),
            start_date=config.signal_date,
            end_date=config.signal_date,
            groups=config.groups,
        )
        earnings_bundle = self._load_earnings_bundle(
            codes=history["stock_code"].drop_duplicates().astype(str).tolist(),
            end_date=config.signal_date,
        )
        group_hits = [
            self._evaluate_group(history, group, target_dates=[config.signal_date], earnings_bundle=earnings_bundle)
            for group in config.groups
        ]
        combined_hits = self._combine_group_hits(group_hits, combine_mode=config.combine_mode, required_groups=len(config.groups))

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        cache_info = self._get_local_cache_info(exclude_st=config.exclude_st)
        summary = {
            "signal_date": config.signal_date,
            "universe": config.universe,
            "universe_label": UNIVERSE_LABELS.get(config.universe, config.universe),
            "universe_size": int(len(universe_df)),
            "hit_count": int(len(combined_hits)),
            "latest_cache_date": cache_info.latest_trade_date,
            "cache_stock_count": int(cache_info.stock_count),
            "combine_mode": config.combine_mode,
            "group_count": int(len(config.groups)),
        }

        export_root = Path(config.export_root)
        export_root.mkdir(parents=True, exist_ok=True)
        export_path = export_root / f"{run_id}_screening_hits.csv"
        combined_hits.to_csv(export_path, index=False)

        self.store.replace_screening_rule_run(
            run_id=run_id,
            screening_date=config.signal_date,
            strategy_name="condition_screening",
            universe=config.universe,
            timeframe="1d",
            config=self._config_payload(config),
            result=summary,
        )
        self.store.replace_screening_rule_hits(run_id, combined_hits)

        return {
            "run_id": run_id,
            "hits": combined_hits,
            "summary": summary,
            "group_hits": group_hits,
            "export_path": export_path,
        }

    def _normalized_config(self) -> ConditionScreeningConfig:
        groups = [_normalize_group(group) for group in self.config.groups if bool(group.enabled)]
        if not groups:
            raise ValueError("At least one enabled condition group is required.")
        combine_mode = str(self.config.combine_mode or "any").lower()
        if combine_mode not in {"any", "all"}:
            combine_mode = "any"
        return ConditionScreeningConfig(
            db_path=self.config.db_path,
            khquant_cache_path=self.config.khquant_cache_path,
            export_root=self.config.export_root,
            signal_date=str(pd.Timestamp(self.config.signal_date).date()),
            universe=self.config.universe,
            exclude_st=bool(self.config.exclude_st),
            combine_mode=combine_mode,
            groups=groups,
        )

    def _resolved_config_date(self, config: ConditionScreeningConfig) -> ConditionScreeningConfig:
        resolved_signal_date = self._resolve_signal_date(config.signal_date)
        if resolved_signal_date is None:
            raise ValueError(f"No available trade date on or before {config.signal_date}.")
        if resolved_signal_date == config.signal_date:
            return config
        return ConditionScreeningConfig(
            db_path=config.db_path,
            khquant_cache_path=config.khquant_cache_path,
            export_root=config.export_root,
            signal_date=resolved_signal_date,
            universe=config.universe,
            exclude_st=config.exclude_st,
            combine_mode=config.combine_mode,
            groups=config.groups,
        )

    @staticmethod
    def _config_payload(config: ConditionScreeningConfig) -> dict:
        payload = asdict(config)
        payload["groups"] = [asdict(group) for group in config.groups]
        return payload

    def _table_exists(self, table_name: str) -> bool:
        frame = self.store.query_frame(
            """
            SELECT COUNT(*) AS table_count
            FROM information_schema.tables
            WHERE table_name = ?
            """,
            (table_name,),
        )
        return bool(int(frame.iloc[0]["table_count"])) if not frame.empty else False

    def _resolve_signal_date(self, signal_date: str) -> str | None:
        frame = self.store.query_frame(
            """
            SELECT MAX(trade_date) AS trade_date
            FROM kline_bars
            WHERE timeframe = '1d' AND trade_date <= ?
            """,
            (signal_date,),
        )
        if frame.empty:
            return None
        value = frame.iloc[0]["trade_date"]
        if pd.isna(value):
            return None
        return str(pd.Timestamp(value).date())

    def _ensure_feature_store(self, *, end_date: str) -> None:
        if not self._table_exists("stock_daily_features") or not self._table_exists("stock_daily_followups"):
            StockFeatureStoreBuilder(
                StockFeatureStoreConfig(
                    db_path=self.config.db_path,
                    end_date=end_date,
                )
            ).run()
            return

        frame = self.store.query_frame(
            """
            SELECT MAX(trade_date) AS latest_trade_date
            FROM stock_daily_features
            WHERE timeframe = '1d'
            """
        )
        latest_trade_date = None if frame.empty else frame.iloc[0]["latest_trade_date"]
        if latest_trade_date is None or pd.isna(latest_trade_date) or str(pd.Timestamp(latest_trade_date).date()) < end_date:
            StockFeatureStoreBuilder(
                StockFeatureStoreConfig(
                    db_path=self.config.db_path,
                    end_date=end_date,
                )
            ).run()

    def _get_local_cache_info(self, *, exclude_st: bool = True):
        latest_trade_date = self._resolve_signal_date("2999-12-31")
        if latest_trade_date is None:
            return type("LocalCacheInfo", (), {"latest_trade_date": None, "stock_count": 0})()
        universe_df = self._load_universe(signal_date=latest_trade_date, universe="all_a", exclude_st=exclude_st)
        return type(
            "LocalCacheInfo",
            (),
            {"latest_trade_date": latest_trade_date, "stock_count": int(len(universe_df))},
        )()

    def _load_universe(self, *, signal_date: str, universe: str, exclude_st: bool) -> pd.DataFrame:
        universe_name = universe if universe and universe != "all_a" and self._table_exists("universe_members") else "all_a"
        st_filter = "AND COALESCE(s.is_st, FALSE) = FALSE" if exclude_st else ""
        a_share_filter = " OR ".join([f"b.stock_code LIKE '{prefix[3:]}%'" for prefix in A_SHARE_PREFIXES])
        if universe_name == "all_a":
            return self.store.query_frame(
                f"""
                SELECT DISTINCT
                    b.stock_code AS code,
                    COALESCE(s.stock_name, b.stock_name, b.stock_code) AS name
                FROM kline_bars AS b
                LEFT JOIN securities AS s ON s.stock_code = b.stock_code
                WHERE b.timeframe = '1d'
                  AND b.trade_date = ?
                  {st_filter}
                  AND ({a_share_filter})
                ORDER BY b.stock_code
                """,
                (signal_date,),
            )
        return self.store.query_frame(
            f"""
            WITH latest_snapshot AS (
                SELECT MAX(snapshot_date) AS snapshot_date
                FROM universe_members
                WHERE universe = ? AND snapshot_date <= ?
            )
            SELECT
                u.code AS code,
                COALESCE(s.stock_name, u.name, u.code) AS name
            FROM universe_members AS u
            CROSS JOIN latest_snapshot AS ls
            LEFT JOIN securities AS s ON s.stock_code = u.code
            WHERE u.universe = ?
              AND u.snapshot_date = ls.snapshot_date
              {st_filter}
            ORDER BY u.code
            """,
            (universe_name, signal_date, universe_name),
        )

    def _load_history(self, *, codes: list[str], start_date: str, end_date: str, groups: list[ConditionGroupConfig]) -> pd.DataFrame:
        lookback_days = max(
            max(group.relative_low_window for group in groups),
            max(group.volume_ma_window + 2 for group in groups),
            max(group.daily_k_angle_window + 2 for group in groups),
            max(group.ema_period * 3 for group in groups),
            max(group.limit_up_count_window + 2 for group in groups),
            max(group.upper_shadow_window + 2 for group in groups),
            max(group.lower_shadow_window + 2 for group in groups),
            max(group.amount_followup_lookback_window + group.amount_followup_days + 2 for group in groups),
            max(group.breakout_ma20_within_days + group.breakout_ma55_within_days + 2 for group in groups),
            160,
        )
        start_text = str((pd.Timestamp(start_date) - pd.Timedelta(days=lookback_days * 2)).date())
        end_buffer = max(max(group.hold_days for group in groups) + 3, 3)
        end_text = str((pd.Timestamp(end_date) + pd.Timedelta(days=end_buffer)).date())
        self._ensure_feature_store(end_date=end_text)
        history = self.store.query_frame(
            """
            SELECT
                b.stock_code,
                COALESCE(NULLIF(b.stock_name, ''), b.stock_code) AS stock_name,
                b.trade_date AS date,
                b.open,
                b.high,
                b.low,
                b.close,
                b.volume,
                b.amount,
                b.turnover AS turn,
                f.upper_shadow_pct,
                f.lower_shadow_pct,
                f.body_pct,
                f.amplitude_pct,
                f.ma20,
                f.ma55,
                f.ma120,
                f.break_ma20_today,
                f.break_ma55_today,
                f.last_break_ma20_date,
                f.last_break_ma55_date,
                f.days_since_break_ma20,
                f.days_since_break_ma55,
                f.limit_up,
                f.limit_down,
                p.available_date_5d,
                p.amount_sum_next_5d,
                p.return_next_5d,
                p.max_return_next_5d,
                p.limit_up_count_next_5d
            FROM kline_bars AS b
            LEFT JOIN stock_daily_features AS f
              ON f.stock_code = b.stock_code
             AND f.trade_date = b.trade_date
             AND f.timeframe = b.timeframe
            LEFT JOIN stock_daily_followups AS p
              ON p.stock_code = b.stock_code
             AND p.anchor_date = b.trade_date
             AND p.timeframe = b.timeframe
            WHERE b.timeframe = '1d'
              AND b.stock_code IN (SELECT UNNEST(?))
              AND b.trade_date BETWEEN ? AND ?
            ORDER BY b.stock_code, b.trade_date
            """,
            (codes, start_text, end_text),
        )
        if history.empty:
            raise ValueError("No local daily history was loaded for the selected universe.")
        history["date"] = pd.to_datetime(history["date"])
        for column in ("last_break_ma20_date", "last_break_ma55_date", "available_date_5d"):
            if column in history.columns:
                history[column] = pd.to_datetime(history[column], errors="coerce")
        return history

    def _load_sector_context(self, *, target_dates: list[str], group: ConditionGroupConfig) -> pd.DataFrame:
        if not group.enable_sector_strength_filter:
            return pd.DataFrame()
        if not self._table_exists("stock_sector_map") or not self._table_exists("sector_strength"):
            raise ValueError("板块强度过滤已启用，但本地板块库不存在。请先运行 `python -m mns sync-sector-data ...`。")

        clauses = [
            "s.trade_date IN (SELECT CAST(UNNEST(?) AS DATE))",
            "(m.start_date IS NULL OR m.start_date <= s.trade_date)",
            "(m.end_date IS NULL OR m.end_date >= s.trade_date)",
        ]
        params: list[object] = [target_dates]
        if group.sector_source:
            clauses.append("m.source = ?")
            params.append(group.sector_source)
        if group.sector_type:
            clauses.append("m.sector_type = ?")
            params.append(group.sector_type)

        frame = self.store.query_frame(
            f"""
            SELECT
                m.stock_code,
                CAST(s.trade_date AS VARCHAR) AS trade_date,
                m.sector_id,
                m.sector_name AS primary_sector_name,
                m.sector_type AS primary_sector_type,
                m.source AS sector_source,
                s.strength_score AS sector_strength_score,
                s.rank AS sector_rank
            FROM stock_sector_map AS m
            INNER JOIN sector_strength AS s
                ON s.sector_id = m.sector_id
               AND s.source = m.source
            WHERE {" AND ".join(clauses)}
            """,
            tuple(params),
        )
        if frame.empty:
            return frame

        keywords = [item.strip() for item in str(group.required_sector_name_keywords or "").replace("，", ",").split(",") if item.strip()]
        if keywords:
            pattern = "|".join(keywords)
            frame = frame.loc[frame["primary_sector_name"].astype(str).str.contains(pattern, case=False, na=False)].copy()
        if frame.empty:
            return frame
        frame = frame.sort_values(
            ["trade_date", "stock_code", "sector_rank", "sector_strength_score", "primary_sector_name"],
            ascending=[True, True, True, False, True],
        )
        return frame.drop_duplicates(subset=["trade_date", "stock_code"], keep="first").reset_index(drop=True)

    def _load_earnings_bundle(self, *, codes: list[str], end_date: str) -> dict[str, pd.DataFrame]:
        if not codes:
            return {"forecast": pd.DataFrame(), "express": pd.DataFrame(), "growth": pd.DataFrame()}
        empty_bundle = {"forecast": pd.DataFrame(), "express": pd.DataFrame(), "growth": pd.DataFrame()}
        if not self._table_exists("forecast_reports") and not self._table_exists("performance_express_reports") and not self._table_exists("growth_reports"):
            return empty_bundle
        return empty_bundle

    def _attach_earnings(self, signal_rows: pd.DataFrame, group: ConditionGroupConfig, earnings_bundle: dict[str, pd.DataFrame]) -> pd.DataFrame:
        output = signal_rows.copy()
        earnings_available = any(not earnings_bundle.get(name, pd.DataFrame()).empty for name in ("forecast", "express", "growth"))
        if group.enable_earnings_filter and earnings_available:
            output = _merge_asof_by_stock(
                output,
                earnings_bundle.get("forecast", pd.DataFrame()),
                right_date_column="forecast_pub_date",
                fill_columns=[
                    "forecast_pub_date",
                    "forecast_stat_date",
                    "forecast_type",
                    "forecast_chg_pct_up",
                    "forecast_chg_pct_dwn",
                ],
            )
            output = _merge_asof_by_stock(
                output,
                earnings_bundle.get("express", pd.DataFrame()),
                right_date_column="express_pub_date",
                fill_columns=[
                    "express_pub_date",
                    "express_stat_date",
                    "express_gryoy",
                    "express_opyoy",
                ],
            )
            output = _merge_asof_by_stock(
                output,
                earnings_bundle.get("growth", pd.DataFrame()),
                right_date_column="growth_pub_date",
                fill_columns=[
                    "growth_pub_date",
                    "growth_stat_date",
                    "growth_yoy_ni",
                ],
            )
        else:
            output["forecast_pub_date"] = pd.NaT
            output["forecast_stat_date"] = pd.NaT
            output["forecast_type"] = ""
            output["forecast_chg_pct_up"] = np.nan
            output["forecast_chg_pct_dwn"] = np.nan
            output["express_pub_date"] = pd.NaT
            output["express_stat_date"] = pd.NaT
            output["express_gryoy"] = np.nan
            output["express_opyoy"] = np.nan
            output["growth_pub_date"] = pd.NaT
            output["growth_stat_date"] = pd.NaT
            output["growth_yoy_ni"] = np.nan
        return output

    @staticmethod
    def _rolling_flag_count(grouped, source: pd.Series, window: int) -> pd.Series:
        return grouped[source.name].transform(lambda series: series.fillna(False).astype(int).rolling(window).sum())

    @staticmethod
    def _matured_amount_followup_pass(grouped_frame: pd.DataFrame, group: ConditionGroupConfig) -> pd.Series:
        values = pd.Series(False, index=grouped_frame.index)
        for _, stock_frame in grouped_frame.groupby("stock_code", sort=False):
            stock_frame = stock_frame.sort_values("date")
            stock_values = np.zeros(len(stock_frame), dtype=bool)
            dates = stock_frame["date"].to_numpy(dtype="datetime64[ns]")
            available_dates = pd.to_datetime(stock_frame["available_date_5d"], errors="coerce").to_numpy(dtype="datetime64[ns]")
            anchor_pass = (
                stock_frame["amount"].fillna(0).to_numpy() >= group.amount_followup_trigger_min
            ) & (
                stock_frame["amount_sum_next_5d"].fillna(-1).to_numpy() >= group.amount_followup_sum_min
            ) & pd.notna(stock_frame["available_date_5d"]).to_numpy()

            for idx in range(len(stock_frame)):
                start = max(0, idx - group.amount_followup_lookback_window + 1)
                window_mask = anchor_pass[start : idx + 1] & (available_dates[start : idx + 1] <= dates[idx])
                stock_values[idx] = bool(window_mask.any())

            values.loc[stock_frame.index] = stock_values
        return values

    def _evaluate_group(
        self,
        history: pd.DataFrame,
        group: ConditionGroupConfig,
        *,
        target_dates: list[str],
        earnings_bundle: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        frame = history.copy().sort_values(["stock_code", "date"]).reset_index(drop=True)
        grouped = frame.groupby("stock_code", sort=False)

        frame["prev_close"] = grouped["close"].shift(1)
        frame["ema_value"] = grouped["close"].transform(lambda series: series.ewm(span=group.ema_period, adjust=False).mean())
        frame["prev_ema"] = grouped["ema_value"].shift(1)
        frame["volume_ratio"] = grouped["volume"].transform(
            lambda series: series / series.shift(1).rolling(group.volume_ma_window).mean()
        )
        frame["daily_k_slope_pct"] = (
            grouped["close"]
            .apply(lambda series: series.rolling(group.daily_k_angle_window).apply(calculate_daily_k_slope_pct, raw=True))
            .reset_index(level=0, drop=True)
        )
        frame["daily_k_angle"] = frame["daily_k_slope_pct"].apply(slope_pct_to_angle)
        rolling_low = grouped["low"].transform(lambda series: series.rolling(group.relative_low_window).min())
        rolling_high = grouped["high"].transform(lambda series: series.rolling(group.relative_low_window).max())
        range_span = rolling_high - rolling_low
        frame["relative_low_position"] = np.where(
            range_span.abs() < 1e-12,
            0.0,
            (frame["close"] - rolling_low) / range_span,
        )
        frame["turnover_rate"] = frame["turn"]
        frame["breakout_pct"] = frame["close"] / frame["ema_value"] - 1.0
        frame["recent_amount_max"] = grouped["amount"].transform(
            lambda series: series.rolling(group.recent_volume_spike_window).max()
        )
        frame["limit_up_count_recent"] = grouped["limit_up"].transform(
            lambda series: series.fillna(False).astype(int).rolling(group.limit_up_count_window).sum()
        )
        frame["upper_shadow_count_recent"] = grouped["upper_shadow_pct"].transform(
            lambda series: (series.fillna(0) >= group.upper_shadow_threshold_pct / 100.0).astype(int).rolling(group.upper_shadow_window).sum()
        )
        frame["lower_shadow_count_recent"] = grouped["lower_shadow_pct"].transform(
            lambda series: (series.fillna(0) >= group.lower_shadow_threshold_pct / 100.0).astype(int).rolling(group.lower_shadow_window).sum()
        )
        frame["amount_followup_pass_recent"] = self._matured_amount_followup_pass(frame, group)
        frame["breakout_sequence_pass"] = (
            frame["days_since_break_ma20"].notna()
            & frame["days_since_break_ma55"].notna()
            & (frame["days_since_break_ma20"] <= group.breakout_ma20_within_days)
            & (frame["days_since_break_ma55"] <= group.breakout_ma55_within_days)
            & frame["last_break_ma20_date"].notna()
            & frame["last_break_ma55_date"].notna()
            & (frame["last_break_ma55_date"] >= frame["last_break_ma20_date"])
        )

        if group.hold_days > 0:
            frame["buy_date"] = grouped["date"].shift(-1)
            frame["buy_open"] = grouped["open"].shift(-1)
            frame["sell_date"] = grouped["date"].shift(-group.hold_days)
            frame["sell_close"] = grouped["close"].shift(-group.hold_days)
            frame["hold_return_pct"] = frame["sell_close"] / frame["buy_open"] - 1.0
        else:
            frame["buy_date"] = pd.NaT
            frame["buy_open"] = np.nan
            frame["sell_date"] = pd.NaT
            frame["sell_close"] = np.nan
            frame["hold_return_pct"] = np.nan

        target_set = {str(pd.Timestamp(value).date()) for value in target_dates}
        signal_rows = frame[frame["date"].dt.date.astype(str).isin(target_set)].copy()
        if signal_rows.empty:
            return pd.DataFrame()
        signal_rows["trade_date"] = signal_rows["date"].dt.date.astype(str)

        sector_context = self._load_sector_context(target_dates=sorted(target_set), group=group)
        if not sector_context.empty:
            signal_rows = signal_rows.merge(
                sector_context,
                on=["trade_date", "stock_code"],
                how="left",
            )
        else:
            signal_rows["sector_id"] = None
            signal_rows["primary_sector_name"] = None
            signal_rows["primary_sector_type"] = None
            signal_rows["sector_source"] = None
            signal_rows["sector_strength_score"] = np.nan
            signal_rows["sector_rank"] = np.nan

        earnings_available = any(not earnings_bundle.get(name, pd.DataFrame()).empty for name in ("forecast", "express", "growth"))
        signal_rows = self._attach_earnings(signal_rows, group, earnings_bundle)
        signal_rows["signal_change_pct"] = signal_rows["close"] / signal_rows["prev_close"] - 1.0
        signal_rows["forecast_chg_pct_max"] = signal_rows[["forecast_chg_pct_up", "forecast_chg_pct_dwn"]].max(
            axis=1,
            skipna=True,
        )
        earnings_yoy_threshold = group.earnings_yoy_min / 100.0
        signal_rows["forecast_pass"] = (
            signal_rows["forecast_type"].fillna("").isin(POSITIVE_FORECAST_TYPES)
            & signal_rows["forecast_chg_pct_max"].notna()
            & (signal_rows["forecast_chg_pct_max"] >= group.earnings_forecast_change_min)
        )
        signal_rows["express_pass"] = (
            signal_rows["express_gryoy"].notna()
            & signal_rows["express_opyoy"].notna()
            & (signal_rows["express_gryoy"] >= earnings_yoy_threshold)
            & (signal_rows["express_opyoy"] >= earnings_yoy_threshold)
        )
        signal_rows["growth_pass"] = signal_rows["growth_yoy_ni"].notna() & (
            signal_rows["growth_yoy_ni"] >= earnings_yoy_threshold
        )

        conditions: list[tuple[str, pd.Series, str]] = []
        if group.enable_ema_breakout:
            conditions.append(
                (
                    "ema_breakout",
                    signal_rows["ema_value"].notna()
                    & signal_rows["prev_ema"].notna()
                    & (signal_rows["prev_close"] <= signal_rows["prev_ema"])
                    & (signal_rows["close"] > signal_rows["ema_value"]),
                    f"收盘上穿EMA{group.ema_period}",
                )
            )
        if group.enable_volume_ratio:
            conditions.append(("volume_ratio", signal_rows["volume_ratio"] >= group.volume_ratio_min, f"量比>={group.volume_ratio_min:.2f}"))
        if group.enable_daily_k_angle:
            conditions.append(
                (
                    "daily_k_angle",
                    signal_rows["daily_k_angle"] >= group.daily_k_angle_min,
                    f"日K角度({group.daily_k_angle_window}日)>={group.daily_k_angle_min:.2f}度",
                )
            )
        if group.enable_relative_low:
            conditions.append(
                (
                    "relative_low",
                    signal_rows["relative_low_position"] <= group.relative_low_position_max,
                    f"近{group.relative_low_window}日区间位置<={group.relative_low_position_max:.2%}",
                )
            )
        if group.enable_earnings_filter and earnings_available:
            conditions.append(
                (
                    "earnings",
                    signal_rows["forecast_pass"] | signal_rows["express_pass"] | signal_rows["growth_pass"],
                    f"业绩预告>={group.earnings_forecast_change_min:.2f}%或同比>={group.earnings_yoy_min:.2f}%",
                )
            )
        if group.enable_price_max:
            conditions.append(("price_max", signal_rows["close"] < group.price_max, f"股价<{group.price_max:.2f}"))
        if group.enable_turnover:
            conditions.append(("turnover", signal_rows["turnover_rate"] <= group.turnover_min, f"换手率<={group.turnover_min:.2f}%"))
        if group.enable_recent_volume_spike:
            conditions.append(
                (
                    "recent_volume_spike",
                    signal_rows["recent_amount_max"] >= group.recent_volume_spike_min,
                    f"最近{group.recent_volume_spike_window}天内有一天成交额>={group.recent_volume_spike_min / 100000000:.2f}亿",
                )
            )
        if group.enable_limit_up_count:
            conditions.append(
                (
                    "limit_up_count",
                    signal_rows["limit_up_count_recent"] >= group.limit_up_count_min,
                    f"近{group.limit_up_count_window}天涨停次数>={group.limit_up_count_min}",
                )
            )
        if group.enable_upper_shadow_count:
            conditions.append(
                (
                    "upper_shadow_count",
                    signal_rows["upper_shadow_count_recent"] >= group.upper_shadow_count_min,
                    f"近{group.upper_shadow_window}天上影线>={group.upper_shadow_threshold_pct:.2f}%次数>={group.upper_shadow_count_min}",
                )
            )
        if group.enable_lower_shadow_count:
            conditions.append(
                (
                    "lower_shadow_count",
                    signal_rows["lower_shadow_count_recent"] >= group.lower_shadow_count_min,
                    f"近{group.lower_shadow_window}天下影线>={group.lower_shadow_threshold_pct:.2f}%次数>={group.lower_shadow_count_min}",
                )
            )
        if group.enable_amount_followup:
            conditions.append(
                (
                    "amount_followup",
                    signal_rows["amount_followup_pass_recent"],
                    f"近{group.amount_followup_lookback_window}天存在成交额>={group.amount_followup_trigger_min / 100000000:.2f}亿且后{group.amount_followup_days}日成交额和>={group.amount_followup_sum_min / 100000000:.2f}亿",
                )
            )
        if group.enable_breakout_sequence:
            conditions.append(
                (
                    "breakout_sequence",
                    signal_rows["breakout_sequence_pass"],
                    f"近{group.breakout_ma20_within_days}天突破MA20且近{group.breakout_ma55_within_days}天突破MA55",
                )
            )
        if group.enable_sector_strength_filter:
            sector_mask = signal_rows["primary_sector_name"].notna()
            reason_parts: list[str] = []
            if group.max_sector_rank > 0:
                sector_mask &= signal_rows["sector_rank"].notna() & (signal_rows["sector_rank"] <= group.max_sector_rank)
                reason_parts.append(f"板块排名<={group.max_sector_rank}")
            if group.min_sector_strength_score > 0:
                sector_mask &= signal_rows["sector_strength_score"].notna() & (
                    signal_rows["sector_strength_score"] >= group.min_sector_strength_score
                )
                reason_parts.append(f"板块强度>={group.min_sector_strength_score:.2f}")
            if group.required_sector_name_keywords:
                reason_parts.append(f"板块名匹配:{group.required_sector_name_keywords}")
            if group.sector_source:
                reason_parts.append(f"板块源:{group.sector_source}")
            if group.sector_type:
                reason_parts.append(f"板块类型:{group.sector_type}")
            conditions.append(
                (
                    "sector_strength",
                    sector_mask,
                    ";".join(reason_parts) if reason_parts else "板块强度过滤",
                )
            )

        signal_rows["candidate_reason"] = ""
        signal_rows["filter_score"] = 0
        mask = pd.Series(True, index=signal_rows.index)
        for _, condition_mask, reason_text in conditions:
            condition_mask = condition_mask.fillna(False)
            mask &= condition_mask
            signal_rows.loc[condition_mask, "filter_score"] = signal_rows.loc[condition_mask, "filter_score"] + 1
            signal_rows.loc[condition_mask, "candidate_reason"] = signal_rows.loc[condition_mask, "candidate_reason"].apply(
                lambda existing, text=reason_text: f"{existing};{text}".strip(";")
            )

        result = signal_rows.loc[mask].copy()
        if result.empty:
            return result

        result["timeframe"] = "1d"
        result["bar_time"] = pd.to_datetime(result["date"])
        result["group_name"] = group.name
        result["group_reason"] = result["candidate_reason"]
        result["group_filters"] = ",".join(_enabled_filters(group))
        result["earnings_pub_date"] = result.apply(_select_earnings_pub_date, axis=1)
        result["earnings_signal"] = result.apply(_build_earnings_signal, axis=1)
        result["rule_label"] = _rule_label(group)
        result["score"] = 1

        ordered_columns = [
            "stock_code",
            "stock_name",
            "trade_date",
            "bar_time",
            "timeframe",
            "close",
            "score",
            "filter_score",
            "candidate_reason",
            "group_name",
            "group_reason",
            "group_filters",
            "signal_change_pct",
            "ema_value",
            "breakout_pct",
            "daily_k_slope_pct",
            "daily_k_angle",
            "relative_low_position",
            "limit_up_count_recent",
            "upper_shadow_count_recent",
            "lower_shadow_count_recent",
            "amount_followup_pass_recent",
            "breakout_sequence_pass",
            "days_since_break_ma20",
            "days_since_break_ma55",
            "amount_sum_next_5d",
            "available_date_5d",
            "earnings_pub_date",
            "earnings_signal",
            "volume_ratio",
            "turnover_rate",
            "primary_sector_name",
            "primary_sector_type",
            "sector_source",
            "sector_strength_score",
            "sector_rank",
            "recent_amount_max",
            "volume",
            "amount",
            "buy_date",
            "buy_open",
            "sell_date",
            "sell_close",
            "hold_return_pct",
            "rule_label",
        ]
        for column in ordered_columns:
            if column not in result.columns:
                result[column] = None
        return result[ordered_columns]

    @staticmethod
    def _combine_group_hits(group_hits: list[pd.DataFrame], *, combine_mode: str, required_groups: int) -> pd.DataFrame:
        non_empty = [frame for frame in group_hits if not frame.empty]
        if not non_empty:
            return pd.DataFrame()

        all_hits = pd.concat(non_empty, ignore_index=True)
        rows: list[dict] = []
        for _, subset in all_hits.groupby(["trade_date", "stock_code"], sort=False):
            group_count = subset["group_name"].nunique()
            if combine_mode == "all" and group_count < required_groups:
                continue
            base = subset.iloc[0].to_dict()
            reasons = [value for value in subset["group_reason"].astype(str).tolist() if value]
            group_names = subset["group_name"].astype(str).drop_duplicates().tolist()
            base["score"] = int(group_count)
            base["group_count"] = int(group_count)
            base["group_name"] = ";".join(group_names)
            base["matched_groups"] = ";".join(group_names)
            base["candidate_reason"] = " | ".join([f"{row['group_name']}:{row['group_reason']}" for _, row in subset.iterrows()])
            base["group_reason"] = " | ".join(reasons)
            rows.append(base)
        if not rows:
            return pd.DataFrame()
        result = pd.DataFrame(rows)
        return result.sort_values(
            by=["trade_date", "score", "filter_score", "turnover_rate", "volume_ratio", "daily_k_angle"],
            ascending=[True, False, False, False, False, False],
        ).reset_index(drop=True)


class ConditionTimelineRunner:
    def __init__(self, config: ConditionTimelineConfig) -> None:
        self.config = config
        self.store = DuckDBStore(config.db_path)

    def run(self) -> dict[str, object]:
        config = self._normalized_config()
        config = self._resolved_config_dates(config)
        screening_runner = ConditionScreeningRunner(
            ConditionScreeningConfig(
                db_path=config.db_path,
                khquant_cache_path=config.khquant_cache_path,
                export_root=config.export_root,
                signal_date=config.end_date,
                universe=config.universe,
                exclude_st=config.exclude_st,
                combine_mode=config.combine_mode,
                groups=config.groups,
            )
        )
        universe_df = screening_runner._load_universe(signal_date=config.end_date, universe=config.universe, exclude_st=config.exclude_st)
        if universe_df.empty:
            raise ValueError(f"No stocks found for universe={config.universe} on {config.end_date}.")

        history = self._load_history(
            codes=universe_df["code"].astype(str).tolist(),
            start_date=config.start_date,
            end_date=config.end_date,
            groups=config.groups,
        )
        available_dates = sorted(
            history[
                history["date"].dt.date.astype(str).between(config.start_date, config.end_date)
            ]["date"].dt.date.astype(str).drop_duplicates().tolist()
        )
        earnings_bundle = screening_runner._load_earnings_bundle(
            codes=history["stock_code"].drop_duplicates().astype(str).tolist(),
            end_date=config.end_date,
        )
        group_hits = [
            screening_runner._evaluate_group(history, group, target_dates=available_dates, earnings_bundle=earnings_bundle)
            for group in config.groups
        ]
        combined_hits = screening_runner._combine_group_hits(group_hits, combine_mode=config.combine_mode, required_groups=len(config.groups))

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        daily_counts = combined_hits.groupby("trade_date").size().rename("count").reset_index() if not combined_hits.empty else pd.DataFrame(columns=["trade_date", "count"])
        stock_summary = (
            combined_hits.groupby("stock_code")
            .agg(
                stock_name=("stock_name", "first"),
                hit_count=("trade_date", "count"),
                first_hit=("trade_date", "min"),
                last_hit=("trade_date", "max"),
            )
            .reset_index()
            if not combined_hits.empty
            else pd.DataFrame(columns=["stock_code", "stock_name", "hit_count", "first_hit", "last_hit"])
        )
        summary = {
            "start_date": config.start_date,
            "end_date": config.end_date,
            "universe": config.universe,
            "universe_label": UNIVERSE_LABELS.get(config.universe, config.universe),
            "date_count": int(len(available_dates)),
            "hit_count": int(len(combined_hits)),
            "unique_stock_count": int(combined_hits["stock_code"].nunique()) if not combined_hits.empty else 0,
            "combine_mode": config.combine_mode,
            "group_count": int(len(config.groups)),
        }

        export_root = Path(config.export_root)
        export_root.mkdir(parents=True, exist_ok=True)
        export_path = export_root / f"{run_id}_timeline_hits.csv"
        combined_hits.to_csv(export_path, index=False)

        self.store.replace_screening_timeline_run(
            run_id=run_id,
            start_date=config.start_date,
            end_date=config.end_date,
            strategy_name="condition_timeline",
            universe=config.universe,
            timeframe="1d",
            config=self._config_payload(config),
            result=summary,
        )
        self.store.replace_screening_timeline_hits(run_id, combined_hits)

        return {
            "run_id": run_id,
            "hits": combined_hits,
            "daily_counts": daily_counts,
            "stock_summary": stock_summary,
            "summary": summary,
            "export_path": export_path,
        }

    def _normalized_config(self) -> ConditionTimelineConfig:
        groups = [_normalize_group(group) for group in self.config.groups if bool(group.enabled)]
        if not groups:
            raise ValueError("At least one enabled condition group is required.")
        return ConditionTimelineConfig(
            db_path=self.config.db_path,
            khquant_cache_path=self.config.khquant_cache_path,
            export_root=self.config.export_root,
            start_date=str(pd.Timestamp(self.config.start_date).date()),
            end_date=str(pd.Timestamp(self.config.end_date).date()),
            universe=self.config.universe,
            exclude_st=bool(self.config.exclude_st),
            combine_mode=str(self.config.combine_mode or "any").lower(),
            groups=groups,
        )

    def _resolved_config_dates(self, config: ConditionTimelineConfig) -> ConditionTimelineConfig:
        screening_runner = ConditionScreeningRunner(
            ConditionScreeningConfig(
                db_path=config.db_path,
                khquant_cache_path=config.khquant_cache_path,
                export_root=config.export_root,
                signal_date=config.end_date,
                universe=config.universe,
                exclude_st=config.exclude_st,
                combine_mode=config.combine_mode,
                groups=config.groups,
            )
        )
        resolved_start = screening_runner._resolve_signal_date(config.start_date)
        resolved_end = screening_runner._resolve_signal_date(config.end_date)
        if resolved_end is None:
            raise ValueError(f"No available trade date on or before {config.end_date}.")
        if resolved_start is None:
            resolved_start = resolved_end
        if resolved_start > resolved_end:
            resolved_start = resolved_end
        return ConditionTimelineConfig(
            db_path=config.db_path,
            khquant_cache_path=config.khquant_cache_path,
            export_root=config.export_root,
            start_date=resolved_start,
            end_date=resolved_end,
            universe=config.universe,
            exclude_st=config.exclude_st,
            combine_mode=config.combine_mode,
            groups=config.groups,
        )

    @staticmethod
    def _config_payload(config: ConditionTimelineConfig) -> dict:
        payload = asdict(config)
        payload["groups"] = [asdict(group) for group in config.groups]
        return payload

    def _load_history(self, *, codes: list[str], start_date: str, end_date: str, groups: list[ConditionGroupConfig]) -> pd.DataFrame:
        screening_runner = ConditionScreeningRunner(
            ConditionScreeningConfig(
                db_path=self.config.db_path,
                khquant_cache_path=self.config.khquant_cache_path,
                export_root=self.config.export_root,
                signal_date=end_date,
                universe=self.config.universe,
                exclude_st=self.config.exclude_st,
                combine_mode=self.config.combine_mode,
                groups=groups,
            )
        )
        return screening_runner._load_history(codes=codes, start_date=start_date, end_date=end_date, groups=groups)


class ConditionCombo1Runner:
    def __init__(self, config: ConditionCombo1Config) -> None:
        self.config = config

    def run(self) -> dict[str, object]:
        runner = ConditionScreeningRunner(
            ConditionScreeningConfig(
                db_path=self.config.db_path,
                khquant_cache_path=self.config.khquant_cache_path,
                export_root=self.config.export_root,
                signal_date=self.config.signal_date,
                universe=self.config.universe,
                exclude_st=self.config.exclude_st,
                combine_mode="any",
                groups=[
                    ConditionGroupConfig(
                        name="组合1",
                        enabled=True,
                        ema_period=self.config.ema_period,
                        enable_ema_breakout=self.config.enable_ema_breakout,
                        volume_ma_window=self.config.volume_ma_window,
                        enable_volume_ratio=self.config.enable_volume_ratio,
                        volume_ratio_min=self.config.volume_ratio_min,
                        daily_k_angle_window=self.config.daily_k_angle_window,
                        enable_daily_k_angle=self.config.enable_daily_k_angle,
                        daily_k_angle_min=self.config.daily_k_angle_min,
                        relative_low_window=self.config.relative_low_window,
                        enable_relative_low=self.config.enable_relative_low,
                        relative_low_position_max=self.config.relative_low_position_max,
                        enable_earnings_filter=self.config.enable_earnings_filter,
                        earnings_forecast_change_min=self.config.earnings_forecast_change_min,
                        earnings_yoy_min=self.config.earnings_yoy_min,
                        enable_price_max=self.config.enable_price_max,
                        price_max=self.config.price_max,
                        enable_turnover=self.config.enable_turnover,
                        turnover_min=self.config.turnover_min,
                        enable_recent_volume_spike=self.config.enable_recent_volume_spike,
                        recent_volume_spike_window=self.config.recent_volume_spike_window,
                        recent_volume_spike_min=self.config.recent_volume_spike_min,
                        enable_limit_up_count=self.config.enable_limit_up_count,
                        limit_up_count_window=self.config.limit_up_count_window,
                        limit_up_count_min=self.config.limit_up_count_min,
                        enable_upper_shadow_count=self.config.enable_upper_shadow_count,
                        upper_shadow_window=self.config.upper_shadow_window,
                        upper_shadow_threshold_pct=self.config.upper_shadow_threshold_pct,
                        upper_shadow_count_min=self.config.upper_shadow_count_min,
                        enable_lower_shadow_count=self.config.enable_lower_shadow_count,
                        lower_shadow_window=self.config.lower_shadow_window,
                        lower_shadow_threshold_pct=self.config.lower_shadow_threshold_pct,
                        lower_shadow_count_min=self.config.lower_shadow_count_min,
                        enable_amount_followup=self.config.enable_amount_followup,
                        amount_followup_lookback_window=self.config.amount_followup_lookback_window,
                        amount_followup_trigger_min=self.config.amount_followup_trigger_min,
                        amount_followup_sum_min=self.config.amount_followup_sum_min,
                        amount_followup_days=self.config.amount_followup_days,
                        enable_breakout_sequence=self.config.enable_breakout_sequence,
                        breakout_ma20_within_days=self.config.breakout_ma20_within_days,
                        breakout_ma55_within_days=self.config.breakout_ma55_within_days,
                        hold_days=self.config.hold_days,
                        enable_sector_strength_filter=self.config.enable_sector_strength_filter,
                        sector_source=self.config.sector_source,
                        sector_type=self.config.sector_type,
                        max_sector_rank=self.config.max_sector_rank,
                        min_sector_strength_score=self.config.min_sector_strength_score,
                        required_sector_name_keywords=self.config.required_sector_name_keywords,
                    )
                ],
            )
        )
        result = runner.run()
        result["cache_info"] = runner._get_local_cache_info(exclude_st=self.config.exclude_st)
        return result


def _select_earnings_pub_date(row: pd.Series) -> str:
    for column in ("forecast_pub_date", "express_pub_date", "growth_pub_date"):
        value = row.get(column)
        if pd.notna(value):
            return str(pd.Timestamp(value).date())
    return ""


def _build_earnings_signal(row: pd.Series) -> str:
    parts: list[str] = []
    if bool(row.get("forecast_pass", False)):
        parts.append(f"预告:{row.get('forecast_type', '')}")
    if bool(row.get("express_pass", False)):
        parts.append("快报通过")
    if bool(row.get("growth_pass", False)):
        parts.append("成长通过")
    return ";".join(parts)
