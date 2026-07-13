# Moneynosleep 条件选股组合1说明

日期：2026-05-21

## 1. 目标

本次新增的是 `条件选股` 第一版，先落地一套可直接执行的 `组合1`，参数与本地 `D:\khQuant` 项目的选股界面保持一致。

当前支持：

- 指定 `信号日期`
- 指定 `股票池`
- 勾选/关闭单项过滤条件
- 执行单日组合筛选
- 结果落库
- 结果导出 CSV
- 页面内查看历史筛选批次

## 2. 本次组合1包含的条件

- EMA 上穿过滤
- 带量过滤
- 日K角度过滤
- 相对低位过滤
- 业绩预期过滤
- 股价上限过滤
- 换手率过滤

## 3. 数据来源

本次组合1为了完整支持 `换手率` 和 `业绩预期`，默认读取：

- `D:\khQuant\oskhquant\stock_screener\cache\market_data.duckdb`

其中使用到的表：

- `daily_bars`
- `stock_master`
- `forecast_reports`
- `performance_express_reports`
- `growth_reports`
- `universe_members`

MoneyNoSleep 自己的 `data/duckdb/mns.duckdb` 负责保存：

- 筛选批次
- 筛选命中结果
- 页面历史回看

## 4. 页面入口

页面入口：

- [ui/pages/03_条件选股.py](D:/MoneyNoSleep/ui/pages/03_条件选股.py)

主工作台左侧导航已新增：

- `条件选股`

## 5. 命令行入口

命令：

```powershell
python -m mns run-condition-screening --signal-date 2026-05-19
```

常用参数：

- `--khquant-cache`
- `--universe`
- `--ema-period`
- `--volume-ma-window`
- `--volume-ratio-min`
- `--daily-k-angle-window`
- `--daily-k-angle-min`
- `--relative-low-window`
- `--relative-low-position-max`
- `--earnings-forecast-change-min`
- `--earnings-yoy-min`
- `--price-max`
- `--turnover-min`
- `--hold-days`

## 6. 结果保存位置

数据库：

- `data/duckdb/mns.duckdb`

导出：

- `data/reports/exports/*_screening_hits.csv`

## 7. 当前边界

这次先落地了 `组合1`。

还没做的部分：

- 多组组合条件编排器
- 条件模板保存/复制
- 组合之间 AND / OR 混合执行
- 条件选股结果直接联动下一步连续复盘

## 8. 下一步建议

建议下一步做：

1. 组合2、组合3 的参数化接入
2. 组合模板保存
3. 多组合并集 / 交集筛选
4. 选股结果一键送入连续复盘
