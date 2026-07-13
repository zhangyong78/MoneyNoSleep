from __future__ import annotations

import pandas as pd

from mns.review.capital_utilization_exporter import CapitalUtilizationExporter


def test_capital_utilization_exporter_writes_png(tmp_path):
    portfolio = pd.DataFrame(
        [
            {"snapshot_time": "2026-01-02", "total_equity": 1_000_000.0, "cash": 980_000.0, "market_value": 20_000.0},
            {"snapshot_time": "2026-01-05", "total_equity": 1_002_000.0, "cash": 960_000.0, "market_value": 42_000.0},
        ]
    )

    path = CapitalUtilizationExporter(tmp_path).export(portfolio, run_id="capital_run")

    assert path.exists()
    assert path.name == "capital_run_capital_utilization.png"
