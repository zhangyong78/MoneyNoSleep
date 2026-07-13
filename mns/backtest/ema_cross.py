from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.data.local_data import LocalMarketData
from mns.factors.technical import ema
from mns.review.report_exporter import ReportExporter


@dataclass(frozen=True)
class EmaCrossBacktestConfig:
    db_path: str = "data/duckdb/mns.duckdb"
    timeframe: str = "1h"
    start_date: str | None = None
    end_date: str | None = None
    stock_codes: list[str] | None = None
    fast_period: int = 21
    slow_period: int = 55
    initial_cash: float = 1_000_000
    risk_per_trade: float = 5_000
    lot_size: int = 100
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.0
    transfer_fee_rate: float = 0.0
    slippage_rate: float = 0.0005
    export_root: str = "data/reports/exports"


def add_ema_cross_factors(
    kline: pd.DataFrame,
    *,
    fast_period: int = 21,
    slow_period: int = 55,
) -> pd.DataFrame:
    enriched = kline.sort_values(["stock_code", "bar_time"]).copy()
    enriched["bar_time"] = pd.to_datetime(enriched["bar_time"])
    enriched["trade_date"] = pd.to_datetime(enriched["trade_date"]).dt.date
    grouped = enriched.groupby("stock_code", group_keys=False)
    enriched["ema_fast"] = grouped["close"].transform(lambda s: ema(s, fast_period))
    enriched["ema_slow"] = grouped["close"].transform(lambda s: ema(s, slow_period))
    enriched["ema_fast_prev"] = grouped["ema_fast"].shift(1)
    enriched["ema_slow_prev"] = grouped["ema_slow"].shift(1)
    enriched["pre_entry_3bar_low"] = grouped["low"].transform(lambda s: s.rolling(window=3, min_periods=3).min())
    enriched["next_bar_time"] = grouped["bar_time"].shift(-1)
    enriched["next_trade_date"] = grouped["trade_date"].shift(-1)
    enriched["next_open"] = grouped["open"].shift(-1)
    enriched["golden_cross"] = (
        enriched["ema_fast"].notna()
        & enriched["ema_slow"].notna()
        & enriched["ema_fast_prev"].notna()
        & enriched["ema_slow_prev"].notna()
        & (enriched["ema_fast_prev"] <= enriched["ema_slow_prev"])
        & (enriched["ema_fast"] > enriched["ema_slow"])
    )
    return enriched


def build_ema_cross_signals(enriched: pd.DataFrame) -> pd.DataFrame:
    if enriched.empty:
        return pd.DataFrame()

    signals = enriched.loc[enriched["golden_cross"]].copy()
    signals = signals[
        signals["next_bar_time"].notna()
        & signals["next_open"].notna()
        & signals["pre_entry_3bar_low"].notna()
        & (signals["next_open"] > signals["pre_entry_3bar_low"])
    ].copy()
    if signals.empty:
        return pd.DataFrame()

    signals["strategy_name"] = "ema21_ema55_cross"
    signals["action"] = "BUY"
    signals["timeframe"] = signals["timeframe"].astype(str)
    signals["signal_time"] = pd.to_datetime(signals["bar_time"])
    signals["entry_time"] = pd.to_datetime(signals["next_bar_time"])
    signals["entry_price"] = signals["next_open"].astype(float)
    signals["stop_loss"] = signals["pre_entry_3bar_low"].astype(float)
    signals["take_profit"] = None
    signals["risk_per_share_est"] = signals["entry_price"] - signals["stop_loss"]
    signals["score"] = (signals["ema_fast"] - signals["ema_slow"]) / signals["ema_slow"]
    signals["reason"] = "ema21_up_cross_ema55;buy_next_open;stop_last_3bar_low"
    signals["status"] = "NEW"
    return signals[
        [
            "stock_code",
            "stock_name",
            "trade_date",
            "bar_time",
            "strategy_name",
            "action",
            "timeframe",
            "signal_time",
            "entry_time",
            "entry_price",
            "stop_loss",
            "take_profit",
            "score",
            "reason",
            "status",
            "risk_per_share_est",
        ]
    ].reset_index(drop=True)


