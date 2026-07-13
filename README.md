# Moneynosleep

Moneynosleep 是一个面向 A 股的选股、复盘、回测和人工交易复核工具集。

当前仓库的目标不是自动实盘交易，而是把以下流程串起来：

```text
本地数据同步
  -> 条件选股
  -> 快速复盘
  -> 资金曲线和交易明细
  -> K 线截图
  -> 人工复核
  -> 问题归因
```

## 主要能力

- `mns.data`: 数据源接入、标准化、校验，以及 DuckDB / Parquet 存储
- `mns.selector`: 条件选股与基础过滤
- `mns.strategies`: 策略实现
- `mns.backtest`: 回测与快速复盘
- `mns.review`: 连续复盘、截图导出、人工复核、问题归因
- `mns.portfolio`: 仓位、资金和风控相关模块
- `ui`: Streamlit 界面入口
- `tests`: 基础 smoke tests

## 环境要求

- Python 3.11+
- Windows 环境下建议使用 PowerShell
- 依赖见 [`pyproject.toml`](/D:/MoneyNoSleep/pyproject.toml)

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

## 常用命令

运行测试：

```powershell
pytest
```

初始化本地数据库：

```powershell
mns init-db --path data/duckdb/mns.duckdb
```

同步本地 CSV 日线并执行快速复盘：

```powershell
mns sync-csv-kline --stock-codes 600000.SH,000001.SZ --start 2026-01-01 --end 2026-04-30
mns run-daily-review --start 2026-01-01 --end 2026-04-30 --as-of 2026-03-25
```

同步 BaoStock 日线：

```powershell
mns sync-baostock-kline --stock-codes 600000.SH,000001.SZ --start 2026-01-01 --end 2026-04-30 --timeframe 1d
```

启动 Streamlit 界面：

```powershell
streamlit run ui/app.py
```

或者使用一键入口：

```powershell
mns start-ui
```

Windows 下也可以直接双击仓库根目录里的 `启动Moneynosleep.cmd`。

## 本地数据约定

`data/` 目录下主要是运行时生成的数据、缓存、日志和报表。
这些内容默认不纳入 Git 提交。

## 仓库结构

- `config/`: 配置文件
- `docs/`: 设计文档、计划和回顾记录
- `mns/`: 核心 Python 包
- `tests/`: 测试
- `tools/`: 辅助脚本
- `ui/`: Streamlit 前端

## 说明

- 当前仓库不包含真实自动实盘交易流程
- 策略和回测结果依赖本地数据源与配置
- 如果你要在另一台机器上继续开发，直接克隆这个仓库，再重新安装依赖即可
