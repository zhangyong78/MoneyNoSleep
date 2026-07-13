from __future__ import annotations

import html
import math
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.transforms import blended_transform_factory

from mns.factors.technical import ema
from mns.review.chart_indicators import add_price_overlay_indicators, load_default_price_overlay_indicators
from mns.review.chart_style import DOWN_COLOR, UP_COLOR, build_kline_colors


matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


def render_review_chart(
    figure: Figure,
    *,
    kline: pd.DataFrame,
    signals: pd.DataFrame | None,
    trades: pd.DataFrame | None,
    portfolio: pd.DataFrame | None,
    stock_code: str | None,
    run_id: str,
    strategy_id: str,
    timeframe: str,
    summary: dict[str, float | int] | None,
    initial_cash: float,
    fast_period: int = 21,
    slow_period: int = 55,
    risk_per_trade: float = 5_000.0,
    display_points: int = 260,
) -> dict[str, Any]:
    frame = _select_stock(kline, stock_code).copy()
    figure.clear()
    figure.patch.set_facecolor("#f3f6fb")

    if frame.empty:
        _draw_empty_figure(figure, "No K-line data to display.")
        return {"bar_times": [], "data_count": 0, "default_window": 0, "right_padding": 3.2}

    frame["bar_time"] = pd.to_datetime(frame["bar_time"], errors="coerce")
    frame = frame.dropna(subset=["bar_time"]).sort_values("bar_time").reset_index(drop=True)

    frame["open"] = pd.to_numeric(frame["open"], errors="coerce")
    frame["high"] = pd.to_numeric(frame["high"], errors="coerce")
    frame["low"] = pd.to_numeric(frame["low"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if frame.empty:
        _draw_empty_figure(figure, "Selected K-line data is invalid.")
        return {"bar_times": [], "data_count": 0, "default_window": 0, "right_padding": 3.2}

    frame["ema_fast"] = ema(frame["close"], fast_period)
    frame["ema_slow"] = ema(frame["close"], slow_period)

    trade_frame = _filter_by_stock(trades, stock_code, "stock_code")
    signal_frame = _filter_by_stock(signals, stock_code, "stock_code")
    portfolio_frame = _align_portfolio(frame["bar_time"], portfolio)
    x_values = np.arange(len(frame), dtype=float)
    time_lookup = {timestamp: index for index, timestamp in enumerate(frame["bar_time"])}

    grid = figure.add_gridspec(
        3,
        1,
        height_ratios=[6.4, 1.55, 1.15],
        left=0.045,
        right=0.95,
        top=0.91,
        bottom=0.08,
        hspace=0.04,
    )
    ax_price = figure.add_subplot(grid[0])
    ax_equity = figure.add_subplot(grid[1], sharex=ax_price)
    ax_drawdown = figure.add_subplot(grid[2], sharex=ax_price)
    axes = (ax_price, ax_equity, ax_drawdown)
    for axis in axes:
        axis.set_facecolor("#ffffff")
        for spine in axis.spines.values():
            spine.set_color("#d7dce5")
            spine.set_linewidth(0.8)

    _draw_headers(
        figure=figure,
        run_id=run_id,
        strategy_id=strategy_id,
        stock_code=stock_code or _first_text(frame.get("stock_code")),
        timeframe=timeframe,
        summary=summary or {},
        fast_period=fast_period,
        slow_period=slow_period,
        risk_per_trade=risk_per_trade,
    )

    candle_width = max(0.48, min(0.72, 0.78 - (len(frame) / 9000)))
    for idx, row in frame.iterrows():
        color = UP_COLOR if float(row["close"]) >= float(row["open"]) else DOWN_COLOR
        ax_price.vlines(idx, float(row["low"]), float(row["high"]), color=color, linewidth=0.85, zorder=2)
        body_bottom = min(float(row["open"]), float(row["close"]))
        body_height = abs(float(row["close"]) - float(row["open"]))
        if body_height < 1e-6:
            body_height = max((frame["high"].max() - frame["low"].min()) * 0.0015, 1e-4)
        ax_price.add_patch(
            Rectangle(
                (idx - candle_width / 2, body_bottom),
                candle_width,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.8,
                zorder=3,
            )
        )

    ax_price.plot(x_values, frame["ema_fast"], color="#f59e0b", linewidth=1.15, zorder=4)
    ax_price.plot(x_values, frame["ema_slow"], color="#4f6bdc", linewidth=1.15, zorder=4)

    if not signal_frame.empty:
        for _, signal in signal_frame.iterrows():
            signal_time = pd.to_datetime(signal.get("signal_time"), errors="coerce")
            if pd.isna(signal_time):
                continue
            bar_index = time_lookup.get(signal_time)
            if bar_index is None:
                continue
            signal_price = pd.to_numeric(signal.get("entry_price"), errors="coerce")
            if pd.isna(signal_price):
                signal_price = frame.iloc[bar_index]["close"]
            ax_price.scatter(
                [bar_index],
                [float(signal_price)],
                marker="o",
                s=8,
                color="#0ea5e9",
                alpha=0.65,
                zorder=5,
            )

    _draw_trade_overlays(ax_price, trade_frame, frame, time_lookup)

    net_values = pd.Series(index=frame.index, dtype=float)
    drawdown_values = pd.Series(index=frame.index, dtype=float)
    if not portfolio_frame.empty:
        net_values = portfolio_frame["total_equity"] / max(initial_cash, 1.0) * 1000.0
        drawdown_values = portfolio_frame["drawdown"].abs() * 100.0
    else:
        net_values = pd.Series([1000.0] * len(frame), index=frame.index, dtype=float)
        drawdown_values = pd.Series([0.0] * len(frame), index=frame.index, dtype=float)

    ax_equity.plot(x_values, net_values, color="#1d4ed8", linewidth=1.35, zorder=3)
    ax_drawdown.plot(x_values, drawdown_values, color="#ef4444", linewidth=1.15, zorder=3)
    ax_drawdown.fill_between(x_values, 0, drawdown_values, color="#fee2e2", alpha=0.35, zorder=2)

    _style_price_axis(ax_price, frame)
    _style_equity_axis(ax_equity, net_values)
    _style_drawdown_axis(ax_drawdown, drawdown_values)
    _style_shared_xaxis(ax_drawdown, frame["bar_time"])
    ax_price.tick_params(axis="x", which="both", bottom=False, labelbottom=False)
    ax_equity.tick_params(axis="x", which="both", bottom=False, labelbottom=False)

    _draw_info_box(ax_price, frame, net_values, drawdown_values, fast_period=fast_period, slow_period=slow_period)
    _draw_axis_tags(
        ax_price=ax_price,
        ax_equity=ax_equity,
        ax_drawdown=ax_drawdown,
        frame=frame,
        fast_period=fast_period,
        slow_period=slow_period,
    )

    right_padding = 3.2
    default_window = min(max(display_points, 60), len(frame))
    left_bound = max(-1.0, len(frame) - default_window - 1.0)
    ax_price.set_xlim(left_bound, len(frame) + right_padding)
    return {
        "bar_times": frame["bar_time"].tolist(),
        "data_count": len(frame),
        "default_window": default_window,
        "right_padding": right_padding,
    }


def build_portfolio_chart_html(portfolio: pd.DataFrame) -> str:
    import plotly.graph_objects as go

    if portfolio.empty or "total_equity" not in portfolio.columns:
        return _empty_html("No portfolio curve.")

    frame = portfolio.copy()
    frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"], errors="coerce")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=frame["snapshot_time"],
            y=frame["total_equity"],
            mode="lines",
            name="Equity",
            line={"color": "#0f766e", "width": 2.2},
        )
    )
    if "drawdown" in frame.columns:
        fig.add_trace(
            go.Scatter(
                x=frame["snapshot_time"],
                y=frame["drawdown"],
                mode="lines",
                name="Drawdown",
                yaxis="y2",
                line={"color": "#b91c1c", "width": 1.3},
            )
        )
    fig.update_layout(
        title={"text": "Portfolio Curve", "x": 0.02, "xanchor": "left"},
        height=520,
        margin={"l": 20, "r": 24, "t": 52, "b": 18},
        paper_bgcolor="#f8fafc",
        plot_bgcolor="#ffffff",
        hovermode="x unified",
        yaxis={"title": "Equity", "side": "right"},
        yaxis2={"title": "Drawdown", "overlaying": "y", "side": "left", "tickformat": ".1%"},
    )
    return fig.to_html(full_html=True, include_plotlyjs=True)


