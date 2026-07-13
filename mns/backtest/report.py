from __future__ import annotations

import pandas as pd


def summarize_trades(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"trade_count": 0, "total_pnl": 0.0, "win_rate": 0.0}
    wins = (trades["pnl"] > 0).sum()
    return {
        "trade_count": int(len(trades)),
        "total_pnl": float(trades["pnl"].sum()),
        "win_rate": float(wins / len(trades)),
    }
