from __future__ import annotations

import pandas as pd


class ReplayEngine:
    def daily_summary(self, portfolio_snapshots: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
        if portfolio_snapshots.empty:
            return pd.DataFrame()
        summary = portfolio_snapshots.copy()
        if not trades.empty:
            trade_counts = trades.groupby(trades["sell_time"].dt.date).size().rename("closed_trades")
            summary = summary.merge(
                trade_counts,
                left_on="snapshot_time",
                right_index=True,
                how="left",
            )
        summary["closed_trades"] = summary.get("closed_trades", 0).fillna(0).astype(int)
        return summary