def build_kline_chart_html(
    kline: pd.DataFrame,
    *,
    signals: pd.DataFrame | None = None,
    trades: pd.DataFrame | None = None,
    stock_code: str | None = None,
    display_points: int = 260,
) -> str:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    frame = _select_stock(kline, stock_code).copy()
    if frame.empty:
        return _empty_html("暂无可展示的 K 线数据")

    frame["bar_time"] = pd.to_datetime(frame["bar_time"], errors="coerce")
    frame = frame.dropna(subset=["bar_time"]).sort_values("bar_time")
    if display_points > 0:
        frame = frame.tail(display_points).copy()
    frame = add_price_overlay_indicators(frame, load_default_price_overlay_indicators())

    x_values = frame["bar_time"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.76, 0.24])
    fig.add_trace(
        go.Candlestick(
            x=x_values,
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            name="K",
            increasing_line_color=UP_COLOR,
            increasing_fillcolor=UP_COLOR,
            decreasing_line_color=DOWN_COLOR,
            decreasing_fillcolor=DOWN_COLOR,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=x_values,
            y=frame.get("volume", pd.Series([0] * len(frame))),
            name="Volume",
            marker={"color": build_kline_colors(frame)},
            opacity=0.72,
        ),
        row=2,
        col=1,
    )
    for column, label, color in (("ema21", "EMA21", "#2563eb"), ("ema55", "EMA55", "#f59e0b")):
        if column in frame.columns:
            fig.add_trace(
                go.Scatter(x=x_values, y=frame[column], mode="lines", name=label, line={"color": color, "width": 1.6}),
                row=1,
                col=1,
            )
    fig.update_layout(
        title={"text": f"{stock_code or 'Backtest'} K-line", "x": 0.02, "xanchor": "left"},
        height=720,
        margin={"l": 20, "r": 24, "t": 52, "b": 18},
        paper_bgcolor="#f8fafc",
        plot_bgcolor="#ffffff",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "right", "x": 1},
    )
    fig.update_xaxes(rangeslider_visible=False, showspikes=True, spikemode="across")
    fig.update_yaxes(title_text="Price", side="right", fixedrange=False, row=1, col=1)
    fig.update_yaxes(title_text="Volume", side="right", fixedrange=False, showgrid=False, row=2, col=1)
    return fig.to_html(full_html=True, include_plotlyjs=True)


