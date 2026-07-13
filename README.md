# Moneynosleep

Moneynosleep 是面向 A股市场的复盘选股、策略验证、连续复盘和人工买卖点复核系统。

当前阶段只建设第一期闭环：

```text
日线数据入库
  -> 条件选股
  -> 快速复盘回测
  -> 资金曲线和交易明细
  -> K线截图
  -> 人工复核
  -> 问题归因
```

## 第一阶段边界

- 不做真实自动交易。
- 不做真实自动下单。
- 不启用 QMT 实盘执行。
- 策略不得直接访问外部数据源，必须读取本地 DuckDB / Parquet。
- 回测必须区分信号时间和成交时间，避免未来函数。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
pytest
mns --version
```

初始化数据库：

```powershell
mns init-db --path data/duckdb/mns.duckdb
```

同步本地 CSV 日线并运行快速复盘：

```powershell
mns sync-csv-kline --stock-codes 600000.SH,000001.SZ --start 2026-01-01 --end 2026-04-30
mns run-daily-review --start 2026-01-01 --end 2026-04-30 --as-of 2026-03-25
```

同步 BaoStock 公开日线：

```powershell
mns sync-baostock-kline --stock-codes 600000.SH,000001.SZ --start 2026-01-01 --end 2026-04-30 --timeframe 1d
```

启动 Streamlit 原型：

```powershell
streamlit run ui/app.py
```

一键启动页面：

```powershell
mns start-ui
```

Windows 下也可以直接双击根目录里的 `启动Moneynosleep.cmd`。

## 当前已搭建模块

- `mns.data`: 数据源接口、K线标准化、校验、DuckDB / Parquet 存储框架。
- `mns.factors`: 因子抽象基类和第一批技术因子。
- `mns.selector`: 基础过滤和条件选股框架。
- `mns.strategies`: 策略抽象和日线快速复盘策略。
- `mns.backtest`: 快速复盘回测器。
- `mns.review`: 连续复盘、K线标记、截图导出、人工复核、问题归因框架。
- `ui`: Streamlit 原型入口。
- `tests`: 第一批 smoke tests。

## 计划文档

整体工作计划见：

```text
docs/Moneynosleep_整体工作计划_V1.md
```
