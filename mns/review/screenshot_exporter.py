from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

from mns.review.chart_indicators import ChartIndicatorSpec, add_price_overlay_indicators, load_default_price_overlay_indicators
from mns.review.chart_style import build_kline_colors


DEFAULT_CHART_FONT_CANDIDATES = ("Microsoft YaHei", "SimHei", "SimSun", "DengXian")


def resolve_chart_font_family(candidates: Sequence[str] = DEFAULT_CHART_FONT_CANDIDATES) -> str | None:
    from matplotlib import font_manager

    installed = {font.name for font in font_manager.fontManager.ttflist}
    return next((candidate for candidate in candidates if candidate in installed), None)


def select_trade_chart_window(
    kline: pd.DataFrame,
    trade: pd.Series | dict,
    *,
    lookback_bars: int = 60,
    after_sell_bars: int = 30,
) -> pd.DataFrame:
    """Keep the price context around one completed trade instead of plotting all history."""
    window = kline.sort_values("bar_time").copy()
    window["bar_time"] = pd.to_datetime(window["bar_time"])
    buy_time = pd.Timestamp(trade["buy_time"])
    sell_time = pd.Timestamp(trade.get("sell_time", buy_time))
    start_index = max(int(window["bar_time"].searchsorted(buy_time, side="left")) - lookback_bars, 0)
    end_index = min(int(window["bar_time"].searchsorted(sell_time, side="right")) + after_sell_bars, len(window))
    return window.iloc[start_index:end_index].copy()


def trade_marker_style(action: str) -> dict[str, object]:
    if action == "buy":
        return {"marker": "^", "s": 300, "color": "#e11d48", "edgecolors": "#7f1d1d", "linewidths": 1.6, "zorder": 12, "label": "买入"}
    if action == "sell":
        return {"marker": "v", "s": 300, "color": "#059669", "edgecolors": "#064e3b", "linewidths": 1.6, "zorder": 12, "label": "卖出"}
    raise ValueError(f"unsupported trade marker action: {action}")


class ScreenshotExporter:
    def __init__(self, root: str | Path = "data/reports/screenshots") -> None:
        self.root = Path(root)

    def export_trade_chart(
        self,
        trade: pd.Series | dict,
        kline: pd.DataFrame,
        *,
        run_id: str,
        indicators: Sequence[ChartIndicatorSpec] | None = None,
    ) -> Path:
        """Export a static PNG using A-share style candlesticks."""

        try:
            import matplotlib.dates as mdates
            import matplotlib.pyplot as plt
            from matplotlib.patches import Rectangle
        except ModuleNotFoundError as exc:
            raise RuntimeError("matplotlib is required to export screenshots. Run `pip install -e .`.") from exc

        chart_font = resolve_chart_font_family()
        if chart_font:
            plt.rcParams["font.sans-serif"] = [chart_font, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        indicators = tuple(indicators) if indicators is not None else load_default_price_overlay_indicators()
        stock_code = str(trade["stock_code"])
        trade_id = str(trade["trade_id"])
        out_dir = self.root / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{stock_code}_{trade_id}.png"

        stock_kline = select_trade_chart_window(kline[kline["stock_code"] == stock_code], trade)
        stock_kline = add_price_overlay_indicators(stock_kline, indicators)
        stock_kline["bar_time"] = pd.to_datetime(stock_kline["bar_time"])
        for column in ["open", "high", "low"]:
            if column not in stock_kline.columns:
                stock_kline[column] = stock_kline["close"]
        if "volume" not in stock_kline.columns:
            stock_kline["volume"] = 0.0
        stock_kline["kline_color"] = build_kline_colors(stock_kline)

        fig, (ax_price, ax_volume) = plt.subplots(
            2,
            1,
            figsize=(10, 5.4),
            sharex=True,
            gridspec_kw={"height_ratios": [4, 1], "hspace": 0.04},
        )

        x_values = mdates.date2num(stock_kline["bar_time"])
        candle_width = 0.6
        for x_value, row in zip(x_values, stock_kline.itertuples(index=False)):
            color = row.kline_color
            lower = min(row.open, row.close)
            height = max(abs(row.close - row.open), 0.001)
            ax_price.vlines(x_value, row.low, row.high, color=color, linewidth=1.1)
            ax_price.add_patch(
                Rectangle(
                    (x_value - candle_width / 2, lower),
                    candle_width,
                    height,
                    facecolor=color,
                    edgecolor=color,
                    linewidth=1.0,
                )
            )
            ax_volume.bar(x_value, row.volume, color=color, width=candle_width, alpha=0.8)

        for indicator in indicators:
            if indicator.column_name not in stock_kline.columns:
                continue
            ax_price.plot(
                stock_kline["bar_time"],
                stock_kline[indicator.column_name],
                color=indicator.color,
                linewidth=indicator.width,
                label=indicator.display_name,
            )

        buy_style = trade_marker_style("buy")
        sell_style = trade_marker_style("sell")
        ax_price.scatter(
            [pd.Timestamp(trade["buy_time"])],
            [trade["buy_price"]],
            **buy_style,
        )
        ax_price.scatter(
            [pd.Timestamp(trade["sell_time"])],
            [trade["sell_price"]],
            **sell_style,
        )
        ax_price.annotate(
            f"买入\n¥{float(trade['buy_price']):.2f}",
            xy=(pd.Timestamp(trade["buy_time"]), trade["buy_price"]),
            xytext=(0, 28),
            textcoords="offset points",
            ha="center",
            va="bottom",
            color=buy_style["color"],
            fontweight="bold",
            arrowprops={"arrowstyle": "-|>", "color": buy_style["color"], "lw": 1.4},
            zorder=13,
        )
        ax_price.annotate(
            f"卖出\n¥{float(trade['sell_price']):.2f}",
            xy=(pd.Timestamp(trade["sell_time"]), trade["sell_price"]),
            xytext=(0, -32),
            textcoords="offset points",
            ha="center",
            va="top",
            color=sell_style["color"],
            fontweight="bold",
            arrowprops={"arrowstyle": "-|>", "color": sell_style["color"], "lw": 1.4},
            zorder=13,
        )
        ax_price.set_title(f"{stock_code} {trade_id}")
        ax_price.legend(loc="best")
        ax_price.grid(True, alpha=0.18, linestyle="--")
        ax_price.yaxis.tick_right()
        ax_volume.yaxis.tick_right()
        ax_price.set_ylabel("价格")
        ax_volume.set_ylabel("成交量")
        ax_volume.grid(False)
        ax_volume.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate(rotation=30)
        fig.subplots_adjust(left=0.06, right=0.96, top=0.92, bottom=0.14)
        fig.savefig(path, dpi=150)
        plt.close(fig)
        return path