def _draw_headers(
    *,
    figure: Figure,
    run_id: str,
    strategy_id: str,
    stock_code: str | None,
    timeframe: str,
    summary: dict[str, float | int],
    fast_period: int,
    slow_period: int,
    risk_per_trade: float,
) -> None:
    total_pnl = float(summary.get("total_pnl", 0.0))
    win_rate = float(summary.get("win_rate", 0.0))
    max_drawdown = float(summary.get("max_drawdown", 0.0))
    ending_equity = float(summary.get("ending_equity", 0.0))
    trade_count = int(summary.get("trade_count", 0))
    description = "回测K线图：用于查看 K 线结构、EMA 轨迹、资金曲线、回撤曲线和止损/止盈定位。"
    config_line = (
        f"运行编号：{run_id} | 标的：{stock_code or '-'} | 周期：{timeframe} | "
        f"策略：{strategy_id} | EMA：{fast_period}/{slow_period} | 单笔风险：{risk_per_trade:,.0f}"
    )
    summary_line = (
        f"交易：{trade_count} | 胜率：{win_rate:.2%} | 总盈亏：{total_pnl:,.2f} | "
        f"最大回撤：{max_drawdown:.2%} | 期末权益：{ending_equity:,.2f}"
    )
    figure.text(0.012, 0.988, description, ha="left", va="top", fontsize=9, color="#374151")
    figure.text(0.012, 0.968, config_line, ha="left", va="top", fontsize=9, color="#374151")
    figure.text(0.012, 0.948, summary_line, ha="left", va="top", fontsize=9, color="#374151")


