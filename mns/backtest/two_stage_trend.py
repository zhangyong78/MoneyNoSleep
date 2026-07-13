from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import pandas as pd


@dataclass(frozen=True)
class TwoStageTrendBacktestConfig:
    initial_cash: float = 200_000.0
    max_positions: int = 10
    per_position_cash: float | None = None
    initial_stop_pct: float = 0.10
    breakeven_r: float = 1.0
    trail_start_r: float = 2.0
    atr_multiple: float = 2.0
    ma20_exit_mode: str = "off"
    lot_size: int = 100
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001
    transfer_fee_rate: float = 0.00001
    slippage_rate: float = 0.0005


class TwoStageTrendBacktester:
    run_type = "two_stage_trend"

    def __init__(self, config: TwoStageTrendBacktestConfig | None = None) -> None:
        self.config = config or TwoStageTrendBacktestConfig()

    def run(self, signals: pd.DataFrame, bars: pd.DataFrame, *, run_id: str | None = None) -> dict[str, pd.DataFrame | str]:
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        empty = pd.DataFrame()
        if bars.empty:
            return {"run_id": run_id, "trades": empty, "trade_actions": empty, "portfolio_snapshots": empty, "skipped_orders": empty}
        data = bars.sort_values(["trade_date", "stock_code"]).copy()
        data["trade_date"] = pd.to_datetime(data["trade_date"]).dt.date
        data["bar_time"] = pd.to_datetime(data["bar_time"])
        data["prev_close"] = data.groupby("stock_code")["close"].shift(1)
        scheduled = signals.copy()
        if not scheduled.empty:
            scheduled["entry_date"] = pd.to_datetime(scheduled["entry_date"]).dt.date
        buys_by_date = {} if scheduled.empty else {date: frame.sort_values(["score", "volume_ratio_5", "breakout_pct"], ascending=False) for date, frame in scheduled.groupby("entry_date")}
        positions: dict[str, dict] = {}
        pending_sells: dict[str, str] = {}
        actions: list[dict] = []
        trades: list[dict] = []
        skipped: list[dict] = []
        snapshots: list[dict] = []
        cash = float(self.config.initial_cash)
        last_close_by_code: dict[str, float] = {}

        for date, day in data.groupby("trade_date", sort=True):
            by_code = {str(row["stock_code"]): row for _, row in day.iterrows()}
            for code, reason in list(pending_sells.items()):
                bar = by_code.get(code)
                if bar is None or not self._tradable(bar):
                    continue
                position = positions.pop(code)
                price = float(bar["open"]) * (1 - self.config.slippage_rate)
                proceeds, action, trade = self._close(position, price, pd.Timestamp(bar["bar_time"]), reason)
                cash += proceeds
                actions.append(action | {"run_id": run_id})
                trades.append(trade | {"run_id": run_id})
                del pending_sells[code]

            for code in list(positions):
                position = positions[code]
                bar = by_code.get(code)
                if bar is None or date <= position["entry_date"]:
                    continue
                active_stop = float(position["active_stop"])
                if float(bar["low"]) > active_stop:
                    continue
                raw_price = float(bar["open"]) if float(bar["open"]) < active_stop else active_stop
                price = raw_price * (1 - self.config.slippage_rate)
                proceeds, action, trade = self._close(position, price, pd.Timestamp(bar["bar_time"]), str(position["exit_reason"]))
                cash += proceeds
                actions.append(action | {"run_id": run_id})
                trades.append(trade | {"run_id": run_id})
                del positions[code]
                pending_sells.pop(code, None)

            day_signals = buys_by_date.get(date, pd.DataFrame())
            equity = cash + sum(
                float(pos["quantity"])
                * (
                    float(by_code[code]["open"])
                    if code in by_code and pd.notna(by_code[code]["open"]) and float(by_code[code]["open"]) > 0
                    else last_close_by_code.get(code, float(pos["entry_price"]))
                )
                for code, pos in positions.items()
            )
            for _, signal in day_signals.iterrows():
                code = str(signal["stock_code"])
                if code in positions:
                    continue
                if len(positions) >= self.config.max_positions:
                    skipped.append({"stock_code": code, "trade_date": date, "reason": "position_limit"})
                    continue
                bar = by_code.get(code)
                if bar is None or not self._tradable(bar):
                    skipped.append({"stock_code": code, "trade_date": date, "reason": "not_buyable"})
                    continue
                if self._at_limit_up(bar):
                    skipped.append({"stock_code": code, "trade_date": date, "reason": "limit_up_unbuyable"})
                    continue
                raw_price = float(bar["open"])
                price = raw_price * (1 + self.config.slippage_rate)
                quantity = self._quantity(equity, cash, price)
                commission = quantity * price * (self.config.commission_rate + self.config.transfer_fee_rate)
                if quantity <= 0 or quantity * price + commission > cash:
                    skipped.append({"stock_code": code, "trade_date": date, "reason": "insufficient_cash"})
                    continue
                cash -= quantity * price + commission
                positions[code] = {
                    "trade_id": f"{run_id}_{len(trades) + len(positions) + 1:04d}", "stock_code": code,
                    "stock_name": signal.get("stock_name", code), "entry_time": pd.Timestamp(bar["bar_time"]), "entry_date": date,
                    "strategy_name": "two_stage_trend",
                    "entry_price": price, "quantity": quantity, "buy_commission": commission, "r_value": price * self.config.initial_stop_pct,
                    "active_stop": price * (1 - self.config.initial_stop_pct), "highest_close": float(bar["close"]),
                    "exit_reason": "initial_stop", "entry_reason": signal.get("reason", ""),
                }
                actions.append({"run_id": run_id, "trade_id": positions[code]["trade_id"], "stock_code": code, "strategy_name": "two_stage_trend", "action": "BUY", "price": price, "quantity": quantity, "trade_time": pd.Timestamp(bar["bar_time"]), "commission": commission, "tax": 0.0, "slippage": quantity * (price - raw_price), "reason": "next_open"})

            for code, position in positions.items():
                bar = by_code.get(code)
                if bar is None:
                    continue
                self._update_stop(position, bar)
                if float(bar["close"]) < float(position["active_stop"]):
                    pending_sells[code] = str(position["exit_reason"])
                    continue
                ma20_exit_reason = self._ma20_exit_reason(position, bar)
                if ma20_exit_reason:
                    pending_sells[code] = ma20_exit_reason
            for code, bar in by_code.items():
                if pd.notna(bar.get("close")) and float(bar["close"]) > 0:
                    last_close_by_code[code] = float(bar["close"])
            market_value = sum(
                float(pos["quantity"]) * last_close_by_code.get(code, float(pos["entry_price"]))
                for code, pos in positions.items()
            )
            snapshots.append({"run_id": run_id, "snapshot_time": pd.Timestamp(date), "total_equity": cash + market_value, "cash": cash, "available_cash": cash, "market_value": market_value})

        last = data.sort_values("bar_time").groupby("stock_code").tail(1).set_index("stock_code")
        for code, position in list(positions.items()):
            bar = last.loc[code]
            proceeds, action, trade = self._close(position, float(bar["close"]) * (1 - self.config.slippage_rate), pd.Timestamp(bar["bar_time"]), "end_of_test")
            cash += proceeds
            actions.append(action | {"run_id": run_id})
            trades.append(trade | {"run_id": run_id})
        portfolio = self._portfolio(pd.DataFrame(snapshots))
        return {"run_id": run_id, "trades": pd.DataFrame(trades), "trade_actions": pd.DataFrame(actions), "portfolio_snapshots": portfolio, "skipped_orders": pd.DataFrame(skipped)}

    def _quantity(self, equity: float, cash: float, price: float) -> int:
        target_amount = self.config.per_position_cash or equity / self.config.max_positions
        amount = min(target_amount, cash)
        return max(int(amount // (price * self.config.lot_size)) * self.config.lot_size, 0)

    @staticmethod
    def _tradable(bar: pd.Series) -> bool:
        return pd.notna(bar.get("open")) and float(bar["open"]) > 0 and not bool(bar.get("is_suspended", False))

    @staticmethod
    def _at_limit_up(bar: pd.Series) -> bool:
        limit_up = bar.get("limit_up_price")
        if pd.notna(limit_up):
            return float(bar["open"]) >= float(limit_up) * 0.999
        previous_close = bar.get("prev_close")
        if pd.isna(previous_close) or float(previous_close) <= 0:
            return False
        code = str(bar.get("stock_code", ""))
        name = str(bar.get("stock_name", "")).upper()
        if "ST" in name:
            threshold = 1.045
        elif code.startswith(("300", "301", "688")):
            threshold = 1.195
        else:
            threshold = 1.095
        return float(bar["open"]) / float(previous_close) >= threshold

    def _update_stop(self, position: dict, bar: pd.Series) -> None:
        position["highest_close"] = max(float(position["highest_close"]), float(bar["close"]))
        entry, risk, high = float(position["entry_price"]), float(position["r_value"]), float(position["highest_close"])
        if high >= entry + self.config.breakeven_r * risk:
            position["active_stop"] = max(float(position["active_stop"]), entry)
            position["exit_reason"] = "breakeven_stop"
        if high >= entry + self.config.trail_start_r * risk:
            trailing = high - self.config.atr_multiple * float(bar.get("atr14", 0.0) or 0.0)
            position["active_stop"] = max(float(position["active_stop"]), entry, trailing)
            position["exit_reason"] = "atr_trailing_stop"

    def _ma20_exit_reason(self, position: dict, bar: pd.Series) -> str | None:
        mode = self.config.ma20_exit_mode
        if mode == "off":
            return None
        ma20 = pd.to_numeric(pd.Series([bar.get("ma20")]), errors="coerce").iloc[0]
        close = pd.to_numeric(pd.Series([bar.get("close")]), errors="coerce").iloc[0]
        if pd.isna(ma20) or ma20 <= 0 or pd.isna(close) or close >= ma20:
            return None
        if mode == "always":
            return "ma20_exit"
        if mode == "profit_only" and close > float(position["entry_price"]):
            return "ma20_profit_exit"
        return None

    def _close(self, position: dict, price: float, time: pd.Timestamp, reason: str) -> tuple[float, dict, dict]:
        quantity = int(position["quantity"]); proceeds = quantity * price
        commission = proceeds * (self.config.commission_rate + self.config.transfer_fee_rate); tax = proceeds * self.config.stamp_tax_rate
        pnl = proceeds - commission - tax - quantity * float(position["entry_price"]) - float(position["buy_commission"])
        action = {"trade_id": position["trade_id"], "stock_code": position["stock_code"], "strategy_name": position["strategy_name"], "action": "SELL", "price": price, "quantity": quantity, "trade_time": time, "commission": commission, "tax": tax, "slippage": 0.0, "reason": reason}
        trade = {"trade_id": position["trade_id"], "stock_code": position["stock_code"], "stock_name": position["stock_name"], "buy_time": position["entry_time"], "buy_price": position["entry_price"], "sell_time": time, "sell_price": price, "quantity": quantity, "pnl": pnl, "return_pct": pnl / (quantity * float(position["entry_price"])), "r_multiple": pnl / (quantity * float(position["r_value"])), "days_held": (time.date() - position["entry_date"]).days, "exit_reason": reason, "reason": position["entry_reason"]}
        return proceeds - commission - tax, action, trade

    def _portfolio(self, snapshots: pd.DataFrame) -> pd.DataFrame:
        if snapshots.empty:
            return snapshots
        result = snapshots.copy(); result["daily_pnl"] = result["total_equity"].diff().fillna(result["total_equity"] - self.config.initial_cash)
        result["cumulative_return"] = result["total_equity"] / self.config.initial_cash - 1; result["drawdown"] = result["total_equity"] / result["total_equity"].cummax() - 1
        return result


def summarize_two_stage_trend_run(trades: pd.DataFrame, portfolio: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"trade_count": 0, "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "profit_loss_ratio": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0}
    wins, losses = trades.loc[trades.pnl > 0, "pnl"], trades.loc[trades.pnl < 0, "pnl"]
    avg_win, avg_loss = float(wins.mean()) if len(wins) else 0.0, float(losses.mean()) if len(losses) else 0.0
    return {"trade_count": len(trades), "win_rate": float((trades.pnl > 0).mean()), "avg_win": avg_win, "avg_loss": avg_loss, "profit_loss_ratio": abs(avg_win / avg_loss) if avg_loss else 0.0, "profit_factor": float(wins.sum()) / abs(float(losses.sum())) if len(losses) else 0.0, "max_drawdown": float(portfolio.drawdown.min()) if not portfolio.empty else 0.0}
