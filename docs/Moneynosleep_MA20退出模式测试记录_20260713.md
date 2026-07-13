# MoneyNoSleep MA20 退出模式测试记录

## 目的

验证两阶段趋势策略的三种 MA20 退出配置能够正确传入回测器、改变退出行为，并确保默认模式保持原有逻辑。本文同时作为迁移到其他机器后测试其他时间区间的测试文案。

## 固定条件

- 初始资金：1,000,000 元。
- 最大持仓：50 只。
- 单只目标金额：100,000 元。
- 排除 ST。
- 信号日收盘确认，下一交易日开盘买入。
- 次日开盘直接涨停时不买入。
- 初始止损 10%，1R 后保本，2R 后启用 2 倍 ATR 移动止盈。
- MA20 破位使用收盘确认，符合条件后在下一交易日开盘卖出。

## 参数说明

| 参数值 | 行为 |
|---|---|
| `off` | 关闭 MA20 退出，保持原有止损、保本和 ATR 移动止盈逻辑。 |
| `always` | 持仓收盘价跌破 MA20，下一交易日开盘卖出。 |
| `profit_only` | 仅当收盘价高于实际买入价且跌破 MA20 时，下一交易日开盘卖出。 |

## 自动化测试文案

### 用例一：默认行为

不传 `--ma20-exit-mode`，断言解析结果为 `off`，持仓不会产生 `ma20_exit` 或 `ma20_profit_exit`。

### 用例二：无条件 MA20 退出

使用 `ma20_exit_mode="always"`。构造持仓收盘价低于 MA20 的日线，断言当日只登记卖出，并在下一交易日开盘以 `ma20_exit` 原因成交。

### 用例三：仅盈利时 MA20 退出

使用 `ma20_exit_mode="profit_only"`。先构造亏损且跌破 MA20 的日线，断言不退出；随后构造盈利且跌破 MA20 的日线，断言下一交易日以 `ma20_profit_exit` 原因成交。

### 用例四：CLI 参数

传入 `--ma20-exit-mode profit_only`，断言命令行解析结果正确进入 `TwoStageTrendBacktestConfig`。

### 最小测试命令

```powershell
pytest -q tests/test_two_stage_trend_backtest.py -k ma20 tests/test_two_stage_trend_cli.py -k ma20
```

本次结果：`3 passed`。

## 现有结果一致性检查

本节只读取已经生成的 CSV 和日志，没有重新执行完整回测。

| 模式 | Run ID | 交易数 | 胜率 | 盈亏比 | Profit Factor | 期末权益 | 总收益率 | 最大回撤 | MA20 退出数 | 零价格成交 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `off` | `20260713_114114_942522fc` | 601 | 27.29% | 3.3828 | 1.2695 | 1,417,633.41 | +41.76% | -21.35% | 0 | 0 |
| `always` | `20260713_141007_6c02eaf9` | 939 | 26.94% | 2.9662 | 1.0940 | 1,198,905.74 | +19.89% | -26.73% | 608 | 0 |
| `profit_only` | `20260713_141605_369c242e` | 756 | 44.05% | 1.6315 | 1.2844 | 1,523,883.52 | +52.39% | -19.26% | 207 | 0 |

一致性结论：`off` 没有 MA20 退出；`always` 和 `profit_only` 分别产生对应退出原因，证明参数能够影响退出逻辑；三组均没有零价格成交。该结果只用于功能核对，不作为样本外性能结论。

## 在其他机器测试其他时间段

先迁移数据库和筛选缓存，并确认项目依赖安装完成。然后分别运行：

```powershell
$START_DATE = "2023-01-01"
$END_DATE = "2024-12-31"

python -m mns run-two-stage-trend-backtest --start $START_DATE --end $END_DATE --initial-cash 1000000 --max-positions 50 --per-position-cash 100000 --ma20-exit-mode off --export-root data/reports/ma20_off
python -m mns run-two-stage-trend-backtest --start $START_DATE --end $END_DATE --initial-cash 1000000 --max-positions 50 --per-position-cash 100000 --ma20-exit-mode always --export-root data/reports/ma20_always
python -m mns run-two-stage-trend-backtest --start $START_DATE --end $END_DATE --initial-cash 1000000 --max-positions 50 --per-position-cash 100000 --ma20-exit-mode profit_only --export-root data/reports/ma20_profit_only
```

更换时间段时只修改 `$START_DATE` 和 `$END_DATE`，其余条件保持不变，才能进行有效对照。

## 已知限制

- `profit_only` 按收盘价高于实际买入价判断浮盈，没有扣除卖出费用和下一交易日滑点。
- Qt 界面尚未验证 MA20 模式下拉框；当前可靠入口是 CLI。
- 历史结果属于样本内测试，迁移后应继续测试不同年份、牛熊阶段和震荡区间。
- `data/` 不纳入 Git；迁移机器时必须单独复制 DuckDB、筛选缓存和必要行情数据。