def _draw_trade_overlays(
    axis: Any,
    trades: pd.DataFrame,
    frame: pd.DataFrame,
    time_lookup: dict[pd.Timestamp, int],
) -> None:
    if trades.empty:
        return

    for _, trade in trades.iterrows():
        entry_time = pd.to_datetime(trade.get("buy_time"), errors="coerce")
        exit_time = pd.to_datetime(trade.get("sell_time"), errors="coerce")
        if pd.isna(entry_time) or pd.isna(exit_time):
            continue
        entry_index = time_lookup.get(entry_time)
        exit_index = time_lookup.get(exit_time)
        if entry_index is None or exit_index is None:
            continue

        buy_price = pd.to_numeric(trade.get("buy_price"), errors="coerce")
        sell_price = pd.to_numeric(trade.get("sell_price"), errors="coerce")
        stop_price = pd.to_numeric(trade.get("stop_loss"), errors="coerce")
        risk_per_share = pd.to_numeric(trade.get("risk_per_share"), errors="coerce")
        if pd.isna(buy_price) or pd.isna(sell_price):
            continue

        pnl = float(pd.to_numeric(trade.get("pnl"), errors="coerce"))
        exit_reason = str(trade.get("exit_reason") or "")
        exit_label = _trade_exit_label(exit_reason)
        exit_color = "#d92d20" if pnl <= 0 else "#16a34a"

        axis.plot(
            [entry_index, exit_index],
            [float(buy_price), float(sell_price)],
            color="#1f6feb",
            linewidth=1.15,
            zorder=5,
        )
        if not pd.isna(stop_price):
            axis.hlines(
                float(stop_price),
                xmin=entry_index,
                xmax=exit_index,
                colors="#ef4444",
                linestyles=(0, (2, 2)),
                linewidth=0.9,
                alpha=0.7,
                zorder=4,
            )
        if not pd.isna(risk_per_share) and float(risk_per_share) > 0:
            one_r = float(buy_price) + float(risk_per_share)
            two_r = float(buy_price) + (2 * float(risk_per_share))
            if float(pd.to_numeric(trade.get("max_r"), errors="coerce")) >= 1:
                axis.hlines(
                    one_r,
                    xmin=entry_index,
                    xmax=exit_index,
                    colors="#10b981",
                    linestyles=(0, (1, 2)),
                    linewidth=0.75,
                    alpha=0.5,
                    zorder=4,
                )
            if float(pd.to_numeric(trade.get("max_r"), errors="coerce")) >= 2:
                axis.hlines(
                    two_r,
                    xmin=entry_index,
                    xmax=exit_index,
                    colors="#14b8a6",
                    linestyles=(0, (1, 2)),
                    linewidth=0.75,
                    alpha=0.45,
                    zorder=4,
                )

        axis.scatter([entry_index], [float(buy_price)], s=20, color="#1f6feb", zorder=6)
        axis.scatter([exit_index], [float(sell_price)], s=24, color=exit_color, zorder=6)
        label_dx = -0.9 if exit_index >= len(frame) - 24 else 0.9
        axis.text(
            exit_index + label_dx,
            float(sell_price),
            exit_label,
            ha="right" if label_dx < 0 else "left",
            va="center",
            fontsize=8.5,
            fontweight="bold",
            color="#ffffff",
            bbox={
                "boxstyle": "round,pad=0.18,rounding_size=0.05",
                "fc": exit_color,
                "ec": "#ffffff",
                "lw": 0.9,
            },
            zorder=7,
        )


def _draw_info_box(
    axis: Any,
    frame: pd.DataFrame,
    net_values: pd.Series,
    drawdown_values: pd.Series,
    *,
    fast_period: int,
    slow_period: int,
) -> None:
    last = frame.iloc[-1]
    last_net = float(net_values.iloc[-1]) if len(net_values) else 1000.0
    last_drawdown = float(drawdown_values.iloc[-1]) if len(drawdown_values) else 0.0
    info_lines = [
        f"时间：{pd.Timestamp(last['bar_time']).strftime('%Y-%m-%d %H:%M')}",
        f"开/高/低/收：{float(last['open']):.4f} / {float(last['high']):.4f} / {float(last['low']):.4f} / {float(last['close']):.4f}",
        f"EMA({fast_period}): {float(last['ema_fast']):.4f}" if pd.notna(last["ema_fast"]) else f"EMA({fast_period}): -",
        f"EMA({slow_period}): {float(last['ema_slow']):.4f}" if pd.notna(last["ema_slow"]) else f"EMA({slow_period}): -",
        f"净值曲线：{last_net:.2f}",
        f"当前回撤：{last_drawdown:.2f}%",
    ]
    axis.text(
        0.012,
        0.98,
        "\n".join(info_lines),
        transform=axis.transAxes,
        ha="left",
        va="top",
        fontsize=8.3,
        color="#374151",
        bbox={"boxstyle": "square,pad=0.35", "fc": "#ffffff", "ec": "#d7dce5", "lw": 0.8, "alpha": 0.96},
        zorder=10,
    )


