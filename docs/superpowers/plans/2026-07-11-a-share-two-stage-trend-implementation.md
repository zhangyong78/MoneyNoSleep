# A股两阶段趋势选股与回测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily A-share strategy that turns the user's two-stage watch-then-buy judgement into ST-excluded candidates and a 200,000 CNY, ten-position, next-open backtest with a 10% initial stop and ATR trailing exit.

**Architecture:** Keep signal construction, portfolio simulation, and orchestration separate. `mns.strategies.two_stage_trend` derives only signal-day features and watch/buy signals; `mns.backtest.two_stage_trend` schedules next-open orders and maintains position state; `mns.pipelines.two_stage_trend_review` loads the non-ST universe, persists/export results, validates the time split, and optionally emits marked sample charts.

**Tech Stack:** Python 3.11, pandas, DuckDB, matplotlib, PyYAML, pytest.

## Global Constraints

- Read only local DuckDB/Parquet data; do not access an external market-data source.
- Use only `1d` bars and information available on the signal date; buy and sell orders execute on the next trading day's open.
- Exclude all `ST` and `*ST` stocks from candidates, signals, orders, calibration, and performance metrics.
- Default capital is 200,000 CNY, maximum concurrent positions is 10, and all quantities are rounded down to 100-share board lots.
- Initial risk is 10% of entry price; at +1R stop moves to breakeven; at +2R the close-based ATR(14) trailing stop is active.
- Preserve existing strategies and commands. Do not add live trading, external APIs, machine learning, sector rotation, or unrelated UI changes.
- The workspace has no `.git` directory. Do not attempt git commits; record the completed test command in the final implementation summary instead.

---

## File Structure

- Create: `mns/strategies/two_stage_trend.py` — signal-day feature derivation, observation-window state, ST name filter, candidate rows, and BUY signals.
- Create: `mns/backtest/two_stage_trend.py` — next-open order simulator, ten-slot equal-weight allocation, stop state machine, trade/portfolio metrics.
- Create: `mns/pipelines/two_stage_trend_review.py` — local non-ST universe loading, one-run orchestration, persistence, CSV exports, time-split preset validation, and marked K-line export.
- Modify: `mns/__main__.py` — add `run-two-stage-trend-backtest` CLI command and parameter flags.
- Create: `tests/test_two_stage_trend_strategy.py` — unit tests for factor boundaries, watch expiration, scoring, and ST exclusion.
- Create: `tests/test_two_stage_trend_backtest.py` — unit tests for next-open scheduling, ten-slot sizing, breakeven, ATR trailing, and metrics.
- Create: `tests/test_two_stage_trend_review.py` — runner validation and non-ST code conversion tests using a temporary DuckDB/cache fixture.
- Create: `tests/test_two_stage_trend_cli.py` — parser/dispatch smoke test for the new command.

### Task 1: Implement deterministic two-stage daily signals

**Files:**
- Create: `mns/strategies/two_stage_trend.py`
- Create: `tests/test_two_stage_trend_strategy.py`

**Interfaces:**
- Consumes: normalized daily K-line rows with `stock_code`, `stock_name`, `trade_date`, `bar_time`, `open`, `high`, `low`, `close`, `volume`, `limit_up_price`.
- Produces: `TwoStageTrendStrategy.enrich(data: pd.DataFrame) -> pd.DataFrame`, `TwoStageTrendStrategy.build_candidates(data: pd.DataFrame) -> pd.DataFrame`, and `TwoStageTrendStrategy.generate_signals(data: pd.DataFrame) -> pd.DataFrame`.
- Signal rows include `stock_code`, `stock_name`, `trade_date`, `bar_time`, `strategy_name`, `action`, `timeframe`, `signal_time`, `entry_date`, `score`, `volume_ratio_5`, `breakout_pct`, `attention_reason`, `reason`, and `status`.

- [ ] **Step 1: Write failing feature and state tests**