class EmaCrossBacktester:
    run_type = "ema_cross"

    def __init__(self, config: EmaCrossBacktestConfig | None = None) -> None:
        self.config = config or EmaCrossBacktestConfig()

    def run(self, signals: pd.DataFrame, kline: pd.DataFrame, *, run_id: str | None = None) -> dict[str, pd.DataFrame | str]:
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        if signals.empty or kline.empty:
            empty = pd.DataFrame()
            return {"run_id": run_id, "trades": empty, "trade_actions": empty, "portfolio_snapshots": empty}

        bars = kline.sort_values(["bar_time", "stock_code"]).copy()
        bars["bar_time"] = pd.to_datetime(bars["bar_time"])
        bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date

        signals = signals.sort_values(["entry_time", "stock_code"]).copy()
        signals["entry_time"] = pd.to_datetime(signals["entry_time"])
        signal_map = {
            bar_time: frame.sort_values("stock_code").reset_index(drop=True)
            for bar_time, frame in signals.groupby("entry_time")
        }

        open_positions: dict[str, dict] = {}
        completed_trades: list[dict] = []
        action_rows: list[dict] = []
        snapshots: list[dict] = []
        cash = float(self.config.initial_cash)

        for bar_time, frame in bars.groupby("bar_time"):
            frame = frame.sort_values("stock_code").reset_index(drop=True)
            daily_index = {str(row["stock_code"]): row for _, row in frame.iterrows()}

            entry_signals = signal_map.get(bar_time, pd.DataFrame())
            for _, signal in entry_signals.iterrows():
                stock_code = str(signal["stock_code"])
                if stock_code in open_positions:
                    continue
                bar = daily_index.get(stock_code)
                if bar is None:
                    continue

                raw_entry_price = float(bar["open"])
                entry_price = raw_entry_price * (1 + self.config.slippage_rate)
                stop_loss = float(signal["stop_loss"])
                risk_per_share = entry_price - stop_loss
                if risk_per_share <= 0:
                    continue

                quantity = self._position_quantity(risk_per_share=risk_per_share, entry_price=entry_price, cash=cash)
                if quantity <= 0:
                    continue

                gross_cost = quantity * entry_price
                buy_commission = gross_cost * (self.config.commission_rate + self.config.transfer_fee_rate)
                total_cash_out = gross_cost + buy_commission
                if total_cash_out > cash:
                    continue

                cash -= total_cash_out
                position = {
                    "trade_id": f"{run_id}_{len(completed_trades) + len(open_positions) + 1:04d}",
                    "run_id": run_id,
                    "stock_code": stock_code,
                    "stock_name": signal.get("stock_name"),
                    "strategy_name": signal["strategy_name"],
                    "entry_time": pd.Timestamp(bar_time),
                    "entry_date": pd.Timestamp(bar_time).date(),
                    "entry_price": entry_price,
                    "raw_entry_price": raw_entry_price,
                    "initial_stop_loss": stop_loss,
                    "active_stop": stop_loss,
                    "risk_per_share": risk_per_share,
                    "quantity": quantity,
                    "buy_commission": buy_commission,
                    "highest_price": float(bar["high"]),
                    "max_r": max((float(bar["high"]) - entry_price) / risk_per_share, 0.0),
                    "stop_stage": "INITIAL_STOP",
                    "entry_reason": signal.get("reason", ""),
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
                        "trade_time": pd.Timestamp(bar_time),
                        "commission": buy_commission,
                        "tax": 0.0,
                        "slippage": quantity * (entry_price - raw_entry_price),
                        "reason": "golden_cross_next_open",
                    }
                )

            for stock_code in list(open_positions.keys()):
                position = open_positions[stock_code]
                bar = daily_index.get(stock_code)
                if bar is None:
                    continue

                current_stop = float(position["active_stop"])
                open_price = float(bar["open"])
                low_price = float(bar["low"])
                if low_price <= current_stop:
                    raw_exit_price = open_price if open_price < current_stop else current_stop
                    exit_price = raw_exit_price * (1 - self.config.slippage_rate)
                    realized_cash, action_row, trade_record = self._close_position(
                        position=position,
                        exit_price=exit_price,
                        raw_exit_price=raw_exit_price,
                        trade_time=pd.Timestamp(bar_time),
                        exit_reason=position["stop_stage"],
                    )
                    cash += realized_cash
                    action_rows.append(action_row | {"run_id": run_id})
                    completed_trades.append(trade_record | {"run_id": run_id})
                    del open_positions[stock_code]
                    continue

                highest_price = max(float(position["highest_price"]), float(bar["high"]))
                position["highest_price"] = highest_price
                max_r = (highest_price - float(position["entry_price"])) / float(position["risk_per_share"])
                position["max_r"] = max(float(position["max_r"]), max_r)
                self._update_trailing_stop(position)

            market_value = 0.0
            for stock_code, position in open_positions.items():
                bar = daily_index.get(stock_code)
                if bar is None:
                    continue
                market_value += int(position["quantity"]) * float(bar["close"])

            total_equity = cash + market_value
            snapshots.append(
                {
                    "run_id": run_id,
                    "snapshot_time": pd.Timestamp(bar_time),
                    "total_equity": total_equity,
                    "cash": cash,
                    "available_cash": cash,
                    "market_value": market_value,
                }
            )

        if open_positions:
            last_bars = bars.sort_values("bar_time").groupby("stock_code").tail(1).set_index("stock_code")
            for stock_code, position in list(open_positions.items()):
                bar = last_bars.loc[stock_code]
                raw_exit_price = float(bar["close"])
                exit_price = raw_exit_price * (1 - self.config.slippage_rate)
                realized_cash, action_row, trade_record = self._close_position(
                    position=position,
                    exit_price=exit_price,
                    raw_exit_price=raw_exit_price,
                    trade_time=pd.Timestamp(bar["bar_time"]),
                    exit_reason="END_OF_TEST",
                )
                cash += realized_cash
                action_rows.append(action_row | {"run_id": run_id})
                completed_trades.append(trade_record | {"run_id": run_id})
                del open_positions[stock_code]

        trades = pd.DataFrame(completed_trades)
        trade_actions = pd.DataFrame(action_rows)
        portfolio_snapshots = self._build_portfolio_snapshots(pd.DataFrame(snapshots))
        return {
            "run_id": run_id,
            "trades": trades,
            "trade_actions": trade_actions,
            "portfolio_snapshots": portfolio_snapshots,
        }

    def _position_quantity(self, *, risk_per_share: float, entry_price: float, cash: float) -> int:
        risk_quantity = math.floor((self.config.risk_per_trade / risk_per_share) / self.config.lot_size) * self.config.lot_size
        cash_quantity = math.floor((cash / entry_price) / self.config.lot_size) * self.config.lot_size
        return max(min(int(risk_quantity), int(cash_quantity)), 0)

    @staticmethod
    def _update_trailing_stop(position: dict) -> None:
        entry_price = float(position["entry_price"])
        risk_per_share = float(position["risk_per_share"])
        max_r = float(position["max_r"])

        if max_r >= 1.0:
            position["active_stop"] = max(float(position["active_stop"]), entry_price)
            position["stop_stage"] = "BREAKEVEN_STOP"

        if max_r >= 2.0:
            locked_r = math.floor(max_r) - 1
            trailing_stop = entry_price + locked_r * risk_per_share
            position["active_stop"] = max(float(position["active_stop"]), trailing_stop)
            position["stop_stage"] = f"TRAILING_STOP_{locked_r}R"

    def _close_position(
        self,
        *,
        position: dict,
        exit_price: float,
        raw_exit_price: float,
        trade_time: pd.Timestamp,
        exit_reason: str,
    ) -> tuple[float, dict, dict]:
        quantity = int(position["quantity"])
        gross_proceeds = quantity * exit_price
        sell_commission = gross_proceeds * (self.config.commission_rate + self.config.transfer_fee_rate)
        tax = gross_proceeds * self.config.stamp_tax_rate
        realized_cash = gross_proceeds - sell_commission - tax
        buy_value = quantity * float(position["entry_price"])
        pnl = gross_proceeds - buy_value - float(position["buy_commission"]) - sell_commission - tax

        action_row = {
            "trade_id": position["trade_id"],
            "stock_code": position["stock_code"],
            "strategy_name": position["strategy_name"],
            "action": "SELL",
            "price": exit_price,
            "quantity": quantity,
            "trade_time": trade_time,
            "commission": sell_commission,
            "tax": tax,
            "slippage": quantity * (raw_exit_price - exit_price),
            "reason": exit_reason,
        }
        trade_record = {
            "trade_id": position["trade_id"],
            "stock_code": position["stock_code"],
            "stock_name": position["stock_name"],
            "strategy_name": position["strategy_name"],
            "trade_date": position["entry_date"],
            "buy_time": position["entry_time"],
            "buy_price": float(position["entry_price"]),
            "sell_time": trade_time,
            "sell_price": exit_price,
            "quantity": quantity,
            "pnl": pnl,
            "return_pct": pnl / buy_value if buy_value else 0.0,
            "commission": float(position["buy_commission"]) + sell_commission,
            "buy_commission": float(position["buy_commission"]),
            "sell_commission": sell_commission,
            "tax": tax,
            "slippage": quantity * (
                (float(position["entry_price"]) - float(position["raw_entry_price"])) + (raw_exit_price - exit_price)
            ),
            "total_cost": float(position["buy_commission"]) + sell_commission + tax,
            "stop_loss": float(position["initial_stop_loss"]),
            "risk_per_share": float(position["risk_per_share"]),
            "r_multiple": pnl / (float(position["risk_per_share"]) * quantity) if quantity and position["risk_per_share"] else 0.0,
            "max_r": float(position["max_r"]),
            "days_held": max((trade_time.date() - position["entry_date"]).days, 0),
            "exit_reason": exit_reason,
            "reason": position["entry_reason"],
        }
        return realized_cash, action_row, trade_record

    def _build_portfolio_snapshots(self, snapshots: pd.DataFrame) -> pd.DataFrame:
        if snapshots.empty:
            return pd.DataFrame()
        portfolio = snapshots.sort_values("snapshot_time").copy()
        portfolio["daily_pnl"] = portfolio["total_equity"].diff().fillna(portfolio["total_equity"] - self.config.initial_cash)
        portfolio["cumulative_return"] = portfolio["total_equity"] / self.config.initial_cash - 1.0
        running_max = portfolio["total_equity"].cummax()
        portfolio["drawdown"] = portfolio["total_equity"] / running_max - 1.0
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


