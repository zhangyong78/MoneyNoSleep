from __future__ import annotations

import pandas as pd


def identify_sector_leaders(sector_daily: pd.DataFrame) -> pd.DataFrame:
    """Build minimal leader rows from sector-daily board leaders."""

    if sector_daily.empty:
        return pd.DataFrame(
            columns=[
                "sector_id",
                "sector_name",
                "trade_date",
                "stock_code",
                "stock_name",
                "leader_type",
                "leader_score",
                "pct_change",
                "amount",
                "turnover_rate",
                "reason",
                "updated_at",
            ]
        )

    prepared = sector_daily.loc[sector_daily["leading_stock"].notna()].copy()
    if prepared.empty:
        return pd.DataFrame(
            columns=[
                "sector_id",
                "sector_name",
                "trade_date",
                "stock_code",
                "stock_name",
                "leader_type",
                "leader_score",
                "pct_change",
                "amount",
                "turnover_rate",
                "reason",
                "updated_at",
            ]
        )
    prepared["stock_code"] = None
    prepared["stock_name"] = prepared["leading_stock"]
    prepared["leader_type"] = "龙一"
    prepared["leader_score"] = prepared["leading_stock_pct"].fillna(0.0)
    prepared["pct_change"] = prepared["leading_stock_pct"].fillna(0.0)
    prepared["reason"] = "board_leading_stock"
    prepared["updated_at"] = pd.Timestamp.utcnow().tz_localize(None)
    return prepared[
        [
            "sector_id",
            "sector_name",
            "trade_date",
            "stock_code",
            "stock_name",
            "leader_type",
            "leader_score",
            "pct_change",
            "amount",
            "turnover_rate",
            "reason",
            "updated_at",
        ]
    ].reset_index(drop=True)
