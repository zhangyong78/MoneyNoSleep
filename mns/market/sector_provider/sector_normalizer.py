from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


SECTOR_TYPES = {"industry", "concept", "theme", "index", "region", "custom", "unknown"}


@dataclass(frozen=True)
class SectorNormalizer:
    source: str

    @staticmethod
    def normalize_stock_code(value: Any) -> str | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        raw = str(value).strip()
        if not raw:
            return None
        uppered = raw.upper()
        if uppered.endswith((".SH", ".SZ", ".BJ")) and len(uppered) >= 9:
            return uppered
        lowered = raw.lower()
        if lowered.startswith(("sh.", "sz.", "bj.")) and len(lowered) >= 9:
            return f"{lowered[3:9]}.{lowered[:2].upper()}"
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) != 6:
            return uppered
        if digits.startswith(("6", "9")):
            return f"{digits}.SH"
        if digits.startswith(("4", "8")):
            return f"{digits}.BJ"
        return f"{digits}.SZ"

    @staticmethod
    def normalize_sector_type(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw in SECTOR_TYPES:
            return raw
        if raw in {"hy", "industry_board"}:
            return "industry"
        if raw in {"gn", "concept_board"}:
            return "concept"
        if raw in {"zs", "index_board"}:
            return "index"
        return "unknown"

    @staticmethod
    def canonical_sector_name(value: Any) -> str:
        return str(value or "").strip()

    def build_sector_id(self, *, sector_type: str, sector_name: str, source_sector_code: Any = None) -> str:
        code = str(source_sector_code).strip() if pd.notna(source_sector_code) and source_sector_code not in (None, "") else ""
        key = code or self.canonical_sector_name(sector_name)
        return f"{self.source}:{sector_type}:{key}"

    @staticmethod
    def _pick_column(frame: pd.DataFrame, candidates: list[str]) -> pd.Series:
        for column in candidates:
            if column in frame.columns:
                return frame[column]
        return pd.Series([None] * len(frame), index=frame.index)

    def normalize_sector_list(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(
                columns=[
                    "sector_id",
                    "sector_name",
                    "canonical_sector_name",
                    "sector_type",
                    "source",
                    "source_sector_code",
                    "updated_at",
                ]
            )
        prepared = frame.copy()
        prepared["sector_name"] = self._pick_column(prepared, ["sector_name", "name", "板块名称", "板块", "行业名称"]).map(self.canonical_sector_name)
        prepared["source_sector_code"] = self._pick_column(prepared, ["source_sector_code", "sector_code", "code", "板块代码"])
        prepared["sector_type"] = self._pick_column(prepared, ["sector_type", "type", "板块类型"]).map(self.normalize_sector_type)
        prepared.loc[prepared["sector_type"] == "unknown", "sector_type"] = "industry"
        prepared["canonical_sector_name"] = prepared["sector_name"].map(self.canonical_sector_name)
        prepared["source"] = self.source
        prepared["updated_at"] = pd.Timestamp.utcnow().tz_localize(None)
        prepared["sector_id"] = prepared.apply(
            lambda row: self.build_sector_id(
                sector_type=row["sector_type"],
                sector_name=row["sector_name"],
                source_sector_code=row["source_sector_code"],
            ),
            axis=1,
        )
        return prepared[
            [
                "sector_id",
                "sector_name",
                "canonical_sector_name",
                "sector_type",
                "source",
                "source_sector_code",
                "updated_at",
            ]
        ].drop_duplicates(subset=["sector_id", "source"])

    def normalize_stock_sector_map(
        self,
        frame: pd.DataFrame,
        *,
        sector_id: str,
        sector_name: str,
        sector_type: str,
    ) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(
                columns=[
                    "stock_code",
                    "stock_name",
                    "sector_id",
                    "sector_name",
                    "sector_type",
                    "source",
                    "start_date",
                    "end_date",
                    "updated_at",
                ]
            )
        prepared = frame.copy()
        prepared["stock_code"] = self._pick_column(
            prepared,
            ["stock_code", "code", "代码", "股票代码", "证券代码"],
        ).map(self.normalize_stock_code)
        prepared["stock_name"] = self._pick_column(prepared, ["stock_name", "name", "名称", "股票名称", "证券简称"])
        prepared["sector_id"] = sector_id
        prepared["sector_name"] = sector_name
        prepared["sector_type"] = sector_type
        prepared["source"] = self.source
        prepared["start_date"] = self._pick_column(prepared, ["start_date", "纳入日期"])
        prepared["end_date"] = self._pick_column(prepared, ["end_date", "移除日期"])
        prepared["updated_at"] = pd.Timestamp.utcnow().tz_localize(None)
        prepared = prepared.dropna(subset=["stock_code"]).drop_duplicates(subset=["stock_code", "sector_id", "source"])
        return prepared[
            [
                "stock_code",
                "stock_name",
                "sector_id",
                "sector_name",
                "sector_type",
                "source",
                "start_date",
                "end_date",
                "updated_at",
            ]
        ]

    def normalize_sector_daily(
        self,
        frame: pd.DataFrame,
        *,
        sectors: pd.DataFrame,
        trade_date: str | None = None,
    ) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(
                columns=[
                    "sector_id",
                    "sector_name",
                    "trade_date",
                    "timeframe",
                    "open",
                    "high",
                    "low",
                    "close",
                    "pct_change",
                    "amount",
                    "volume",
                    "turnover_rate",
                    "up_num",
                    "down_num",
                    "flat_num",
                    "limit_up_num",
                    "limit_down_num",
                    "leading_stock",
                    "leading_stock_pct",
                    "source",
                    "updated_at",
                ]
            )
        prepared = frame.copy()
        prepared["sector_name"] = self._pick_column(prepared, ["sector_name", "name", "板块名称", "板块"]).map(self.canonical_sector_name)
        prepared["source_sector_code"] = self._pick_column(prepared, ["source_sector_code", "sector_code", "code", "板块代码"])
        prepared["trade_date"] = pd.to_datetime(
            self._pick_column(prepared, ["trade_date", "日期"]).fillna(trade_date or pd.Timestamp.today().date()),
            errors="coerce",
        ).dt.date
        prepared["timeframe"] = self._pick_column(prepared, ["timeframe"]).fillna("1d")
        prepared["open"] = pd.to_numeric(self._pick_column(prepared, ["open", "今开"]), errors="coerce")
        prepared["high"] = pd.to_numeric(self._pick_column(prepared, ["high", "最高"]), errors="coerce")
        prepared["low"] = pd.to_numeric(self._pick_column(prepared, ["low", "最低"]), errors="coerce")
        prepared["close"] = pd.to_numeric(self._pick_column(prepared, ["close", "最新价"]), errors="coerce")
        prepared["pct_change"] = pd.to_numeric(self._pick_column(prepared, ["pct_change", "涨跌幅"]), errors="coerce")
        prepared["amount"] = pd.to_numeric(self._pick_column(prepared, ["amount", "成交额", "总成交额"]), errors="coerce")
        prepared["volume"] = pd.to_numeric(self._pick_column(prepared, ["volume", "成交量", "总成交量"]), errors="coerce")
        prepared["turnover_rate"] = pd.to_numeric(self._pick_column(prepared, ["turnover_rate", "换手率"]), errors="coerce")
        prepared["up_num"] = pd.to_numeric(self._pick_column(prepared, ["up_num", "上涨家数"]), errors="coerce").fillna(0).astype(int)
        prepared["down_num"] = pd.to_numeric(self._pick_column(prepared, ["down_num", "下跌家数"]), errors="coerce").fillna(0).astype(int)
        prepared["flat_num"] = pd.to_numeric(self._pick_column(prepared, ["flat_num", "平盘家数"]), errors="coerce").fillna(0).astype(int)
        prepared["limit_up_num"] = pd.to_numeric(self._pick_column(prepared, ["limit_up_num", "涨停家数"]), errors="coerce").fillna(0).astype(int)
        prepared["limit_down_num"] = pd.to_numeric(self._pick_column(prepared, ["limit_down_num", "跌停家数"]), errors="coerce").fillna(0).astype(int)
        prepared["leading_stock"] = self._pick_column(prepared, ["leading_stock", "领涨股"])
        prepared["leading_stock_pct"] = pd.to_numeric(self._pick_column(prepared, ["leading_stock_pct", "领涨股-涨跌幅"]), errors="coerce")
        prepared["source"] = self.source
        prepared["updated_at"] = pd.Timestamp.utcnow().tz_localize(None)
        merged = prepared.merge(
            sectors[["sector_id", "sector_name", "source_sector_code"]],
            on=["sector_name", "source_sector_code"],
            how="left",
        )
        return merged[
            [
                "sector_id",
                "sector_name",
                "trade_date",
                "timeframe",
                "open",
                "high",
                "low",
                "close",
                "pct_change",
                "amount",
                "volume",
                "turnover_rate",
                "up_num",
                "down_num",
                "flat_num",
                "limit_up_num",
                "limit_down_num",
                "leading_stock",
                "leading_stock_pct",
                "source",
                "updated_at",
            ]
        ].dropna(subset=["sector_id", "trade_date"])