def _draw_axis_tags(
    *,
    ax_price: Any,
    ax_equity: Any,
    ax_drawdown: Any,
    frame: pd.DataFrame,
    fast_period: int,
    slow_period: int,
) -> None:
    transform_price = blended_transform_factory(ax_price.transAxes, ax_price.transData)
    transform_equity = blended_transform_factory(ax_equity.transAxes, ax_equity.transData)
    transform_drawdown = blended_transform_factory(ax_drawdown.transAxes, ax_drawdown.transData)

    last_close = float(frame["close"].iloc[-1])
    ax_price.text(1.004, last_close, f"收 {last_close:.4f}", transform=transform_price, color="#15803d", fontsize=9, fontweight="bold", ha="left", va="center")

    last_fast = frame["ema_fast"].dropna()
    if not last_fast.empty:
        ax_price.text(
            1.004,
            float(last_fast.iloc[-1]),
            f"EMA({fast_period})",
            transform=transform_price,
            color="#f59e0b",
            fontsize=9,
            fontweight="bold",
            ha="left",
            va="center",
        )

    last_slow = frame["ema_slow"].dropna()
    if not last_slow.empty:
        ax_price.text(
            1.004,
            float(last_slow.iloc[-1]),
            f"EMA({slow_period})",
            transform=transform_price,
            color="#4f6bdc",
            fontsize=9,
            fontweight="bold",
            ha="left",
            va="center",
        )

    y0_equity, y1_equity = ax_equity.get_ylim()
    ax_equity.text(
        1.004,
        y0_equity + ((y1_equity - y0_equity) * 0.82),
        "净值曲线",
        transform=transform_equity,
        color="#1d4ed8",
        fontsize=9,
        fontweight="bold",
        ha="left",
        va="center",
    )
    y0_drawdown, y1_drawdown = ax_drawdown.get_ylim()
    ax_drawdown.text(
        1.004,
        y1_drawdown + ((y0_drawdown - y1_drawdown) * 0.18),
        "回撤曲线(%)",
        transform=transform_drawdown,
        color="#ef4444",
        fontsize=9,
        fontweight="bold",
        ha="left",
        va="center",
    )


def _style_price_axis(axis: Any, frame: pd.DataFrame) -> None:
    price_min = float(frame["low"].min())
    price_max = float(frame["high"].max())
    padding = max((price_max - price_min) * 0.08, 1e-3)
    axis.set_ylim(price_min - padding, price_max + padding)
    axis.grid(axis="y", color="#e7ebf2", linestyle="--", linewidth=0.7)
    axis.tick_params(axis="y", labelsize=9, colors="#64748b", length=0)
    axis.tick_params(axis="x", length=0)
    axis.yaxis.set_major_locator(plt_locator(max_ticks=5))
    axis.yaxis.set_major_formatter(plt_price_formatter())


def _style_equity_axis(axis: Any, net_values: pd.Series) -> None:
    net_min = float(net_values.min())
    net_max = float(net_values.max())
    padding = max((net_max - net_min) * 0.12, 0.6)
    axis.set_ylim(net_min - padding, net_max + padding)
    axis.grid(axis="y", color="#edf2f7", linestyle="--", linewidth=0.65)
    axis.tick_params(axis="y", labelsize=8.5, colors="#64748b", length=0)
    axis.tick_params(axis="x", length=0)
    axis.yaxis.set_major_locator(plt_locator(max_ticks=3))
    axis.yaxis.set_major_formatter(plt_fixed_formatter(decimals=2))


def _style_drawdown_axis(axis: Any, drawdown_values: pd.Series) -> None:
    max_drawdown = max(float(drawdown_values.max()), 0.6)
    axis.set_ylim(max_drawdown * 1.08, 0.0)
    axis.grid(axis="y", color="#edf2f7", linestyle="--", linewidth=0.65)
    axis.tick_params(axis="y", labelsize=8.5, colors="#64748b", length=0)
    axis.tick_params(axis="x", labelsize=8.5, colors="#64748b", length=0)
    axis.yaxis.set_major_locator(plt_locator(max_ticks=3))
    axis.yaxis.set_major_formatter(plt_percent_formatter())


