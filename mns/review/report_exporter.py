from __future__ import annotations

from pathlib import Path

import pandas as pd


class ReportExporter:
    def __init__(self, root: str | Path = "data/reports/exports") -> None:
        self.root = Path(root)

    def export_csv_bundle(self, *, run_id: str, trades: pd.DataFrame, portfolio: pd.DataFrame, problems: pd.DataFrame) -> dict[str, Path]:
        self.root.mkdir(parents=True, exist_ok=True)
        outputs = {
            "trades": self.root / f"{run_id}_trades.csv",
            "portfolio": self.root / f"{run_id}_portfolio.csv",
            "problems": self.root / f"{run_id}_problems.csv",
        }
        trades.to_csv(outputs["trades"], index=False)
        portfolio.to_csv(outputs["portfolio"], index=False)
        problems.to_csv(outputs["problems"], index=False)
        return outputs