```python
def test_two_stage_signal_requires_prior_attention_and_two_confirmation_points():
    data = make_daily_bars(
        closes=[10, 10, 10, 10, 10, 10.7, 10.5, 10.4, 10.6, 11.0, 11.3],
        volumes=[100] * 5 + [220] + [90, 90, 100, 160, 180],
        limit_up_prices=[None] * 11,
    )
    strategy = TwoStageTrendStrategy(
        TwoStageTrendStrategyConfig(
            ma10_window=3,
            ma20_window=4,
            ma60_window=5,
            attention_window=5,
            chase_window=5,
        )
    )

    signals = strategy.generate_signals(data)

    assert signals["trade_date"].tolist() == [pd.Timestamp("2026-01-15").date()]
    assert signals.iloc[0]["attention_reason"] == "strong_bar"
    assert {"trend_base", "range_breakout", "volume_confirm"} <= set(signals.iloc[0]["reason"].split(";"))


def test_watch_expires_and_st_rows_never_emit_candidates():
    data = make_daily_bars(closes=[10] * 8 + [10.8] + [10.9] * 61, volumes=[100] * 70)
    data["stock_name"] = "*ST样本"

    result = TwoStageTrendStrategy(TwoStageTrendStrategyConfig(attention_window=60)).build_candidates(data)

    assert result.empty
```

- [ ] **Step 2: Run the new tests and verify failure**

Run: `pytest tests/test_two_stage_trend_strategy.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'mns.strategies.two_stage_trend'`.

- [ ] **Step 3: Implement factors, attention state, and buy scoring**

```python
@dataclass(frozen=True)
class TwoStageTrendStrategyConfig:
    attention_window: int = 60
    strong_change_pct: float = 0.06
    strong_volume_ratio: float = 1.8
    limit_up_close_ratio: float = 0.985
    breakout_window: int = 60
    breakout_volume_ratio: float = 1.5
    ma10_window: int = 10
    ma20_window: int = 20
    ma60_window: int = 60
    ma20_slope_days: int = 3
    consolidation_window: int = 5
    entry_volume_ratio: float = 1.2
    max_chase_pct: float = 0.12
    chase_window: int = 20


class TwoStageTrendStrategy:
    name = "two_stage_trend"
    timeframe = "1d"

    def enrich(self, data: pd.DataFrame) -> pd.DataFrame:
        frame = data.sort_values(["stock_code", "bar_time"]).copy()
        grouped = frame.groupby("stock_code", group_keys=False)
        frame["ma10"] = grouped["close"].transform(lambda s: s.rolling(self.config.ma10_window, min_periods=self.config.ma10_window).mean())
        frame["ma20"] = grouped["close"].transform(lambda s: s.rolling(self.config.ma20_window, min_periods=self.config.ma20_window).mean())
        frame["ma60"] = grouped["close"].transform(lambda s: s.rolling(self.config.ma60_window, min_periods=self.config.ma60_window).mean())
        frame["atr14"] = grouped.apply(lambda part: atr(part, 14), include_groups=False).reset_index(level=0, drop=True)
        frame["volume_ma20"] = grouped["volume"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
        frame["volume_ratio_20"] = frame["volume"] / frame["volume_ma20"]
        frame["volume_ratio_5"] = frame["volume"] / grouped["volume"].transform(lambda s: s.shift(1).rolling(5, min_periods=5).mean())
        frame["prior_high_60"] = grouped["close"].transform(lambda s: s.shift(1).rolling(self.config.breakout_window, min_periods=self.config.breakout_window).max())
        frame["prior_high_5"] = grouped["close"].transform(lambda s: s.shift(1).rolling(self.config.consolidation_window, min_periods=self.config.consolidation_window).max())
        frame["prior_high_20"] = grouped["close"].transform(lambda s: s.shift(1).rolling(self.config.chase_window, min_periods=self.config.chase_window).max())
        return frame
```

Implement `attention_strong_bar`, `attention_breakout`, and `attention_ma60_cross` as boolean columns. Build `watch_active` from the rolling maximum of the attention row number in the preceding `attention_window` bars. Require `~stock_name.fillna("").str.upper().str.contains("ST")` for every candidate. A buy row requires `trend_base` plus at least two of `range_breakout`, `volume_confirm`, and `not_chasing`; construct the semicolon-separated reason from the true column names. Set `entry_date` with the next daily bar's date only; never read a future open or high in this module.

- [ ] **Step 4: Run focused tests and style checks**

Run: `pytest tests/test_two_stage_trend_strategy.py -q`

