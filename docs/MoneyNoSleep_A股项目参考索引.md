# Moneynosleep A 股项目参考索引

这份索引用于快速定位仓库中的核心说明文档、实施计划和阶段性结果。

## 推荐阅读顺序

1. [`README.md`](/D:/MoneyNoSleep/README.md)
2. [`docs/Moneynosleep_整体工作计划_V1.md`](/D:/MoneyNoSleep/docs/Moneynosleep_整体工作计划_V1.md)
3. [`docs/Moneynosleep_界面与菜单说明_20260520.md`](/D:/MoneyNoSleep/docs/Moneynosleep_界面与菜单说明_20260520.md)
4. [`docs/Moneynosleep_条件选股组合1说明_20260521.md`](/D:/MoneyNoSleep/docs/Moneynosleep_条件选股组合1说明_20260521.md)
5. [`docs/Moneynosleep_两年日线数据完整性审计_20260711.md`](/D:/MoneyNoSleep/docs/Moneynosleep_两年日线数据完整性审计_20260711.md)
6. [`docs/Moneynosleep_两阶段趋势选股回测留痕_20260711.md`](/D:/MoneyNoSleep/docs/Moneynosleep_两阶段趋势选股回测留痕_20260711.md)
7. [`docs/Moneynosleep_仓位金额敏感性实验_20260713.md`](/D:/MoneyNoSleep/docs/Moneynosleep_仓位金额敏感性实验_20260713.md)

## 说明文档

- [`docs/Moneynosleep_第一批骨架验收报告_20260519.md`](/D:/MoneyNoSleep/docs/Moneynosleep_第一批骨架验收报告_20260519.md)
- [`docs/Moneynosleep_日线闭环进展报告_20260519.md`](/D:/MoneyNoSleep/docs/Moneynosleep_日线闭环进展报告_20260519.md)
- [`docs/Moneynosleep_miniQMT接入进展_20260520.md`](/D:/MoneyNoSleep/docs/Moneynosleep_miniQMT接入进展_20260520.md)

## 设计与实现计划

- [`docs/superpowers/specs/2026-07-11-a-share-two-stage-trend-design.md`](/D:/MoneyNoSleep/docs/superpowers/specs/2026-07-11-a-share-two-stage-trend-design.md)
- [`docs/superpowers/plans/2026-07-11-a-share-two-stage-trend-implementation.md`](/D:/MoneyNoSleep/docs/superpowers/plans/2026-07-11-a-share-two-stage-trend-implementation.md)
- [`docs/superpowers/plans/2026-07-11-two-stage-data-cleaning-and-limit-up-plan.md`](/D:/MoneyNoSleep/docs/superpowers/plans/2026-07-11-two-stage-data-cleaning-and-limit-up-plan.md)
- [`docs/superpowers/plans/2026-07-13-ma20-exit-modes.md`](/D:/MoneyNoSleep/docs/superpowers/plans/2026-07-13-ma20-exit-modes.md)

## 结果和实验记录

- [`docs/Moneynosleep_100万固定2万资金占用回测_20260712.md`](/D:/MoneyNoSleep/docs/Moneynosleep_100万固定2万资金占用回测_20260712.md)
- [`docs/Moneynosleep_100万固定2万50仓回测_20260712.md`](/D:/MoneyNoSleep/docs/Moneynosleep_100万固定2万50仓回测_20260712.md)
- [`docs/Moneynosleep_两阶段趋势选股回测留痕_20260711.md`](/D:/MoneyNoSleep/docs/Moneynosleep_两阶段趋势选股回测留痕_20260711.md)
- [`docs/Moneynosleep_仓位金额敏感性实验_20260713.md`](/D:/MoneyNoSleep/docs/Moneynosleep_仓位金额敏感性实验_20260713.md)

## 代码入口

- [`mns/__main__.py`](/D:/MoneyNoSleep/mns/__main__.py)
- [`ui/app.py`](/D:/MoneyNoSleep/ui/app.py)
- [`ui/streamlit_app.py`](/D:/MoneyNoSleep/ui/streamlit_app.py)

## 约定

- `data/` 是本地运行数据目录，不纳入版本控制
- `docs/` 里保存设计、计划、复盘和实验记录
- `mns/` 是核心 Python 包
- `ui/` 是前端入口
