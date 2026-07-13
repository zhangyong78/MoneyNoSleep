# Moneynosleep 第一批骨架验收报告

> 验收日期：2026-05-19  
> 验收范围：第一期开工的项目骨架、核心抽象接口、存储初始化框架、快速复盘回测骨架、复盘验证骨架、UI 原型入口和基础测试。  
> 验收结论：通过，可进入下一步“日线数据同步 + 本地入库 + 条件选股闭环”。

---

## 1. 验收命令

```powershell
python -m pip install -e .[dev]
python -m mns --version
python -m mns init-db --path data/duckdb/mns.duckdb
pytest
```

验收结果：

```text
python -m mns --version
0.1.0

python -m mns init-db --path data/duckdb/mns.duckdb
Initialized DuckDB schema at data\duckdb\mns.duckdb

pytest
9 passed in 0.50s
```

DuckDB 已初始化表：

```text
backtest_runs
factor_values
portfolio_snapshots
securities
signals
trade_reviews
trade_screenshots
trades
```

---

## 2. 交付物检查

### 项目骨架

状态：通过。

已包含：

- `pyproject.toml`
- `README.md`
- `config/`
- `mns/`
- `ui/`
- `tests/`
- `data/`
- `docs/`

### 数据底座

状态：通过。

已包含：

- `DataProvider` 抽象接口。
- `CSVPublicProvider` 本地 CSV 数据源。
- `QMTProvider` 预留接口，未启用实盘。
- K线标准字段标准化。
- K线质量校验。
- DuckDB Store。
- Parquet Store。

### 因子选股

状态：通过。

已包含：

- Factor 基类。
- MA、EMA、ATR、N日新高、K线角度、量比等基础函数。
- 基础过滤器。
- 条件选股器。
- 自选股状态枚举。

### 快速复盘回测

状态：通过。

已包含：

- Strategy 基类。
- `next_open_hold_n` 策略。
- `QuickReviewBacktester`。
- 信号日之后下一根 K线开盘买入。
- 持有 N 根 K线后收盘卖出。
- 资金快照基础输出。

### 复盘验证

状态：通过。

已包含：

- ReplayEngine。
- ChartMarker。
- ScreenshotExporter。
- TradeReviewer。
- ProblemAnalyzer。
- ReportExporter。

### UI 原型

状态：通过。

已包含：

- `ui/streamlit_app.py`
- 连续复盘、交易列表、K线复核、人工验证、问题归因标签页。

### 实盘边界

状态：通过。

已确认：

- `QMTTradingAdapter.place_order()` 默认报错。
- `TickRiskEngine.start()` 默认报错。
- `ExecutionEngine.submit()` 默认报错。
- 第一阶段不存在真实下单路径。

---

## 3. 当前测试覆盖

已覆盖：

- 包导入与版本。
- 第一阶段 DuckDB 核心表定义。
- K线标准化与数据质量校验。
- 条件选股输出候选理由和评分。
- 快速复盘回测使用信号日后的下一根 K线买入。
- 人工复核记录生成。
- 问题标签统计。
- 实盘交易路径禁用。

---

## 4. 遗留缺口

以下不是本次骨架验收阻塞项，属于下一阶段工作：

1. 尚未接入真实公开行情源。
2. 尚未实现日线数据同步命令。
3. 尚未将 K线数据真实写入 DuckDB / Parquet 的业务流水线。
4. Streamlit 目前是原型静态演示，未连接数据库。
5. K线截图导出功能已有框架，尚未进入端到端回测结果联动。
6. 快速复盘回测尚未纳入手续费、滑点、涨跌停、停牌等完整 A股规则，这些按计划放在阶段 4。

---

## 5. 下一步建议

进入“日线数据同步 + 本地入库 + 条件选股闭环”：

1. 确认第一批公开数据源。
2. 实现日线同步 CLI。
3. 同步指定股票池和日期区间。
4. 标准化并校验 K线。
5. 写入 DuckDB / Parquet。
6. 从本地库读取日线数据运行条件选股。
7. 将候选股交给快速复盘回测。

