from __future__ import annotations

import pandas as pd


def compute_sector_strength(sector_daily: pd.DataFrame) -> pd.DataFrame:
    """Build a simple rankable sector-strength snapshot from daily sector data."""

    if sector_daily.empty:
        return pd.DataFrame(
            columns=[
                "sector_id",
                "sector_name",
                "trade_date",
                "timeframe",
                "strength_score",
                "relative_return",
                "three_bar_score",
                "amount_score",
                "limit_up_score",
                "leader_score",
                "rank",
                "source",
                "updated_at",
            ]
        )

    prepared = sector_daily.copy()
    total_count = (prepared["up_num"] + prepared["down_num"] + prepared["flat_num"]).replace(0, pd.NA)
    prepared["relative_return"] = prepared["pct_change"].fillna(0.0)
    prepared["breadth_score"] = ((prepared["up_num"] - prepared["down_num"]) / total_count).fillna(0.0)
    prepared["amount_rank_score"] = prepared["amount"].fillna(0.0).rank(pct=True)
    prepared["limit_up_score"] = prepared["limit_up_num"].fillna(0).rank(pct=True)
    prepared["leader_score"] = prepared["leading_stock_pct"].fillna(0.0).rank(pct=True)
    prepared["three_bar_score"] = prepared["relative_return"].fillna(0.0)
    prepared["amount_score"] = prepared["amount_rank_score"]
    prepared["strength_score"] = (
        prepared["relative_return"].rank(pct=True) * 0.35
        + prepared["breadth_score"].rank(pct=True) * 0.20
        + prepared["amount_rank_score"] * 0.20
        + prepared["limit_up_score"] * 0.15
        + prepared["leader_score"] * 0.10
    )
    prepared["rank"] = prepared["strength_score"].rank(ascending=False, method="dense").astype(int)
    prepared["updated_at"] = pd.Timestamp.utcnow().tz_localize(None)
    return prepared[
        [
            "sector_id",
            "sector_name",
            "trade_date",
            "timeframe",
            "strength_score",
            "relative_return",
            "three_bar_score",
            "amount_score",
            "limit_up_score",
            "leader_score",
            "rank",
            "source",
            "updated_at",
        ]
    ].sort_values(["trade_date", "rank", "sector_name"]).reset_index(drop=True)