def _style_shared_xaxis(axis: Any, bar_times: pd.Series) -> None:
    label_count = min(8, max(4, math.ceil(len(bar_times) / 45)))
    tick_positions = np.linspace(0, len(bar_times) - 1, label_count).round().astype(int)
    tick_positions = np.unique(tick_positions)
    axis.set_xticks(tick_positions)

    time_span = bar_times.iloc[-1] - bar_times.iloc[0] if len(bar_times) > 1 else pd.Timedelta(0)
    intraday = time_span < pd.Timedelta(days=7) or any(bar_times.dt.hour.ne(0))
    fmt = "%m-%d\n%H:%M" if intraday else "%Y-%m-%d"
    axis.set_xticklabels([bar_times.iloc[int(position)].strftime(fmt) for position in tick_positions])


def _align_portfolio(bar_times: pd.Series, portfolio: pd.DataFrame | None) -> pd.DataFrame:
    if portfolio is None or portfolio.empty:
        return pd.DataFrame(columns=["bar_time", "total_equity", "drawdown"])

    frame = portfolio.copy()
    frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"], errors="coerce")
    frame = frame.dropna(subset=["snapshot_time"]).sort_values("snapshot_time")
    if frame.empty:
        return pd.DataFrame(columns=["bar_time", "total_equity", "drawdown"])

    aligned = pd.DataFrame({"bar_time": pd.to_datetime(bar_times)})
    aligned = aligned.merge(
        frame[["snapshot_time", "total_equity", "drawdown"]],
        left_on="bar_time",
        right_on="snapshot_time",
        how="left",
    )
    aligned["total_equity"] = pd.to_numeric(aligned["total_equity"], errors="coerce").ffill().bfill()
    aligned["drawdown"] = pd.to_numeric(aligned["drawdown"], errors="coerce").fillna(0.0)
    return aligned


def _filter_by_stock(frame: pd.DataFrame | None, stock_code: str | None, key: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    selected = frame.copy()
    if stock_code and key in selected.columns:
        selected = selected[selected[key].astype(str) == str(stock_code)]
    return selected.reset_index(drop=True)


def _select_stock(kline: pd.DataFrame, stock_code: str | None) -> pd.DataFrame:
    if kline.empty:
        return kline
    if stock_code and "stock_code" in kline.columns:
        selected = kline[kline["stock_code"].astype(str) == str(stock_code)]
        if not selected.empty:
            return selected
    first_code = str(kline["stock_code"].dropna().iloc[0]) if "stock_code" in kline.columns and not kline["stock_code"].dropna().empty else None
    return kline[kline["stock_code"].astype(str) == first_code] if first_code else kline


def _draw_empty_figure(figure: Figure, message: str) -> None:
    axis = figure.add_subplot(111)
    axis.set_facecolor("#f8fafc")
    axis.set_xticks([])
    axis.set_yticks([])
    for spine in axis.spines.values():
        spine.set_visible(False)
    axis.text(0.5, 0.5, message, ha="center", va="center", fontsize=11, color="#64748b", transform=axis.transAxes)


def _trade_exit_label(exit_reason: str) -> str:
    reason = str(exit_reason or "").upper()
    if reason == "INITIAL_STOP":
        return "SL"
    if reason == "BREAKEVEN_STOP":
        return "BE"
    if reason.startswith("TRAILING_STOP_"):
        return reason.replace("TRAILING_STOP_", "")
    if reason == "END_OF_TEST":
        return "平"
    return "SL"


def _first_text(series: pd.Series | None) -> str | None:
    if series is None:
        return None
    non_null = series.dropna()
    if non_null.empty:
        return None
    return str(non_null.iloc[0])


def _empty_html(message: str) -> str:
    return (
        "<html><body style='font-family:Segoe UI,sans-serif;background:#f8fafc;color:#475569;padding:32px;'>"
        f"{html.escape(message)}</body></html>"
    )


def plt_locator(*, max_ticks: int):
    from matplotlib.ticker import MaxNLocator

    return MaxNLocator(nbins=max_ticks, prune=None)


def plt_price_formatter():
    from matplotlib.ticker import FuncFormatter

    return FuncFormatter(lambda value, _: f"{value:.4f}" if abs(value) < 10 else f"{value:.2f}")


def plt_fixed_formatter(*, decimals: int):
    from matplotlib.ticker import FuncFormatter

    return FuncFormatter(lambda value, _: f"{value:.{decimals}f}")


def plt_percent_formatter():
    from matplotlib.ticker import FuncFormatter

    return FuncFormatter(lambda value, _: f"{value:.2f}%")
