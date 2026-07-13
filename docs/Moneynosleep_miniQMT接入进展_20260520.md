# Moneynosleep miniQMT 接入进展报告

日期：2026-05-20

## 1. 本轮完成内容

- 接入 `xtquant`，新增 miniQMT 数据提供器 `QMTProvider`
- 新增 CLI：
  - `mns test-qmt-connection`
  - `mns sync-qmt-kline`
- 支持周期：
  - `1d`
  - `1m`
  - `5m`
  - `15m`
  - `30m`
  - `60m`
  - `1h`
- 支持复权方式：
  - `front`
  - `back`
  - `none`
- 处理 xtquant 时间戳到北京时间的转换，避免日期偏移一天
- Streamlit 页面新增：
  - miniQMT 连接测试
  - miniQMT 行情同步
  - 行情展示周期切换
- 新增 5 分钟策略第一版：
  - `EMA21 / MA55 / ATR10` 因子
  - `ema21_ma55_pullback` 策略
  - `run-intraday-pullback-review` CLI
  - 页面内直接运行 5 分钟回踩复盘

## 2. 本地真实环境验证

### 2.1 连接测试

命令：

```powershell
python -m mns test-qmt-connection
```

结果：

- miniQMT 连接成功
- `app_dir`: `D:\兴业证券SMT-Q-2.0.8.0-test\bin.x64`
- `peer_addr`: `127.0.0.1:58610`
- `server_tag`: `{"tag": "sp3", "version": "1.0"}`

### 2.2 数据同步测试

日线：

```powershell
python -m mns sync-qmt-kline --stock-codes 600000.SH,000001.SZ --start 2026-03-01 --end 2026-03-31 --timeframe 1d
```

结果：

- 写入 `44` 行
- 生成 `22` 个 Parquet 分区
- `0` 个质量问题

5 分钟线：

```powershell
python -m mns sync-qmt-kline --stock-codes 600000.SH --start 2026-03-02 --end 2026-03-05 --timeframe 5m
```

结果：

- 写入 `144` 行
- 生成 `3` 个 Parquet 分区
- `0` 个质量问题

## 3. 当前数据库状态

`kline_bars` 当前按来源和周期统计：

```text
source    timeframe  rows
baostock  1d         234
qmt       1d          44
qmt       5m         144
```

## 4. 自动化验证

```text
pytest
21 passed

python -m py_compile ui/streamlit_app.py
通过
```

## 5. 当前可用能力

- 通过 CLI 测试 miniQMT 连接
- 通过 CLI 同步 miniQMT 日线和分钟线
- 页面内直接触发 miniQMT 同步
- 页面内切换 `1d/5m` 查看本地行情
- 通过 CLI 运行 5 分钟回踩复盘
- 页面内直接运行 5 分钟回踩复盘

## 6. 5分钟策略现状

已具备：

- 趋势过滤：`close > ma55` 且 `ema21 > ma55`
- 回踩识别：`low` 回踩 `ema21`
- 风险参数：`ATR10` 止损、`reward_multiple` 止盈
- 仓位控制：按 `risk_per_trade` 风险预算定量，同时受 `per_trade_cash` 上限约束
- 退出逻辑：优先止损/止盈，否则按 `max_hold_bars` 超时退出

真实 miniQMT 5 分钟数据冒烟命令：

```powershell
python -m mns run-intraday-pullback-review --stock-codes 600000.SH --start 2026-03-02 --end 2026-03-05 --as-of 2026-03-02
```

当前样本结果：

- 成功落库并导出
- 本次 `0` 条信号、`0` 笔交易
- 说明执行链已通，但当前参数和样本窗口下未触发 setup

## 7. 下一步建议

优先进入 `5分钟策略验证`：

1. 基于 miniQMT `5m` 数据落地 `EMA21 / MA55`
2. 扩充 setup 触发条件，加入量能和时间窗口过滤
3. 页面增加 `5m` 信号回放与买卖点解释
4. 将多股票、多交易日连续回放做成批量评估

## 8. 暂未触碰范围

- 真实自动下单
- 真实持仓读取
- 实盘风控联动
- QMT 交易指令下发

当前仍保持“只接行情，不接交易”边界。
