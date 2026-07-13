# Two-stage Data Cleaning and Limit-up Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean invalid daily bars in memory before signal calculation and reject buys that open at the applicable price-limit threshold.

**Architecture:** Keep `kline_bars` immutable. The review pipeline will clean each loaded batch, record discarded-row counts, then calculate indicators on only valid trading bars. The backtester will infer a prior close from its bar stream and reject a next-open buy when the opening price has already reached the applicable 10% or 20% limit threshold.

**Tech Stack:** Python, pandas, pytest, DuckDB-backed existing pipeline.

## Global Constraints

- Do not mutate `data/duckdb/mns.duckdb` during a backtest.
- Treat invalid or zero OHLC bars as non-tradable and exclude them from indicators.
- Treat a cross-sectional all-zero-volume/amount date as a non-trading placeholder.
- Use next-trading-day open only; an opening at the upper price limit is unbuyable.

---

### Task 1: Add and test in-memory daily-bar cleaning

**Files:**
- Modify: `mns/pipelines/two_stage_trend_review.py`
- Modify: `tests/test_two_stage_trend_review.py`

- [x] Write a failing test with a normal row, an invalid zero-OHLC row, and at least 50 same-date zero-volume/zero-amount rows; assert that the cleaner removes invalid bars and the cross-sectional placeholder date while retaining valid data.
- [x] Run `pytest -q tests/test_two_stage_trend_review.py -k clean` and verify it fails because the cleaner does not exist.
- [x] Implement a pure cleaner returning `(cleaned_frame, stats)` and call it before `strategy.enrich` in every pipeline batch; append stats to the process log.
- [x] Run the focused test and then all two-stage tests.

### Task 2: Reject next-day limit-up opens

**Files:**
- Modify: `mns/backtest/two_stage_trend.py`
- Modify: `tests/test_two_stage_trend_backtest.py`

- [x] Write a failing test where a main-board stock rises from 10 to a 11 opening on its entry day; assert no buy action and skipped reason `limit_up_unbuyable`.
- [x] Write a failing test where a ChiNext/STAR stock rises from 10 to a 12 opening; assert the same result under the 20% threshold.
- [x] Derive prior close by stock inside the backtester and implement a board-aware upper-limit test, while retaining direct `limit_up_price` support when present.
- [x] Run the focused tests and then all two-stage tests.

### Task 3: Re-run and audit the cleaned two-year backtest

**Files:**
- Modify: `docs/Moneynosleep_两年日线数据完整性审计_20260711.md`
- Create: `data/reports/two_stage_trend_cleaned_v1/*`

- [x] Run the optimized two-stage command with the existing two-year, 200,000 CNY, ten-position configuration.
- [x] Verify the generated process log reports discarded placeholder/invalid bars and the trade file contains no zero-price buys or sells.
- [x] Add the cleaned run ID and its metrics to the audit trace; state that direct limit-up orders are skipped rather than assumed filled.
