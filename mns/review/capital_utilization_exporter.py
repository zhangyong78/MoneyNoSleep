from __future__ import annotations

from pathlib import Path

import pandas as pd

from mns.review.screenshot_exporter import resolve_chart_font_family


class CapitalUtilizationExporter:
    def __init__(self, root: str | Path = "data/reports/exports") -> None:
        self.root = Path(root)

    def export(self, portfolio: pd.DataFrame, *, run_id: str) -> Path:
        if portfolio.empty:
            raise ValueError("portfolio is empty")
        required = {"snapshot_time", "total_equity", "cash", "market_value"}
        missing = required - set(portfolio.columns)
        if missing:
            raise ValueError(f"portfolio missing columns: {sorted(missing)}")

        import matplotlib.pyplot as plt

        chart_font = resolve_chart_font_family()
        if chart_font:
            plt.rcParams["font.sans-serif"] = [chart_font, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        frame = portfolio.sort_values("snapshot_time").copy()
        frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"])
        frame["utilization_pct"] = (frame["market_value"] / frame["total_equity"].where(frame["total_equity"] > 0) * 100).fillna(0.0)

        fig, (ax_assets, ax_utilization) = plt.subplots(
            2,
            1,
            figsize=(10, 5.4),
            sharex=True,
            gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
        )
        ax_assets.plot(frame["snapshot_time"], frame["total_equity"], color="#1f2937", linewidth=2.0, label="总权益")
        ax_assets.plot(frame["snapshot_time"], frame["market_value"], color="#2563eb", linewidth=1.8, label="持仓市值")
        ax_assets.plot(frame["snapshot_time"], frame["cash"], color="#16a34a", linewidth=1.4, label="可用现金")
        ax_assets.fill_between(frame["snapshot_time"], 0, frame["market_value"], color="#2563eb", alpha=0.12)
        ax_assets.set_ylabel("金额（元）")
        ax_assets.legend(loc="best")
        ax_assets.grid(True, alpha=0.18, linestyle="--")
        ax_assets.yaxis.tick_right()

        ax_utilization.plot(frame["snapshot_time"], frame["utilization_pct"], color="#e11d48", linewidth=2.0)
        ax_utilization.fill_between(frame["snapshot_time"], 0, frame["utilization_pct"], color="#e11d48", alpha=0.14)
        ax_utilization.set_ylim(0, 100)
        ax_utilization.set_ylabel("占用率%")
        ax_utilization.grid(True, alpha=0.18, linestyle="--")
        ax_utilization.yaxis.tick_right()

        fig.autofmt_xdate(rotation=30)
        fig.subplots_adjust(left=0.06, right=0.94, top=0.95, bottom=0.14)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{run_id}_capital_utilization.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        return path
