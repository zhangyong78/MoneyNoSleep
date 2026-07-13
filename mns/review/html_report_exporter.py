from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.review.problem_analyzer import count_problem_tags
from mns.review.trade_pairs import pair_trade_actions


class HtmlReviewReportExporter:
    def __init__(self, *, store: DuckDBStore, root: str | Path = "data/reports/html") -> None:
        self.store = store
        self.root = Path(root)

    def export_run(self, run_id: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        runs = self.store.list_backtest_runs(limit=200)
        run = runs[runs["run_id"].astype(str) == str(run_id)]
        if run.empty:
            raise ValueError(f"run not found: {run_id}")

        candidates = self.store.get_run_candidates(run_id)
        signals = self.store.get_run_signals(run_id)
        trades = pair_trade_actions(self.store.get_run_trades(run_id))
        portfolio = self.store.get_run_portfolio_snapshots(run_id)
        reviews = self.store.get_run_trade_reviews(run_id)
        screenshots = self.store.get_run_trade_screenshots(run_id)
        problems = count_problem_tags(reviews)

        path = self.root / f"{run_id}.html"
        path.write_text(
            self._render(
                run=run.iloc[0],
                candidates=candidates,
                signals=signals,
                trades=trades,
                portfolio=portfolio,
                reviews=reviews,
                screenshots=screenshots,
                problems=problems,
            ),
            encoding="utf-8",
        )
        return path

    def _render(
        self,
        *,
        run: pd.Series,
        candidates: pd.DataFrame,
        signals: pd.DataFrame,
        trades: pd.DataFrame,
        portfolio: pd.DataFrame,
        reviews: pd.DataFrame,
        screenshots: pd.DataFrame,
        problems: pd.DataFrame,
    ) -> str:
        title = f"Moneynosleep 复盘报告 {html.escape(str(run['run_id']))}"
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", sans-serif; margin: 32px; color: #17202a; }}
    h1, h2 {{ margin: 0 0 14px; }}
    h2 {{ margin-top: 28px; border-bottom: 1px solid #d8dee4; padding-bottom: 8px; }}
    .summary {{ display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 12px; margin: 18px 0 24px; }}
    .metric {{ border: 1px solid #d8dee4; border-radius: 8px; padding: 12px; background: #f8fafc; }}
    .metric span {{ display: block; color: #5b6773; font-size: 13px; }}
    .metric strong {{ display: block; margin-top: 6px; font-size: 20px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 8px; }}
    th, td {{ border: 1px solid #d8dee4; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #eef2f6; }}
    .empty {{ color: #697386; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <div class="summary">
    {self._metric("候选股", len(candidates))}
    {self._metric("信号", len(signals))}
    {self._metric("交易", len(trades))}
    {self._metric("复核", len(reviews))}
  </div>
  <h2>资金曲线</h2>
  {self._table(portfolio)}
  <h2>交易明细</h2>
  {self._table(trades)}
  <h2>候选股</h2>
  {self._table(candidates)}
  <h2>策略信号</h2>
  {self._table(signals)}
  <h2>人工复核</h2>
  {self._table(reviews)}
  <h2>问题归因</h2>
  {self._table(problems)}
  <h2>截图索引</h2>
  {self._table(screenshots)}
</body>
</html>
"""

    @staticmethod
    def _metric(label: str, value: int | float | str) -> str:
        return f'<div class="metric"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>'

    @staticmethod
    def _table(df: pd.DataFrame) -> str:
        if df.empty:
            return '<p class="empty">暂无数据</p>'
        return df.to_html(index=False, escape=True)
