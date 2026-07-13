from __future__ import annotations

import pandas as pd


def pair_trade_actions(actions: pd.DataFrame) -> pd.DataFrame:
    """Combine BUY/SELL action rows into one review-friendly trade row."""

    if actions.empty:
        return pd.DataFrame()

    paired_rows: list[dict] = []
    for trade_id, group in actions.groupby("trade_id"):
        row: dict[str, object] = {
            "trade_id": trade_id,
            "run_id": group["run_id"].iloc[0],
            "stock_code": group["stock_code"].iloc[0],
            "strategy_name": group["strategy_name"].iloc[0],
        }
        buy = group[group["action"] == "BUY"].sort_values("trade_time")
        sell = group[group["action"] == "SELL"].sort_values("trade_time")
        if not buy.empty:
            row["buy_time"] = buy["trade_time"].iloc[0]
            row["buy_price"] = buy["price"].iloc[0]
            row["quantity"] = int(buy["quantity"].iloc[0])
            row["reason"] = buy["reason"].iloc[0]
        if not sell.empty:
            row["sell_time"] = sell["trade_time"].iloc[-1]
            row["sell_price"] = sell["price"].iloc[-1]
        if "buy_price" in row and "sell_price" in row and "quantity" in row:
            row["pnl"] = (float(row["sell_price"]) - float(row["buy_price"])) * int(row["quantity"])
        paired_rows.append(row)

    paired = pd.DataFrame(paired_rows)
    if "buy_time" in paired.columns:
        return paired.sort_values("buy_time").reset_index(drop=True)
    return paired.reset_index(drop=True)