Expected: PASS.

Run: `python -m compileall mns/strategies/two_stage_trend.py`

Expected: `Compiling 'mns/strategies/two_stage_trend.py'...` with exit code 0.

- [ ] **Step 5: Record completion without commit**

Run: `git rev-parse --show-toplevel`

Expected: exit code 1 because this workspace is not a Git repository; do not run `git add` or `git commit`.

### Task 2: Implement the daily portfolio and risk-state simulator

**Files:**
- Create: `mns/backtest/two_stage_trend.py`
- Create: `tests/test_two_stage_trend_backtest.py`

**Interfaces:**
- Consumes: signal rows from `TwoStageTrendStrategy.generate_signals` and enriched daily bars containing `open`, `close`, `limit_up_price`, `limit_down_price`, `is_suspended`, and `atr14`.
- Produces: `TwoStageTrendBacktester.run(signals, bars, run_id) -> dict[str, pd.DataFrame | str]` with keys `run_id`, `trades`, `trade_actions`, `portfolio_snapshots`, and `skipped_orders`.
- Configures: `TwoStageTrendBacktestConfig(initial_cash=200_000, max_positions=10, initial_stop_pct=0.10, breakeven_r=1.0, trail_start_r=2.0, atr_multiple=2.0, atr_window=14, lot_size=100, commission_rate=0.0003, stamp_tax_rate=0.001, transfer_fee_rate=0.00001, slippage_rate=0.0005)`.

- [ ] **Step 1: Write failing state-machine tests**

```python
def test_orders_fill_next_open_with_ten_equal_slots_and_respect_board_lots():
    signals = make_signals(signal_date="2026-01-02", codes=[f"600{i:03d}.SH" for i in range(11)])
    bars = make_next_open_bars(signals, open_price=10.0)

    result = TwoStageTrendBacktester(TwoStageTrendBacktestConfig(initial_cash=200_000, max_positions=10, commission_rate=0, stamp_tax_rate=0, slippage_rate=0)).run(signals, bars, run_id="slots")

    buys = result["trade_actions"].query("action == 'BUY'")
    assert len(buys) == 10
    assert set(buys["quantity"]) == {2000}
    assert result["skipped_orders"].iloc[0]["reason"] == "position_limit"


def test_close_based_stop_moves_to_breakeven_then_atr_trail_and_sells_next_open():
    bars = make_r_progression_bars(
        entry=10.0,
        closes=[10.0, 11.1, 12.2, 13.0, 10.4, 10.1],
        opens=[10.0, 10.0, 11.1, 12.2, 13.0, 10.1],
        atr14=1.0,
    )
    result = TwoStageTrendBacktester(no_cost_config()).run(make_one_signal(), bars, run_id="trail")

    trade = result["trades"].iloc[0]
    assert trade["exit_reason"] == "atr_trailing_stop"
    assert trade["sell_price"] == pytest.approx(10.1)
    assert trade["r_multiple"] > 0
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/test_two_stage_trend_backtest.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'mns.backtest.two_stage_trend'`.

- [ ] **Step 3: Implement next-open execution and exit state**

```python
@dataclass(frozen=True)
class TwoStageTrendBacktestConfig:
    initial_cash: float = 200_000.0
    max_positions: int = 10
    initial_stop_pct: float = 0.10
    breakeven_r: float = 1.0
    trail_start_r: float = 2.0
    atr_multiple: float = 2.0
    lot_size: int = 100
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001
    transfer_fee_rate: float = 0.00001
    slippage_rate: float = 0.0005


def _target_quantity(*, equity: float, cash: float, entry_price: float, config: TwoStageTrendBacktestConfig) -> int:
    slot_cash = equity / config.max_positions
    affordable = min(slot_cash, cash)
    return max(int(affordable // (entry_price * config.lot_size)) * config.lot_size, 0)


def _next_stop(position: dict[str, object], bar: pd.Series, config: TwoStageTrendBacktestConfig) -> tuple[float, str]:
    highest_close = max(float(position["highest_close"]), float(bar["close"]))
    entry = float(position["entry_price"])
    r_value = float(position["r_value"])
    stop = float(position["active_stop"])
    if highest_close >= entry + config.breakeven_r * r_value:
        stop = max(stop, entry)
    if highest_close >= entry + config.trail_start_r * r_value:
        stop = max(stop, entry, highest_close - config.atr_multiple * float(bar["atr14"]))
        return stop, "atr_trailing_stop"
    return stop, "breakeven_stop" if stop >= entry else "initial_stop"
```