def summarize_ema_cross_run(trades: pd.DataFrame, portfolio_snapshots: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {
            "trade_count": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "avg_r_multiple": 0.0,
            "max_r_multiple": 0.0,
            "max_drawdown": 0.0,
            "ending_equity": 0.0,
        }

    return {
        "trade_count": int(len(trades)),
        "total_pnl": float(trades["pnl"].sum()),
        "win_rate": float((trades["pnl"] > 0).mean()),
        "avg_r_multiple": float(trades["r_multiple"].mean()),
        "max_r_multiple": float(trades["max_r"].max()),
        "max_drawdown": float(portfolio_snapshots["drawdown"].min()) if not portfolio_snapshots.empty else 0.0,
        "ending_equity": float(portfolio_snapshots["total_equity"].iloc[-1]) if not portfolio_snapshots.empty else 0.0,
    }


class EmaCrossBacktestRunner:
    def __init__(self, config: EmaCrossBacktestConfig) -> None:
        self.config = config
        self.store = DuckDBStore(config.db_path)
        self.market_data = LocalMarketData(self.store)

    def run(self) -> dict[str, pd.DataFrame | str | dict[str, Path] | dict]:
        kline = self.market_data.get_kline(
            timeframe=self.config.timeframe,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            stock_codes=self.config.stock_codes,
        )
        if kline.empty:
            raise ValueError(f"No local {self.config.timeframe} K-line data found for requested symbols.")

        enriched = add_ema_cross_factors(
            kline,
            fast_period=self.config.fast_period,
            slow_period=self.config.slow_period,
        )
        signals = build_ema_cross_signals(enriched)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        result = EmaCrossBacktester(self.config).run(signals, enriched, run_id=run_id)
        trades = result["trades"]
        trade_actions = result["trade_actions"]
        portfolio_snapshots = result["portfolio_snapshots"]
        summary = summarize_ema_cross_run(trades, portfolio_snapshots)

        self._persist_run(
            run_id=run_id,
            signals=signals,
            trade_actions=trade_actions,
            portfolio_snapshots=portfolio_snapshots,
            summary=summary,
        )

        exporter = ReportExporter(self.config.export_root)
        outputs = exporter.export_csv_bundle(
            run_id=run_id,
            trades=trades,
            portfolio=portfolio_snapshots,
            problems=pd.DataFrame(columns=["problem_tag", "count"]),
        )
        signals_path = Path(self.config.export_root) / f"{run_id}_signals.csv"
        signals.to_csv(signals_path, index=False)
        outputs["signals"] = signals_path

        return {
            "run_id": run_id,
            "signals": signals,
            "trades": trades,
            "portfolio_snapshots": portfolio_snapshots,
            "summary": summary,
            "outputs": outputs,
        }

    def _persist_run(
        self,
        *,
        run_id: str,
        signals: pd.DataFrame,
        trade_actions: pd.DataFrame,
        portfolio_snapshots: pd.DataFrame,
        summary: dict[str, float | int],
    ) -> None:
        self.store.replace_backtest_run(
            run_id=run_id,
            run_type="ema_cross",
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            initial_cash=self.config.initial_cash,
            config={
                "timeframe": self.config.timeframe,
                "stock_codes": self.config.stock_codes,
                "fast_period": self.config.fast_period,
                "slow_period": self.config.slow_period,
                "risk_per_trade": self.config.risk_per_trade,
                "lot_size": self.config.lot_size,
                "commission_rate": self.config.commission_rate,
                "stamp_tax_rate": self.config.stamp_tax_rate,
                "transfer_fee_rate": self.config.transfer_fee_rate,
                "slippage_rate": self.config.slippage_rate,
                "entry_model": "next_bar_open_after_golden_cross",
                "initial_stop_model": "lowest_low_of_last_3_bars_before_entry",
                "trail_model": "1r_to_breakeven_then_floor(max_r)-1_from_2r",
            },
            result=summary,
        )
        self.store.replace_signals_for_run(run_id, self._prepare_signals(signals, run_id))
        self.store.replace_trades_for_run(run_id, trade_actions)
        self.store.replace_portfolio_snapshots_for_run(run_id, portfolio_snapshots)

    @staticmethod
    def _prepare_signals(signals: pd.DataFrame, run_id: str) -> pd.DataFrame:
        if signals.empty:
            return signals
        prepared = signals.copy()
        prepared["signal_id"] = [f"{run_id}_sig_{idx + 1:04d}" for idx in range(len(prepared))]
        return prepared[
            [
                "signal_id",
                "stock_code",
                "strategy_name",
                "action",
                "timeframe",
                "signal_time",
                "entry_price",
                "stop_loss",
                "take_profit",
                "score",
                "reason",
                "status",
            ]
        ]
