# Moneynosleep 日线闭环进展报告

> 日期：2026-05-19  
> 范围：日线数据同步、本地入库、条件选股、快速复盘回测、结果导出。  
> 结论：基础闭环已打通，可进入真实公开数据源接入或 UI 数据联动。

---

## 1. 新增能力

### 日线同步

新增命令：

```powershell
mns sync-csv-kline --stock-codes 600000.SH,000001.SZ --start 2026-01-01 --end 2026-04-30
```

能力：

- 从本地 CSV provider 读取 K线。
- 标准化为统一 K线字段。
- 执行 K线质量校验。
- 写入 DuckDB `kline_bars`。
- 按 `timeframe/trade_date` 写入 Parquet 分区。

### 本地行情读取

新增：

- `mns.data.local_data.LocalMarketData`

能力：

- 从 DuckDB 本地库按周期、日期区间、股票池读取 K线。
- 后续策略和选股不直接访问外部数据源。

### 条件选股和快速复盘

新增命令：

```powershell
mns run-daily-review --start 2026-01-01 --end 2026-04-30 --as-of 2026-03-25
```

能力：

- 从本地库读取日线。
- 计算 EMA21、MA55、N日新高、K线角度、量比等基础因子。
- 默认执行 `close > ma55` 和 `volume_ratio_5 > 阈值` 条件筛选。
- 生成候选股。
- 生成策略信号。
- 执行 `next_open_hold_n` 快速复盘。
- 导出 candidates、signals、trades、portfolio、problems CSV。

---

## 2. 新增/修改模块

新增：

- `mns/data/local_data.py`
- `mns/data/sync.py`
- `mns/pipelines/__init__.py`
- `mns/pipelines/daily_review.py`
- `tests/test_daily_review_pipeline.py`
- `.gitignore`

修改：

- `mns/data/duckdb_store.py`
- `mns/__main__.py`
- `README.md`
- `tests/test_project_smoke.py`

---

## 3. 验证结果

测试：

```text
pytest
10 passed in 1.85s
```

CLI：

```text
python -m mns --help
usage: mns [-h] [--version] {init-db,sync-csv-kline,run-daily-review} ...
```

数据库初始化：

```text
python -m mns init-db --path data/duckdb/mns.duckdb
Initialized DuckDB schema at data\duckdb\mns.duckdb
```

当前 DuckDB 表：

```text
backtest_runs
factor_values
kline_bars
portfolio_snapshots
securities
signals
trade_reviews
trade_screenshots
trades
```

---

## 4. 当前边界

已完成：

- 日线 CSV 数据同步。
- DuckDB / Parquet 双写。
- 本地库读取。
- 基础因子计算。
- 条件选股。
- 快速复盘回测。
- CSV 结果导出。
- 端到端测试。

尚未完成：

- AKShare / Tushare 等第二公开源 Provider。
- Streamlit 页面连接 DuckDB 真实数据。
- 回测结果写回 `backtest_runs`、`trades`、`portfolio_snapshots` 表。
- 每笔交易自动生成 K线截图。
- 手续费、滑点、涨跌停、停牌、T+1 完整 A股撮合规则。

---

## 5. 下一步建议

### 2026-05-19 追加：BaoStock 公开源已接入

新增：

- `mns/data/providers/baostock_provider.py`
- `mns sync-baostock-kline`
- `tests/test_baostock_provider.py`

使用方式：

```powershell
mns sync-baostock-kline --stock-codes 600000.SH,000001.SZ --start 2026-01-01 --end 2026-04-30 --timeframe 1d
```

已验证：

```text
pytest
11 passed in 1.75s

BaoStock 冒烟同步：
Synced 4 rows from BaoStock, 4 parquet partitions, 0 quality issues.
```

说明：

- BaoStock 使用 `sh.600000` 格式，系统内部仍统一使用 `600000.SH`。
- 当前支持 `1d/5m/15m/30m/60m` 周期参数映射。
- 默认 `adjustflag=2`，即前复权；可通过 CLI 修改。

下一步建议二选一：

1. 继续接入第二公开源 AKShare，作为 BaoStock 的补充和交叉校验。
2. 先把当前日线闭环接入 Streamlit，让 UI 能选择 run、查看候选股、交易明细和资金曲线。

### 2026-05-19 追加：复盘 UI 与结果落库增强

新增：

- 回测批次写入 `backtest_runs`。
- 候选股写入 `screening_candidates`。
- 策略信号写入 `signals`。
- 买卖交易动作写入 `trades`。
- 资金曲线写入 `portfolio_snapshots`。
- 人工复核写入 `trade_reviews`。
- 交易截图索引写入 `trade_screenshots`。
- Streamlit 侧边栏支持 BaoStock 同步和快速复盘。
- Streamlit K线复核页支持买卖点标记图。
- Streamlit 支持单笔截图导出。
- CLI 支持批量截图导出：`mns export-screenshots --run-id <run_id>`。
- 快速复盘支持佣金、印花税、过户费、滑点参数。

验证：

```text
pytest
15 passed

真实 run 验证：
candidates=2
signals=2
trades=4
screenshots=2
```

当前下一步：

1. 如果继续增强研究能力，建议接 AKShare 作为第二公开源。
2. 如果继续增强复盘闭环，建议做人工复核后的问题归因报告和 HTML 导出。
3. 如果进入 QMT、Tushare token 或实盘相关能力，需要先确认本地账号、路径和权限边界。

### 2026-05-19 追加：AKShare 与 HTML 报告已接入

新增：

- AKShare 日线 Provider：`mns/data/providers/akshare_provider.py`。
- AKShare 同步命令：`mns sync-akshare-kline`。
- HTML 复盘报告导出：`mns export-html-report --run-id <run_id>`。
- 批量截图导出：`mns export-screenshots --run-id <run_id>`。

验证：

```text
pytest
17 passed

AKShare 冒烟同步：
Synced 4 rows from AKShare, 4 parquet partitions, 0 quality issues.

HTML 报告：
data/reports/html/20260519_203535_2dd0e983.html
```

当前授权边界：

1. Tushare 需要 token。
2. QMT / miniQMT 需要本地安装路径、账号环境和明确的只读/实盘权限边界。
3. 真实自动交易仍不进入第一阶段。