For each date, execute pending sells at that date's open first, then fill pending buys in descending `score`, `volume_ratio_5`, `breakout_pct` order until cash or the ten-position limit is exhausted. Reject buy fills with missing/zero open, suspension, or an open at/above `limit_up_price`; retain a skipped-order record. At the close, update `highest_close` and `active_stop`; if the close is below the active stop, queue a sell for the next trading day. Apply slippage and configured fees to actual fills. Force-close remaining open positions at the final available close with `end_of_test` reason.

- [ ] **Step 4: Calculate and test reporting metrics**

```python
def summarize_two_stage_trend_run(trades: pd.DataFrame, portfolio: pd.DataFrame) -> dict[str, float | int]:
    wins = trades.loc[trades["pnl"] > 0, "pnl"]
    losses = trades.loc[trades["pnl"] < 0, "pnl"]
    gross_profit = float(wins.sum())
    gross_loss = abs(float(losses.sum()))
    return {
        "trade_count": int(len(trades)),
        "win_rate": float((trades["pnl"] > 0).mean()) if len(trades) else 0.0,
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "profit_loss_ratio": abs(float(wins.mean()) / float(losses.mean())) if len(wins) and len(losses) else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else 0.0,
        "max_drawdown": float(portfolio["drawdown"].min()) if not portfolio.empty else 0.0,
    }
```

Add assertions for win rate, profit/loss ratio, profit factor, and the maximum drawdown calculated from `total_equity.cummax()`.

- [ ] **Step 5: Run backtest tests**

Run: `pytest tests/test_two_stage_trend_backtest.py -q`

Expected: PASS.

Run: `python -m compileall mns/backtest/two_stage_trend.py`

Expected: exit code 0.

### Task 3: Orchestrate non-ST local data, exports, persistence, and marked charts

**Files:**
- Create: `mns/pipelines/two_stage_trend_review.py`
- Create: `tests/test_two_stage_trend_review.py`

**Interfaces:**
- Consumes: `TwoStageTrendStrategy`, `TwoStageTrendBacktester`, `LocalMarketData`, `KhQuantCacheStore`, `DuckDBStore`, and `ReportExporter`.
- Produces: `TwoStageTrendReviewRunner.run() -> dict[str, object]` containing `run_id`, `candidates`, `signals`, `trades`, `portfolio_snapshots`, `skipped_orders`, `summary`, `outputs`, `development_summary`, and `validation_summary`.
- Configures: `TwoStageTrendReviewConfig(db_path, khquant_cache_path, start_date, end_date, initial_cash, max_positions, sample_codes, export_root, strategy, backtest)`.

- [ ] **Step 1: Write failing runner tests**

```python
def test_runner_converts_cache_codes_and_excludes_st_before_loading_bars(tmp_path, monkeypatch):
    cache = write_cache(tmp_path / "cache.duckdb", [
        {"code": "sh.600000", "name": "浦发银行", "is_st": False},
        {"code": "sh.600001", "name": "ST样本", "is_st": True},
    ])
    loaded_codes: list[str] = []

    monkeypatch.setattr(LocalMarketData, "get_kline", lambda self, **kwargs: loaded_codes.extend(kwargs["stock_codes"]) or fixture_bars())
    result = TwoStageTrendReviewRunner(TwoStageTrendReviewConfig(khquant_cache_path=str(cache), start_date="2026-01-01", end_date="2026-03-31")).run()

    assert loaded_codes == ["600000.SH"]
    assert not result["signals"]["stock_name"].fillna("").str.upper().str.contains("ST").any()


def test_runner_exports_signal_and_sample_chart_files(tmp_path, monkeypatch):
    monkeypatch.setattr(LocalMarketData, "get_kline", lambda self, **kwargs: fixture_bars())
    result = TwoStageTrendReviewRunner(TwoStageTrendReviewConfig(export_root=str(tmp_path), sample_codes=["600000.SH"])).run()

    assert result["outputs"]["signals"].exists()
    assert result["outputs"]["sample_chart_600000.SH"].exists()
```

