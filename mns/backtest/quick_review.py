from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import pandas as pd

from mns.portfolio.position_sizer import fixed_cash_quantity, round_lot_quantity


@dataclass(frozen=True)
class QuickReviewConfig:
    initial_cash: float = 1_000_000
    hold_days: int = 5
    per_trade_cash: float = 100_000
    lot_size: int = 100
    commission_rate: float = 0.0
    stamp_tax_rate: float = 0.0
    transfer_fee_rate: float = 0.0
    slippage_rate: float = 0.0
    risk_per_trade: float | None = None
    max_hold_bars: int | None = None
    respect_signal_levels: bool = False


class QuickReviewBacktester:
    """Daily quick review backtest.

    Buy at the next bar open after signal time, then sell at the close after N
    bars. This is intentionally simple and marked as review validation, not a
    full A-share execution model.
    """

    run_type = "quick_review"

    def __init__(self, config: QuickReviewConfig | None = None) -> None:
        self.config = config or QuickReviewConfig()

    def run(self, signals: pd.DataFrame, kline: pd.DataFrame, *, run_id: str | None = None) -> dict[str, pd.DataFrame | str]:
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        if signals.empty:
            return {
                "run_id": run_id,
                "trades": pd.DataFrame(),
                "portfolio_snapshots": pd.DataFrame(),
            }

        bars = kline.sort_values(["stock_code", "bar_time"]).copy()
        bars["bar_time"] = pd.to_datetime(bars["bar_time"])
        trades = []
        hold_bars = self.config.max_hold_bars or self.config.hold_days

        for _, signal in signals.sort_values("signal_time").iterrows():
            stock_bars = bars[bars["stock_code"] == signal["stock_code"]].reset_index(drop=True)
            future = stock_bars[stock_bars["bar_time"] > pd.Timestamp(signal["signal_time"])].reset_index(drop=True)
            if len(future) <= hold_bars:
                continue
            buy_bar = future.iloc[0]
            raw_buy_price = float(buy_bar["open"])
            buy_price = raw_buy_price * (1 + self.config.slippage_rate)
            quantity = self._position_quantity(signal, buy_price)
            if quantity <= 0:
                continue
            sell_bar = future.iloc[hold_bars]
            raw_sell_price = float(sell_bar["close"])
            sell_time = sell_bar["bar_time"]
            exit_reason = "hold_bars"

            if self.config.respect_signal_levels:
                sell_bar, raw_sell_price, sell_time, exit_reason = self._resolve_exit(
                    future=future.iloc[1 : hold_bars + 1].reset_index(drop=True),
                    fallback_bar=sell_bar,
                    signal=signal,
                )

            sell_price = raw_sell_price * (1 - self.config.slippage_rate)
            buy_value = quantity * buy_price
            sell_value = quantity * sell_price
            buy_commission = buy_value * (self.config.commission_rate + self.config.transfer_fee_rate)
            sell_commission = sell_value * (self.config.commission_rate + self.config.transfer_fee_rate)
            tax = sell_value * self.config.stamp_tax_rate
            slippage_cost = quantity * ((buy_price - raw_buy_price) + (raw_sell_price - sell_price))
            total_cost = buy_commission + sell_commission + tax + slippage_cost
            pnl = sell_value - buy_value - buy_commission - sell_commission - tax
            trades.append(
                {
                    "trade_id": f"{run_id}_{len(trades) + 1:04d}",
                    "run_id": run_id,
                    "stock_code": signal["stock_code"],
                    "strategy_name": signal["strategy_name"],
                    "buy_time": buy_bar["bar_time"],
                    "buy_price": buy_price,
                    "sell_time": sell_time,
                    "sell_price": sell_price,
                    "quantity": quantity,
                    "pnl": pnl,
                    "return_pct": pnl / buy_value if buy_value else 0.0,
                    "commission": buy_commission + sell_commission,
                    "buy_commission": buy_commission,
                    "sell_commission": sell_commission,
                    "tax": tax,
                    "slippage": slippage_cost,
                    "total_cost": total_cost,
                    "reason": signal.get("reason", ""),
                    "exit_reason": exit_reason,
                }
            )

        trades_df = pd.DataFrame(trades)
        snapshots_df = self._build_snapshots(run_id, trades_df)
        return {"run_id": run_id, "trades": trades_df, "portfolio_snapshots": snapshots_df}

    def _build_snapshots(self, run_id: str, trades: pd.DataFrame) -> pd.DataFrame:
        if trades.empty:
            return pd.DataFrame()
        by_day = trades.groupby(trades["sell_time"].dt.date)["pnl"].sum().reset_index()
        by_day.columns = ["snapshot_time", "daily_pnl"]
        by_day["run_id"] = run_id
        by_day["total_equity"] = self.config.initial_cash + by_day["daily_pnl"].cumsum()
        by_day["cash"] = by_day["total_equity"]
        by_day["available_cash"] = by_day["cash"]
        by_day["market_value"] = 0.0
        by_day["cumulative_return"] = by_day["total_equity"] / self.config.initial_cash - 1
        running_max = by_day["total_equity"].cummax()
        by_day["drawdown"] = by_day["total_equity"] / running_max - 1
        return by_day[
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

    def _position_quantity(self, signal: pd.Series, buy_price: float) -> int:
        cash_capped_quantity = fixed_cash_quantity(self.config.per_trade_cash, buy_price, self.config.lot_size)
        if not self.config.respect_signal_levels or not self.config.risk_per_trade:
            return cash_capped_quantity

        stop_loss = signal.get("stop_loss")
        if stop_loss is None or pd.isna(stop_loss):
            return cash_capped_quantity

        risk_per_share = buy_price - float(stop_loss)
        if risk_per_share <= 0:
            return cash_capped_quantity

        risk_quantity = round_lot_quantity(self.config.risk_per_trade / risk_per_share, self.config.lot_size)
        if cash_capped_quantity <= 0:
            return risk_quantity
        if risk_quantity <= 0:
            return 0
        return min(cash_capped_quantity, risk_quantity)

    @staticmethod
    def _resolve_exit(
        *,
        future: pd.DataFrame,
        fallback_bar: pd.Series,
        signal: pd.Series,
    ) -> tuple[pd.Series, float, pd.Timestamp, str]:
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        has_stop_loss = stop_loss is not None and not pd.isna(stop_loss)
        has_take_profit = take_profit is not None and not pd.isna(take_profit)

        for _, bar in future.iterrows():
            if has_stop_loss and "low" in bar and pd.notna(bar["low"]) and float(bar["low"]) <= float(stop_loss):
                return bar, float(stop_loss), pd.Timestamp(bar["bar_time"]), "stop_loss"
            if has_take_profit and "high" in bar and pd.notna(bar["high"]) and float(bar["high"]) >= float(take_profit):
                return bar, float(take_profit), pd.Timestamp(bar["bar_time"]), "take_profit"

        return fallback_bar, float(fallback_bar["close"]), pd.Timestamp(fallback_bar["bar_time"]), "hold_bars"
