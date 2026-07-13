# MA20 出场模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为两阶段趋势策略增加两种 MA20 收盘破位出场模式，并与现有止损体系做同口径回测。

**Architecture:** 保持买入信号和既有止损逻辑不变；在持仓的收盘处理阶段判断 MA20，符合条件时登记下一交易日开盘卖出。配置使用 `ma20_exit_mode`，取值为 `off`、`always`、`profit_only`。

**Tech Stack:** Python、pandas、pytest、现有 DuckDB 回测管线。

## Global Constraints

- MA20 出场按收盘确认、下一交易日开盘成交。
- `profit_only` 仅在信号日收盘价高于实际买入价时触发。
- 保留 10% 初始止损、1R 保本、2R ATR 移动止盈；日内止损优先。
- 不修改选股与买入条件。

---

### Task 1: 回测器支持 MA20 出场

**Files:**
- Modify: `mns/backtest/two_stage_trend.py`
- Modify: `mns/pipelines/two_stage_trend_review.py`
- Test: `tests/test_two_stage_trend_backtest.py`

- [ ] 写入并执行两条失败测试：无条件 MA20 出场；仅盈利时 MA20 出场。
- [ ] 添加配置和收盘判断；把 `ma20` 传入回测数据。
- [ ] 执行定向测试，确认两条测试通过。

### Task 2: 命令行与留痕

**Files:**
- Modify: `mns/__main__.py`
- Modify: `tests/test_two_stage_trend_cli.py`

- [ ] 添加 `--ma20-exit-mode` 选项并写入回测配置。
- [ ] 执行 CLI 定向测试。

### Task 3: 对照回测

**Files:**
- Create: `docs/Moneynosleep_MA20出场模式对照回测_20260713.md`

- [ ] 分别执行 `off`、`always`、`profit_only`，保持 100 万、50 仓、每只 10 万与其余参数不变。
- [ ] 验证交易数、卖出原因、资金曲线、零价格和涨停买入拦截。
- [ ] 记录结果与结论。