- [ ] **Step 2: Run runner tests and verify failure**

Run: `pytest tests/test_two_stage_trend_review.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'mns.pipelines.two_stage_trend_review'`.

- [ ] **Step 3: Implement universe loading and one-run orchestration**

```python
@dataclass(frozen=True)
class TwoStageTrendReviewConfig:
    db_path: str = "data/duckdb/mns.duckdb"
    khquant_cache_path: str = "data/cache/screening_cache.duckdb"
    start_date: str | None = None
    end_date: str | None = None
    initial_cash: float = 200_000.0
    max_positions: int = 10
    sample_codes: list[str] | None = None
    export_root: str = "data/reports/exports"
    strategy: TwoStageTrendStrategyConfig = field(default_factory=TwoStageTrendStrategyConfig)
    backtest: TwoStageTrendBacktestConfig = field(default_factory=TwoStageTrendBacktestConfig)


def _non_st_mns_codes(cache: KhQuantCacheStore, end_date: str) -> list[str]:
    universe = cache.load_universe(signal_date=end_date, universe="all_a", exclude_st=True)
    return [bs_to_mns_code(code) for code in universe["code"].astype(str).tolist()]
```

Load only those codes through `LocalMarketData.get_kline(timeframe="1d", ...)`, run the strategy and backtester, and persist exactly as existing runners do: `replace_backtest_run`, `replace_candidates_for_run`, `replace_signals_for_run`, `replace_trades_for_run`, and `replace_portfolio_snapshots_for_run`. Export `trades`, `portfolio`, `problems`, `candidates`, `signals`, and `skipped_orders` CSV files under `export_root`.

Implement `export_sample_chart` with matplotlib's non-interactive `Agg` backend: draw close/MA10/MA20/MA60, scatter red downward triangles for attention rows, green upward triangles for buy rows, and save one PNG per requested sample code. Export only requested `sample_codes`; do not generate thousands of charts during the full-A run.

- [ ] **Step 4: Implement the fixed time-split parameter validation**

```python
def split_dates(dates: list[pd.Timestamp], development_ratio: float = 0.70) -> tuple[pd.Timestamp, pd.Timestamp]:
    cut_index = max(1, min(len(dates) - 1, int(len(dates) * development_ratio)))
    return dates[cut_index - 1], dates[cut_index]


PRESETS = {
    "baseline": {"entry_volume_ratio": 1.2, "max_chase_pct": 0.12, "atr_multiple": 2.0},
    "strict": {"entry_volume_ratio": 1.5, "max_chase_pct": 0.08, "atr_multiple": 1.8},
    "relaxed": {"entry_volume_ratio": 1.0, "max_chase_pct": 0.15, "atr_multiple": 2.2},
}
```

Run all three presets on the development segment. Select the preset with the greatest `profit_factor`; break ties using lower absolute maximum drawdown and then greater `trade_count`. Re-run only that selected preset on the validation segment. Save `parameter_comparison.csv` containing the preset, segment, selected flag, and all summary metrics. Keep the one-run baseline result as the primary persisted run; validation is an exported analysis, not a hidden replacement of the configured live selector.

- [ ] **Step 5: Run runner tests**

Run: `pytest tests/test_two_stage_trend_review.py -q`

Expected: PASS.

Run: `python -m compileall mns/pipelines/two_stage_trend_review.py`

Expected: exit code 0.

### Task 4: Add the CLI entry point and end-to-end contract tests

**Files:**
- Modify: `mns/__main__.py`
- Create: `tests/test_two_stage_trend_cli.py`

**Interfaces:**
- Produces command: `mns run-two-stage-trend-backtest --start YYYY-MM-DD --end YYYY-MM-DD`.
- Consumes optional flags `--db`, `--khquant-cache`, `--initial-cash`, `--max-positions`, `--initial-stop-pct`, `--atr-multiple`, `--sample-codes`, `--export-root`, and the strategy threshold flags listed below.

- [ ] **Step 1: Write a failing parser and dispatch test**

