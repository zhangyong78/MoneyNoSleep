from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from mns.market.sector_provider.base import SectorProvider


class AKShareSectorProvider(SectorProvider):
    """AKShare-backed sector provider for industry and concept boards."""

    name = "akshare"

    def __init__(self, *, ak_module: Any | None = None) -> None:
        self._ak = ak_module

    def _module(self):
        if self._ak is not None:
            return self._ak
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise RuntimeError("akshare is required. Run `pip install -e .`.") from exc
        self._ak = ak
        return self._ak

    def get_sector_list(self, sector_types: list[str] | None = None) -> pd.DataFrame:
        requested = set(sector_types or ["industry", "concept"])
        frames: list[pd.DataFrame] = []
        ak = self._module()

        if "industry" in requested and hasattr(ak, "stock_board_industry_name_em"):
            industry = self._safe_call(ak.stock_board_industry_name_em)
            if not industry.empty:
                industry = industry.copy()
                industry["sector_name"] = self._pick(industry, ["板块名称", "名称", "name"])
                industry["source_sector_code"] = self._pick(industry, ["板块代码", "代码", "code"])
                industry["sector_type"] = "industry"
                frames.append(industry[["sector_name", "source_sector_code", "sector_type"]])

        if "concept" in requested and hasattr(ak, "stock_board_concept_name_em"):
            concept = self._safe_call(ak.stock_board_concept_name_em)
            if not concept.empty:
                concept = concept.copy()
                concept["sector_name"] = self._pick(concept, ["板块名称", "名称", "name"])
                concept["source_sector_code"] = self._pick(concept, ["板块代码", "代码", "code"])
                concept["sector_type"] = "concept"
                frames.append(concept[["sector_name", "source_sector_code", "sector_type"]])

        if not frames:
            return pd.DataFrame(columns=["sector_name", "source_sector_code", "sector_type"])
        return pd.concat(frames, ignore_index=True).drop_duplicates()

    def get_sector_stocks(
        self,
        *,
        sector_name: str,
        sector_type: str | None = None,
        source_sector_code: str | None = None,
    ) -> pd.DataFrame:
        ak = self._module()
        board_type = sector_type or "industry"
        if board_type == "concept":
            if not hasattr(ak, "stock_board_concept_cons_em"):
                return pd.DataFrame()
            return self._safe_call(lambda: ak.stock_board_concept_cons_em(symbol=sector_name))
        if not hasattr(ak, "stock_board_industry_cons_em"):
            return pd.DataFrame()
        return self._safe_call(lambda: ak.stock_board_industry_cons_em(symbol=sector_name))

    def get_sector_daily(self, trade_date: str | None = None, sector_types: list[str] | None = None) -> pd.DataFrame:
        requested = set(sector_types or ["industry", "concept"])
        target_date = pd.to_datetime(trade_date).date() if trade_date else date.today()
        if target_date != date.today():
            return pd.DataFrame()

        frames: list[pd.DataFrame] = []
        ak = self._module()
        if "industry" in requested and hasattr(ak, "stock_board_industry_name_em"):
            industry = self._safe_call(ak.stock_board_industry_name_em)
            if not industry.empty:
                industry = industry.copy()
                industry["sector_type"] = "industry"
                industry["trade_date"] = target_date
                frames.append(industry)
        if "concept" in requested and hasattr(ak, "stock_board_concept_name_em"):
            concept = self._safe_call(ak.stock_board_concept_name_em)
            if not concept.empty:
                concept = concept.copy()
                concept["sector_type"] = "concept"
                concept["trade_date"] = target_date
                frames.append(concept)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    @staticmethod
    def _pick(frame: pd.DataFrame, candidates: list[str]) -> pd.Series:
        for column in candidates:
            if column in frame.columns:
                return frame[column]
        return pd.Series([None] * len(frame), index=frame.index)

    @staticmethod
    def _safe_call(func) -> pd.DataFrame:
        try:
            frame = func()
        except Exception:
            return pd.DataFrame()
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
