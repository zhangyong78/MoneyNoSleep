from __future__ import annotations

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.review.html_report_exporter import HtmlReviewReportExporter


def test_html_report_exporter_writes_report(tmp_path):
    run_id = "report_run"
    store = DuckDBStore(tmp_path / "mns.duckdb")
    store.replace_backtest_run(
        run_id=run_id,
        run_type="quick_review",
        start_date="2026-01-01",
        end_date="2026-01-31",
        initial_cash=100000,
        config={},
        result={"trade_count": 0},
    )
    store.replace_candidates_for_run(
        run_id,
        pd.DataFrame(
            [
                {
                    "stock_code": "600000.SH",
                    "stock_name": "浦发银行",
                    "trade_date": "2026-01-02",
                    "bar_time": pd.Timestamp("2026-01-02"),
                    "timeframe": "1d",
                    "close": 10.0,
                    "score": 1,
                    "candidate_reason": "close>ma55",
                }
            ]
        ),
    )

    path = HtmlReviewReportExporter(store=store, root=tmp_path / "html").export_run(run_id)

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "Moneynosleep 复盘报告" in text
    assert "浦发银行" in text