```python
def test_two_stage_trend_cli_builds_confirmed_defaults(monkeypatch, capsys):
    captured = {}

    class StubRunner:
        def __init__(self, config):
            captured["config"] = config
        def run(self):
            return {"run_id": "two_stage_case", "signals": pd.DataFrame([{}]), "trades": pd.DataFrame([{}]), "summary": {"win_rate": 0.5}, "outputs": {}}

    monkeypatch.setattr(main_module, "TwoStageTrendReviewRunner", StubRunner)
    assert main_module.main(["run-two-stage-trend-backtest", "--start", "2025-01-01", "--end", "2026-01-01"]) == 0
    assert captured["config"].initial_cash == 200_000
    assert captured["config"].max_positions == 10
    assert "two_stage_case" in capsys.readouterr().out
```

- [ ] **Step 2: Run the CLI test and verify failure**

Run: `pytest tests/test_two_stage_trend_cli.py -q`

Expected: FAIL because `run-two-stage-trend-backtest` is not yet registered.

- [ ] **Step 3: Register parser and dispatch runner**

```python
two_stage = subparsers.add_parser(
    "run-two-stage-trend-backtest",
    help="Run the ST-excluded daily watch-then-buy trend strategy and next-open backtest.",
)
two_stage.add_argument("--db", default="data/duckdb/mns.duckdb")
two_stage.add_argument("--khquant-cache", default=DEFAULT_SCREENING_CACHE_PATH)
two_stage.add_argument("--start", required=True)
two_stage.add_argument("--end", required=True)
two_stage.add_argument("--initial-cash", type=float, default=200_000)
two_stage.add_argument("--max-positions", type=int, default=10)
two_stage.add_argument("--initial-stop-pct", type=float, default=0.10)
two_stage.add_argument("--atr-multiple", type=float, default=2.0)
two_stage.add_argument("--attention-window", type=int, default=60)
two_stage.add_argument("--entry-volume-ratio", type=float, default=1.2)
two_stage.add_argument("--max-chase-pct", type=float, default=0.12)
two_stage.add_argument("--sample-codes", default="")
two_stage.add_argument("--export-root", default="data/reports/exports")
```

Instantiate `TwoStageTrendReviewConfig` with nested strategy/backtest config overrides. Print run id, candidate count, signal count, trade count, summary dictionary, and every output path. Do not provide a flag that includes ST stocks.

- [ ] **Step 4: Run CLI and regression tests**

Run: `pytest tests/test_two_stage_trend_cli.py tests/test_two_stage_trend_strategy.py tests/test_two_stage_trend_backtest.py tests/test_two_stage_trend_review.py -q`

Expected: PASS.

Run: `pytest -q`

Expected: PASS with no failures.

- [ ] **Step 5: Run the requested two-year backtest and inspect artifacts**

Run: `mns run-two-stage-trend-backtest --start 2024-07-11 --end 2026-07-10 --sample-codes 603306.SH,603203.SH,603308.SH,603311.SH,603516.SH,603538.SH,603598.SH,603629.SH,603757.SH,603881.SH,603950.SH,605060.SH,605162.SH,605287.SH,605289.SH,605318.SH,603196.SH`

Expected: exit code 0; stdout prints the run id, signal/trade counts, win rate, profit/loss ratio, profit factor, maximum drawdown, and exported CSV/PNG paths. Confirm no `ST` or `*ST` name is present in the candidates, signals, or trades CSVs.

## Plan Self-Review

- **Spec coverage:** Task 1 covers the watch/buy rules, default windows, exact signal-date boundary, and ST filtering. Task 2 covers 200,000 CNY, ten slots, board lots, next-open fills, 10% stop, 1R breakeven, 2R ATR trailing, costs, skipped orders, and performance metrics. Task 3 covers DuckDB loading/persistence, sample overlays, exports, and the 70/30 preset validation. Task 4 covers user-adjustable CLI parameters and the real two-year backtest.
- **Placeholder scan:** This plan contains no unfinished implementation markers; all created symbols, test commands, selection rules, and default parameters are named above.
- **Type consistency:** `TwoStageTrendStrategy.generate_signals` produces the signal schema required by `TwoStageTrendBacktester.run`; the runner owns code conversion and persistence; the CLI constructs only `TwoStageTrendReviewConfig` and nested strategy/backtest config.
