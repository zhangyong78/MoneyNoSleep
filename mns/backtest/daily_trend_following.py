from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import pandas as pd

from mns.portfolio.position_sizer import round_lot_quantity


@dataclass(frozen=True)
class DailyTrendBacktestConfig:
    initial_cash: float = 1_000_000
    risk_per_trade_pct: float = 0.008
    max_position_pct: float = 0.20
    max_total_risk_pct: float = 0.025
    high_volatility_threshold: float = 0.06
    high_volatility_size_factor: float = 0.5
    commission_rate: float = 0.0005
    stamp_tax_rate: float = 0.001
    transfer_fee_rate: float = 0.0
    slippage_rate: float = 0.001
    lot_size: int = 100
    stage2_timeout_days: int = 15


class DailyTrendFollowingBacktester:
    run_type = "daily_trend_following"

    def __init__(self, config: DailyTrendBacktestConfig | None = None) -> None:
        self.config = config or DailyTrendBacktestConfig()

    def run(self, signals: pd.DataFrame, kline: pd.DataFrame, *, run_id: str | None = None) -> dict[str, pd.DataFrame | str | dict]:
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        if signals.empty or kline.empty:
            empty = pd.DataFrame()
            return {
                "run_id": run_id,
                "trades": empty,
                "trade_actions": empty,
                "portfolio_snapshots": empty,
                "signals": signals,
            }

        bars = kline.sort_values(["trade_date", "stock_code", "bar_time"]).copy()
        bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date
        bars["bar_time"] = pd.to_datetime(bars["bar_time"])

        signals_by_date = signals.copy()
        signals_by_date["trade_date"] = pd.to_datetime(signals_by_date["trade_date"]).dt.date
        signal_map = {trade_date: frame.copy() for trade_date, frame in signals_by_date.groupby("trade_date")}

        open_positions: dict[str, dict] = {}
        completed_trades: list[dict] = []
        action_rows: list[dict] = []
        snapshots: list[dict] = []
        cash = float(self.config.initial_cash)

        for trade_date, daily_bars in bars.groupby("trade_date"):
            daily_bars = daily_bars.sort_values("stock_code").reset_index(drop=True)
            daily_index = {row["stock_code"]: row for _, row in daily_bars.iterrows()}

            for stock_code in list(open_positions.keys()):
                position = open_positions[stock_code]
                bar = daily_index.get(stock_code)
                if bar is None:
                    continue

                self._update_position_thresholds(position, bar)
                close_action = self._evaluate_exit(position, bar)
                if close_action is not None:
                    realized_cash, action_row, trade_record = self._close_position(
                        position=position,
                        price=float(close_action["price"]),
                        trade_time=pd.Timestamp(bar["bar_time"]),
                        exit_type=str(close_action["exit_type"]),
                        quantity=int(position["quantity"]),
                        run_id=run_id,
                    )
                    cash += realized_cash
                    action_rows.append(action_row)
                    completed_trades.append(trade_record)
                    del open_positions[stock_code]
                    continue

                partial_action = self._evaluate_partial_exit(position, bar)
                if partial_action is not None:
                    realized_cash, action_row = self._execute_partial_exit(
                        position=position,
                        price=float(partial_action["price"]),
                        trade_time=pd.Timestamp(bar["bar_time"]),
                        run_id=run_id,
                    )
                    cash += realized_cash
                    action_rows.append(action_row)

            equity_before_entries = cash + self._mark_to_market(open_positions, daily_index)
            current_total_risk = sum(pos["risk_per_share"] * pos["quantity"] for pos in open_positions.values())

            daily_signals = signal_map.get(trade_date)
            if daily_signals is None or daily_signals.empty:
                daily_signals = pd.DataFrame()
            else:
                daily_signals = daily_signals.sort_values("score", ascending=False)

            for _, signal in daily_signals.iterrows():
                stock_code = str(signal["stock_code"])
                if stock_code in open_positions:
                    continue
                bar = daily_index.get(stock_code)
                if bar is None:
                    continue

                entry_price = float(signal["entry_price"]) * (1 + self.config.slippage_rate)
                stop_loss = float(signal["stop_loss"])
                risk_per_share = entry_price - stop_loss
                if risk_per_share <= 0:
                    continue

                risk_budget = equity_before_entries * self.config.risk_per_trade_pct
                quantity = round_lot_quantity(risk_budget / risk_per_share, self.config.lot_size)
                max_value_quantity = round_lot_quantity(
                    equity_before_entries * self.config.max_position_pct / entry_price,
                    self.config.lot_size,
                )
                quantity = min(quantity, max_value_quantity)
                if float(signal.get("atr14", 0) or 0) / entry_price > self.config.high_volatility_threshold:
                    quantity = round_lot_quantity(quantity * self.config.high_volatility_size_factor, self.config.lot_size)
                if quantity <= 0:
                    continue

                incremental_risk = quantity * risk_per_share
                if current_total_risk + incremental_risk > equity_before_entries * self.config.max_total_risk_pct:
                    continue

                gross_cost = quantity * entry_price
                buy_commission = gross_cost * (self.config.commission_rate + self.config.transfer_fee_rate)
                total_cash_out = gross_cost + buy_commission
                if total_cash_out > cash:
                    continue

                cash -= total_cash_out
                current_total_risk += incremental_risk
                position = {
                    "trade_id": f"{run_id}_{len(completed_trades) + len(open_positions) + 1:04d}",
                    "run_id": run_id,
                    "stock_code": stock_code,
                    "stock_name": signal.get("stock_name"),
                    "strategy_name": signal["strategy_name"],
                    "entry_date": trade_date,
                    "buy_time": pd.Timestamp(bar["bar_time"]),
                    "entry_price": entry_price,
                    "entry_condition": signal.get("entry_condition", ""),
                    "initial_stop_loss": stop_loss,
                    "active_stop": stop_loss,
                    "quantity": quantity,
                    "initial_quantity": quantity,
                    "risk_per_share": risk_per_share,
                    "r_value": risk_per_share,
                    "atr14": float(signal.get("atr14", 0.0) or 0.0),
                    "ema20_at_entry": float(signal.get("ema20", 0.0) or 0.0),
                    "ema50_at_entry": float(signal.get("ema50", 0.0) or 0.0),
                    "ema20_slope_5": float(signal.get("ema20_slope_5", 0.0) or 0.0),
                    "ema50_slope_5": float(signal.get("ema50_slope_5", 0.0) or 0.0),
                    "volume_ratio": float(signal.get("volume_ratio_20", 0.0) or 0.0),
                    "stage1_done": False,
                    "stage2_done": False,
                    "stage2_date": None,
                    "remaining_stop_floor": stop_loss,
                    "buy_commission": buy_commission,
                    "sell_commission": 0.0,
                    "tax": 0.0,
                    "slippage_cost": quantity * (entry_price - float(signal["entry_price"])),
                    "realized_value": 0.0,
                    "realized_pnl": 0.0,
                    "exit_types": [],
                    "partial_exit_count": 0,
                    "max_drawdown": 0.0,
                }
                open_positions[stock_code] = position
                action_rows.append(
                    {
                        "trade_id": position["trade_id"],
                        "run_id": run_id,
                        "stock_code": stock_code,
                        "strategy_name": position["strategy_name"],
                        "action": "BUY",
                        "price": entry_price,
                        "quantity": quantity,
                        "trade_time": position["buy_time"],
                        "commission": buy_commission,
                        "tax": 0.0,
                        "slippage": quantity * (entry_price - float(signal["entry_price"])),
                        "reason": f"entry_{position['entry_condition']}",
                    }
                )

            total_equity = cash + self._mark_to_market(open_positions, daily_index)
            market_value = self._mark_to_market(open_positions, daily_index)
            snapshots.append(
                {
                    "run_id": run_id,
                    "snapshot_time": pd.Timestamp(trade_date),
                    "total_equity": total_equity,
                    "cash": cash,
                    "available_cash": cash,
                    "market_value": market_value,
                    "daily_pnl": None,
                }
            )

        if open_positions:
            last_bars = bars.sort_values("bar_time").groupby("stock_code").tail(1).set_index("stock_code")
            for stock_code, position in list(open_positions.items()):
                bar = last_bars.loc[stock_code]
                realized_cash, action_row, trade_record = self._close_position(
                    position=position,
                    price=float(bar["close"]),
                    trade_time=pd.Timestamp(bar["bar_time"]),
                    exit_type="end_of_test",
                    quantity=int(position["quantity"]),
                    run_id=run_id,
                )
                cash += realized_cash
                action_rows.append(action_row)
                completed_trades.append(trade_record)
                del open_positions[stock_code]

        trades_df = pd.DataFrame(completed_trades)
        actions_df = pd.DataFrame(action_rows)
        portfolio_df = self._build_portfolio_snapshots(pd.DataFrame(snapshots), trades_df)
        return {"run_id": run_id, "trades": trades_df, "trade_actions": actions_df, "portfolio_snapshots": portfolio_df}

    def _evaluate_exit(self, position: dict, bar: pd.Series) -> dict | None:
        close_price = float(bar["close"])
        low_price = float(bar["low"])
        ema20 = float(bar.get("ema20", position["ema20_at_entry"]))
        trade_time = pd.Timestamp(bar["bar_time"])
        days_held = (trade_time.date() - position["entry_date"]).days

        drawdown = (low_price - position["entry_price"]) / position["entry_price"]
        position["max_drawdown"] = min(position["max_drawdown"], drawdown)

        if low_price <= position["active_stop"]:
            exit_type = "trend_stop" if position["stage2_done"] else ("breakeven_stop" if position["stage1_done"] else "initial_stop")
            return {"price": position["active_stop"], "exit_type": exit_type}

        if close_price < ema20:
            if (not position["stage2_done"]) and days_held >= self.config.stage2_timeout_days:
                return {"price": close_price, "exit_type": "time_stop"}
            return {"price": close_price, "exit_type": "trend_exit"}

        return None

    def _evaluate_partial_exit(self, position: dict, bar: pd.Series) -> dict | None:
        if position["stage2_done"]:
            return None
        high_price = float(bar["high"])
        target_price = position["entry_price"] + 2 * position["r_value"]
        if high_price >= target_price:
            return {"price": target_price}
        return None

    def _update_position_thresholds(self, position: dict, bar: pd.Series) -> None:
        high_price = float(bar["high"])
        ema20 = float(bar.get("ema20", position["ema20_at_entry"]))
        one_r_price = position["entry_price"] + position["r_value"]
        if (not position["stage1_done"]) and high_price >= one_r_price:
            position["stage1_done"] = True
            position["active_stop"] = max(position["active_stop"], position["entry_price"])
        if position["stage2_done"]:
            position["active_stop"] = max(position["active_stop"], position["remaining_stop_floor"], ema20)

    def _execute_partial_exit(self, *, position: dict, price: float, trade_time: pd.Timestamp, run_id: str) -> tuple[float, dict]:
        partial_qty = round_lot_quantity(position["initial_quantity"] * 0.5, self.config.lot_size)
        if partial_qty <= 0 or partial_qty >= position["quantity"]:
            partial_qty = max(position["quantity"] // 2, 0)
        if partial_qty <= 0:
            partial_qty = position["quantity"]

        proceeds = partial_qty * price
        commission = proceeds * (self.config.commission_rate + self.config.transfer_fee_rate)
        tax = proceeds * self.config.stamp_tax_rate
        slippage = partial_qty * (position["entry_price"] + 2 * position["r_value"] - price)
        realized_cash = proceeds - commission - tax
        cost_basis = partial_qty * position["entry_price"]
        realized_pnl = proceeds - cost_basis - commission - tax

        position["quantity"] -= partial_qty
        position["realized_value"] += proceeds
        position["realized_pnl"] += realized_pnl
        position["sell_commission"] += commission
        position["tax"] += tax
        position["slippage_cost"] += slippage
        position["stage2_done"] = True
        position["stage2_date"] = trade_time.date()
        position["remaining_stop_floor"] = position["entry_price"] + position["r_value"]
        position["active_stop"] = max(position["active_stop"], position["remaining_stop_floor"])
        position["partial_exit_count"] += 1
        position["exit_types"].append("take_profit_2r")

        action_row = {
            "trade_id": position["trade_id"],
            "run_id": run_id,
            "stock_code": position["stock_code"],
            "strategy_name": position["strategy_name"],
            "action": "SELL",
            "price": price,
            "quantity": partial_qty,
            "trade_time": trade_time,
            "commission": commission,
            "tax": tax,
            "slippage": slippage,
            "reason": "take_profit_2r",
        }
        return realized_cash, action_row

    def _close_position(
        self,
        *,
        position: dict,
        price: float,
        trade_time: pd.Timestamp,
        exit_type: str,
        quantity: int,
        run_id: str,
    ) -> tuple[float, dict, dict]:
        proceeds = quantity * price
        commission = proceeds * (self.config.commission_rate + self.config.transfer_fee_rate)
        tax = proceeds * self.config.stamp_tax_rate
        slippage = quantity * (float(price) - float(price))
        realized_cash = proceeds - commission - tax
        cost_basis = quantity * position["entry_price"]
        realized_pnl = proceeds - cost_basis - commission - tax

        total_proceeds = position["realized_value"] + proceeds
        total_commission = position["buy_commission"] + position["sell_commission"] + commission
        total_tax = position["tax"] + tax
        total_slippage = position["slippage_cost"] + slippage
        total_cost_basis = position["initial_quantity"] * position["entry_price"]
        total_pnl = position["realized_pnl"] + realized_pnl
        average_exit_price = total_proceeds / position["initial_quantity"] if position["initial_quantity"] else 0.0
        days_held = (trade_time.date() - position["entry_date"]).days

        if position["stage2_done"] and exit_type == "trend_exit":
            normalized_exit_type = "partial_2r+trend_exit"
        elif position["stage2_done"] and exit_type == "end_of_test":
            normalized_exit_type = "partial_2r+end_of_test"
        else:
            normalized_exit_type = exit_type

        action_row = {
            "trade_id": position["trade_id"],
            "run_id": run_id,
            "stock_code": position["stock_code"],
            "strategy_name": position["strategy_name"],
            "action": "SELL",
            "price": price,
            "quantity": quantity,
            "trade_time": trade_time,
            "commission": commission,
            "tax": tax,
            "slippage": slippage,
            "reason": normalized_exit_type,
        }
        trade_record = {
            "trade_id": position["trade_id"],
            "run_id": run_id,
            "stock_code": position["stock_code"],
            "stock_name": position["stock_name"],
            "symbol": position["stock_code"],
            "trade_date": position["entry_date"],
            "entry_price": position["entry_price"],
            "stop_loss": position["initial_stop_loss"],
            "position_size": position["initial_quantity"],
            "atr_14": position["atr14"],
            "ma20": position["ema20_at_entry"],
            "ma50": position["ema50_at_entry"],
            "ma20_slope": position["ema20_slope_5"],
            "ma50_slope": position["ema50_slope_5"],
            "volume_ratio": position["volume_ratio"],
            "entry_condition": position["entry_condition"],
            "exit_price": average_exit_price,
            "exit_type": normalized_exit_type,
            "buy_time": position["buy_time"],
            "buy_price": position["entry_price"],
            "sell_time": trade_time,
            "sell_price": average_exit_price,
            "quantity": position["initial_quantity"],
            "pnl": total_pnl,
            "pnl_pct": total_pnl / total_cost_basis if total_cost_basis else 0.0,
            "return_pct": total_pnl / total_cost_basis if total_cost_basis else 0.0,
            "commission": total_commission,
            "buy_commission": position["buy_commission"],
            "sell_commission": position["sell_commission"] + commission,
            "tax": total_tax,
            "slippage": total_slippage,
            "total_cost": total_commission + total_tax + total_slippage,
            "max_drawdown": position["max_drawdown"],
            "days_held": days_held,
            "reason": f"entry_{position['entry_condition']}",
        }
        return realized_cash, action_row, trade_record

    @staticmethod
    def _mark_to_market(open_positions: dict[str, dict], daily_index: dict[str, pd.Series]) -> float:
        total = 0.0
        for stock_code, position in open_positions.items():
            bar = daily_index.get(stock_code)
            if bar is None:
                continue
            total += position["quantity"] * float(bar["close"])
        return total

    def _build_portfolio_snapshots(self, snapshots: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
        if snapshots.empty:
            return pd.DataFrame()
        portfolio = snapshots.copy()
        portfolio["daily_pnl"] = portfolio["total_equity"].diff().fillna(portfolio["total_equity"] - self.config.initial_cash)
        portfolio["cumulative_return"] = portfolio["total_equity"] / self.config.initial_cash - 1
        running_max = portfolio["total_equity"].cummax()
        portfolio["drawdown"] = portfolio["total_equity"] / running_max - 1
        return portfolio[
            [
                "run_id",
                "snapshot_time",
                "total_equity",
                "cash",
                "available_cash",
                "market_value",
                "daily_pnl",
                "cumulative_return",
                "drawdown",
            ]
        ]


def summarize_daily_trend_run(trades: pd.DataFrame, portfolio_snapshots: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {
            "trade_count": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_loss_ratio": 0.0,
            "expectancy": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "max_consecutive_losses": 0,
            "avg_days_held": 0.0,
            "annualized_return": 0.0,
        }

    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] < 0]
    avg_win = float(wins["pnl"].mean()) if not wins.empty else 0.0
    avg_loss = float(losses["pnl"].mean()) if not losses.empty else 0.0
    win_rate = float((trades["pnl"] > 0).mean())
    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    expectancy = win_rate * avg_win - (1 - win_rate) * abs(avg_loss)

    max_drawdown = float(portfolio_snapshots["drawdown"].min()) if not portfolio_snapshots.empty else 0.0
    daily_returns = portfolio_snapshots["total_equity"].pct_change().dropna() if not portfolio_snapshots.empty else pd.Series(dtype=float)
    sharpe_ratio = 0.0
    if not daily_returns.empty and daily_returns.std() > 0:
        sharpe_ratio = float((daily_returns.mean() / daily_returns.std()) * (252 ** 0.5))

    consecutive_losses = 0
    max_consecutive_losses = 0
    for pnl in trades["pnl"].tolist():
        if pnl < 0:
            consecutive_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        else:
            consecutive_losses = 0

    annualized_return = 0.0
    if not portfolio_snapshots.empty:
        total_days = max((pd.to_datetime(portfolio_snapshots["snapshot_time"]).max() - pd.to_datetime(portfolio_snapshots["snapshot_time"]).min()).days, 1)
        total_return = float(portfolio_snapshots["total_equity"].iloc[-1] / portfolio_snapshots["total_equity"].iloc[0] - 1)
        annualized_return = float((1 + total_return) ** (365 / total_days) - 1) if total_return > -1 else -1.0

    return {
        "trade_count": int(len(trades)),
        "total_pnl": float(trades["pnl"].sum()),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_loss_ratio": profit_loss_ratio,
        "expectancy": expectancy,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "max_consecutive_losses": max_consecutive_losses,
        "avg_days_held": float(trades["days_held"].mean()),
        "annualized_return": annualized_return,
    }
