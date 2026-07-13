from __future__ import annotations

import json
from html import escape
from pathlib import Path

import pandas as pd


FOCUS_PARAM = "F_slope_buffer_1_5atr"


def _pct(value: float) -> str:
    return f"{value:.2%}"


def _money_wan(value: float) -> str:
    return f"{value / 10000:.1f}万"


def _fmt_float(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def _table_html(
    frame: pd.DataFrame,
    columns: list[str],
    headers: list[str],
    formatters: dict[str, callable] | None = None,
) -> str:
    formatters = formatters or {}
    head = "".join(f"<th>{escape(str(label))}</th>" for label in headers)
    rows: list[str] = ['<table class="data-table"><thead><tr>', head, "</tr></thead><tbody>"]
    for _, row in frame.iterrows():
        cells = []
        for column in columns:
            value = row[column]
            if column in formatters:
                value = formatters[column](value)
            cells.append(f"<td>{escape(str(value))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    rows.append("</tbody></table>")
    return "".join(rows)


def _bar_chart(
    frame: pd.DataFrame,
    metric: str,
    *,
    title: str,
    color: str,
    inverse: bool = False,
    formatter=None,
) -> str:
    values = frame[metric].astype(float).tolist()
    max_abs = max(abs(value) for value in values) if values else 1.0
    parts = [f'<div class="chart-block"><h3>{escape(title)}</h3>']
    for _, row in frame.iterrows():
        label = str(row["name"])
        value = float(row[metric])
        width = abs(value) / max_abs * 100 if max_abs else 0.0
        shown = formatter(value) if formatter else _fmt_float(value)
        bar_color = "#b94735" if inverse or value < 0 else color
        parts.append(
            '<div class="bar-row">'
            f'<span class="bar-label">{escape(label)}</span>'
            f'<div class="bar-track"><span class="bar-fill" style="width:{width:.2f}%;background:{bar_color}"></span></div>'
            f'<span class="bar-value">{escape(shown)}</span>'
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _equity_svg(frame: pd.DataFrame, width: int = 780, height: int = 220) -> str:
    if frame.empty:
        return ""
    equity_values = frame["equity"].astype(float).tolist()
    drawdown_values = frame["drawdown"].astype(float).tolist()
    count = len(equity_values)
    ymin = min(equity_values)
    ymax = max(equity_values)
    if ymax == ymin:
        ymax = ymin + 1.0
    drawdown_min = min(drawdown_values) if drawdown_values else -1.0
    drawdown_range = 0 - drawdown_min if drawdown_min != 0 else 1.0
    equity_points: list[str] = []
    drawdown_points: list[str] = []
    for index, value in enumerate(equity_values):
        x = index / max(count - 1, 1) * (width - 40) + 20
        y = height - 25 - ((value - ymin) / (ymax - ymin) * (height - 55))
        equity_points.append(f"{x:.1f},{y:.1f}")
    for index, value in enumerate(drawdown_values):
        x = index / max(count - 1, 1) * (width - 40) + 20
        y = height - 25 - ((value - drawdown_min) / drawdown_range * (height - 55))
        drawdown_points.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg class="equity-svg" viewBox="0 0 {width} {height}" role="img" aria-label="权益曲线">'
        f'<line x1="20" y1="{height - 25}" x2="{width - 20}" y2="{height - 25}" stroke="#d7d1c7" />'
        f'<polyline points="{" ".join(drawdown_points)}" fill="none" stroke="#b94735" stroke-width="2" opacity="0.45" />'
        f'<polyline points="{" ".join(equity_points)}" fill="none" stroke="#1f7a6f" stroke-width="3" />'
        "</svg>"
    )


def _exit_mix_cards(summary_row: pd.Series) -> str:
    total = int(summary_row["trade_count"])
    items = [
        ("ATR止损", int(summary_row["atr_stop_count"]), "#b94735"),
        ("均线死叉", int(summary_row["ema_dead_cross_count"]), "#386fa4"),
        ("测试结束", int(summary_row["end_of_test_count"]), "#8a6f3d"),
    ]
    parts = ['<div class="mini-grid">']
    for label, count, color in items:
        ratio = count / total if total else 0.0
        parts.append(
            '<div class="mini-card">'
            f"<span>{label}</span>"
            f'<strong style="color:{color}">{count}</strong>'
            f"<small>{_pct(ratio)}</small>"
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _monthly_pnl(trades: pd.DataFrame) -> pd.DataFrame:
    frame = trades.copy()
    frame["month"] = frame["exit_date"].dt.to_period("M").astype(str)
    return (
        frame.groupby("month", as_index=False)
        .agg(pnl=("pnl", "sum"), trades=("trade_id", "count"))
        .sort_values("month")
    )


def _style_block() -> str:
    return """
:root {
  --ink: #20231f;
  --muted: #676b61;
  --paper: #f7f4ed;
  --panel: #fffdf8;
  --line: #d8d1c4;
  --green: #1f7a6f;
  --blue: #386fa4;
  --red: #b94735;
  --amber: #b8872d;
  --shadow: 0 18px 45px rgba(57, 49, 36, .12);
}
* { box-sizing: border-box; }
body { margin: 0; font-family: "Microsoft YaHei", "Noto Sans SC", sans-serif; color: var(--ink); background: linear-gradient(135deg, #f7f4ed 0%, #edf2ee 46%, #f5efe7 100%); }
.hero { padding: 42px 48px 26px; border-bottom: 1px solid var(--line); background: radial-gradient(circle at 12% 10%, rgba(31,122,111,.15), transparent 28%), radial-gradient(circle at 92% 0%, rgba(184,135,45,.13), transparent 30%); }
.hero h1 { margin: 0 0 14px; font-size: 32px; letter-spacing: 0; }
.hero p { margin: 6px 0; max-width: 980px; color: var(--muted); line-height: 1.75; }
.badges { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
.badge { border: 1px solid var(--line); background: rgba(255,255,255,.72); padding: 8px 12px; border-radius: 8px; font-size: 13px; }
main { padding: 28px 48px 56px; max-width: 1320px; margin: 0 auto; }
section { margin: 0 0 28px; }
.section-head { display: flex; justify-content: space-between; align-items: end; gap: 16px; margin-bottom: 14px; }
h2 { margin: 0; font-size: 22px; }
h3 { margin: 0 0 12px; font-size: 16px; }
.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; box-shadow: var(--shadow); }
.metric span { display: block; color: var(--muted); font-size: 13px; margin-bottom: 8px; }
.metric strong { display: block; font-size: 24px; }
.metric small { display: block; color: var(--muted); margin-top: 6px; line-height: 1.4; }
.two-col { display: grid; grid-template-columns: 1.1fr .9fr; gap: 16px; }
.three-col { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.data-table { width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; font-size: 13px; }
.data-table th, .data-table td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
.data-table th { background: #eee7d9; color: #37352f; font-weight: 700; }
.data-table tr:last-child td { border-bottom: 0; }
.table-wrap { overflow-x: auto; border-radius: 8px; }
.chart-block { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; box-shadow: var(--shadow); }
.bar-row { display: grid; grid-template-columns: 170px 1fr 82px; align-items: center; gap: 10px; margin: 10px 0; }
.bar-label { color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { height: 12px; background: #ebe5da; border-radius: 999px; overflow: hidden; }
.bar-fill { display: block; height: 100%; border-radius: 999px; }
.bar-value { text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }
.equity-svg { width: 100%; height: auto; background: #fffdf8; border: 1px solid var(--line); border-radius: 8px; }
.mini-grid { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 10px; }
.mini-card { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: rgba(255,255,255,.64); }
.mini-card span, .mini-card small { display: block; color: var(--muted); }
.mini-card strong { display: block; font-size: 22px; margin: 6px 0 2px; }
ul.clean { margin: 0; padding-left: 20px; line-height: 1.85; }
.guide-step { display: grid; grid-template-columns: 42px 1fr; gap: 12px; margin: 12px 0; }
.guide-step b { width: 34px; height: 34px; display: grid; place-items: center; background: var(--green); color: white; border-radius: 8px; }
.guide-step p { margin: 4px 0 0; color: var(--muted); line-height: 1.65; }
.footer { color: var(--muted); font-size: 12px; padding-top: 14px; border-top: 1px solid var(--line); }
@media (max-width: 980px) { main, .hero { padding-left: 18px; padding-right: 18px; } .grid, .two-col, .three-col { grid-template-columns: 1fr; } .bar-row { grid-template-columns: 1fr; } .bar-value { text-align: left; } }
""".strip()


def build_semiconductor_report_html(run_root: str | Path) -> dict[str, str]:
    root = Path(run_root)
    params = pd.read_csv(root / "parameter_grid_summary.csv")
    run_config = json.loads((root / "run_config.json").read_text(encoding="utf-8"))

    bundles: dict[str, dict[str, pd.DataFrame | dict[str, float]]] = {}
    for name in params["name"].tolist():
        param_root = root / name
        bundles[name] = {
            "trades": pd.read_csv(param_root / "trades.csv", parse_dates=["entry_date", "exit_date"]),
            "equity": pd.read_csv(param_root / "equity_curve.csv", parse_dates=["date"]),
            "stock": pd.read_csv(param_root / "stock_summary.csv"),
            "summary": json.loads((param_root / "summary.json").read_text(encoding="utf-8")),
        }

    params["calmar"] = params["annual_return"] / params["max_drawdown"].abs()
    params["best_trade_contribution"] = params["best_trade"] / params["total_pnl"]

    best_name = str(params.iloc[0]["name"])
    best_row = params.loc[params["name"] == best_name].iloc[0]
    focus_row = params.loc[params["name"] == FOCUS_PARAM].iloc[0]
    best_bundle = bundles[best_name]
    focus_bundle = bundles[FOCUS_PARAM]

    focus_top = focus_bundle["stock"].head(12)
    focus_bottom = focus_bundle["stock"].sort_values("total_pnl").head(10)
    best_top = best_bundle["stock"].head(10)
    focus_monthly = _monthly_pnl(focus_bundle["trades"]).tail(14)

    css = _style_block()
    param_table = _table_html(
        params,
        ["name", "total_return", "annual_return", "max_drawdown", "trade_count", "win_rate", "profit_loss_ratio", "max_consecutive_losses", "calmar", "best_trade_contribution"],
        ["参数", "总收益", "年化", "最大回撤", "交易数", "胜率", "盈亏均值比", "最大连亏", "Calmar", "最大单笔贡献占比"],
        {
            "total_return": _pct,
            "annual_return": _pct,
            "max_drawdown": _pct,
            "win_rate": _pct,
            "profit_loss_ratio": lambda value: _fmt_float(value, 2),
            "calmar": lambda value: _fmt_float(value, 2),
            "best_trade_contribution": _pct,
        },
    )
    stock_formatter = {"win_rate": _pct, "total_pnl": _money_wan, "best_trade": _money_wan, "worst_trade": _money_wan}
    focus_top_table = _table_html(focus_top, ["code", "stock_name", "trade_count", "win_rate", "total_pnl", "best_trade", "worst_trade"], ["代码", "名称", "交易数", "胜率", "总贡献", "最佳单笔", "最差单笔"], stock_formatter)
    focus_bottom_table = _table_html(focus_bottom, ["code", "stock_name", "trade_count", "win_rate", "total_pnl", "best_trade", "worst_trade"], ["代码", "名称", "交易数", "胜率", "总贡献", "最佳单笔", "最差单笔"], stock_formatter)
    best_top_table = _table_html(best_top, ["code", "stock_name", "trade_count", "win_rate", "total_pnl", "best_trade", "worst_trade"], ["代码", "名称", "交易数", "胜率", "总贡献", "最佳单笔", "最差单笔"], stock_formatter)
    monthly_table = _table_html(focus_monthly, ["month", "pnl", "trades"], ["月份", "已平仓盈亏", "交易数"], {"pnl": _money_wan})

    dashboard_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>半导体 EMA 回踩 ATR 回测分析看板</title>
<style>{css}</style>
</head>
<body>
<header class="hero">
  <h1>半导体 EMA 回踩 ATR 回测分析看板</h1>
  <p>Run ID：{escape(str(run_config.get("run_id", "")))}。成分股来源：本地板块库 qmt / industry / 半导体，共 {int(run_config.get("board_constituent_count", 0))} 只。区间：2024-01-02 至 2026-05-22，初始资金 100 万。</p>
  <p>核心结论：系统具备趋势捕捉能力，但收益依赖少数大赢家，全部参数组的最大回撤仍然偏高。更适合继续做组合化研究、板块过滤和小资金灰度，而不是直接独立重仓上线。</p>
  <div class="badges">
    <span class="badge">最佳收益：{escape(best_name)} / {_pct(float(best_row["total_return"]))}</span>
    <span class="badge">重点参数：{escape(FOCUS_PARAM)} / {_pct(float(focus_row["total_return"]))}</span>
    <span class="badge">最佳年化：{_pct(float(best_row["annual_return"]))}</span>
    <span class="badge">最低最大回撤：{_pct(float(params["max_drawdown"].max()))}</span>
  </div>
</header>
<main>
  <section class="grid">
    <div class="card metric"><span>最高收益参数</span><strong>{_pct(float(best_row["total_return"]))}</strong><small>{escape(best_name)}，最终权益 {_money_wan(float(best_row["final_equity"]))}</small></div>
    <div class="card metric"><span>重点参数收益</span><strong>{_pct(float(focus_row["total_return"]))}</strong><small>{escape(FOCUS_PARAM)}，最终权益 {_money_wan(float(focus_row["final_equity"]))}</small></div>
    <div class="card metric"><span>最小最大回撤</span><strong>{_pct(float(params["max_drawdown"].max()))}</strong><small>仍超过 50%，需要组合层风控</small></div>
    <div class="card metric"><span>重点参数最大连亏</span><strong>{int(focus_row["max_consecutive_losses"])} 笔</strong><small>执行压力小于 A 组，但收益也有所让渡</small></div>
  </section>
  <section class="two-col">
    {_bar_chart(params, "total_return", title="参数总收益对比", color="#1f7a6f", formatter=_pct)}
    {_bar_chart(params, "max_drawdown", title="最大回撤对比", color="#b94735", inverse=True, formatter=_pct)}
  </section>
  <section>
    <div class="section-head"><h2>参数组横向比较</h2><span class="badge">把收益、回撤、胜率和执行压力放在一起看</span></div>
    <div class="table-wrap">{param_table}</div>
  </section>
  <section class="two-col">
    <div class="card">
      <h2>给领导的结论</h2>
      <ul class="clean">
        <li>6 组参数全部正收益，说明核心逻辑具备研究价值，不是单一参数的偶然结果。</li>
        <li>最佳参数 {escape(best_name)} 的总收益 {_pct(float(best_row["total_return"]))}，但最大回撤 {_pct(float(best_row["max_drawdown"]))}，最大连亏 {int(best_row["max_consecutive_losses"])} 笔，直接实盘重仓并不合适。</li>
        <li>重点参数 {escape(FOCUS_PARAM)} 胜率更高，为 {_pct(float(focus_row["win_rate"]))}，最大连亏降到 {int(focus_row["max_consecutive_losses"])} 笔，更接近交易员可执行版本。</li>
        <li>实盘化前需要补齐交易成本、涨跌停成交、停牌、流动性和历史成分股口径，否则收益和回撤都偏乐观。</li>
      </ul>
    </div>
    <div class="card">
      <h2>收益结构判断</h2>
      <ul class="clean">
        <li>这是低胜率、高赔率策略，核心不是提高每笔胜率，而是保证大趋势单拿得住。</li>
        <li>A 组收益更高，但单笔大赢家对总收益贡献更集中，稳定性更依赖少数龙头行情。</li>
        <li>F 组收益更平滑一些，但仍然不能摆脱高回撤特征，必须通过资金管理来消化。</li>
        <li>更适合作为板块趋势信号模块，配合其他策略和仓位上限形成组合。</li>
      </ul>
    </div>
  </section>
  <section class="two-col">
    <div>
      <div class="section-head"><h2>{escape(best_name)} 权益曲线</h2><span class="badge">收益最高，但连亏压力更大</span></div>
      {_equity_svg(best_bundle["equity"])}
    </div>
    <div>
      <div class="section-head"><h2>{escape(FOCUS_PARAM)} 权益曲线</h2><span class="badge">更偏交易员执行版本</span></div>
      {_equity_svg(focus_bundle["equity"])}
    </div>
  </section>
  <section class="three-col">
    <div class="card"><h2>A 组出场结构</h2>{_exit_mix_cards(best_row)}</div>
    <div class="card"><h2>F 组出场结构</h2>{_exit_mix_cards(focus_row)}</div>
    <div class="card"><h2>怎么看</h2><p style="line-height:1.75;color:var(--muted)">ATR 止损占比高，说明入场后短期噪音不少；均线死叉退出占比高，说明更多单子进入了趋势跟随阶段。F 组胜率更高，但收益弹性明显弱于 A 组。</p></div>
  </section>
  <section>
    <div class="section-head"><h2>重点参数 F：主要赚钱股票</h2><span class="badge">看利润集中在哪里</span></div>
    <div class="table-wrap">{focus_top_table}</div>
  </section>
  <section>
    <div class="section-head"><h2>重点参数 F：主要拖累股票</h2><span class="badge">看哪些股票更容易形成假信号</span></div>
    <div class="table-wrap">{focus_bottom_table}</div>
  </section>
  <section class="two-col">
    <div>
      <div class="section-head"><h2>A 组主要赚钱股票</h2><span class="badge">收益最高参数的贡献集中度</span></div>
      <div class="table-wrap">{best_top_table}</div>
    </div>
    <div>
      <div class="section-head"><h2>F 组近 14 个月已平仓盈亏</h2><span class="badge">看交易节奏变化</span></div>
      <div class="table-wrap">{monthly_table}</div>
    </div>
  </section>
  <section class="card">
    <h2>交易员分析指南</h2>
    <div class="guide-step"><b>1</b><div><strong>先看板块强度。</strong><p>只在半导体板块强度靠前、成交额有支撑、指数没有明显破位时执行。弱板块里的 EMA 回踩先降级为观察信号。</p></div></div>
    <div class="guide-step"><b>2</b><div><strong>再看个股回踩质量。</strong><p>优先选择 EMA21 在 EMA55 上方、最低价触及 EMA55 附近、收盘重新站稳的个股。跳空过大、长上影密集、流动性偏差的信号要谨慎。</p></div></div>
    <div class="guide-step"><b>3</b><div><strong>按 ATR 止损定仓。</strong><p>止损是交易前确定的风险边界，仓位跟着风险走，不跟着主观判断走。不要因为看好就放大仓位。</p></div></div>
    <div class="guide-step"><b>4</b><div><strong>接受低胜率。</strong><p>这类系统靠少数大赢家覆盖很多小亏。复盘重点是有没有漏掉大赢家、有没有过早卖出，而不是单笔输赢本身。</p></div></div>
    <div class="guide-step"><b>5</b><div><strong>记录被拒绝和失败信号。</strong><p>每天结合 signal_log 回看板块强度、成交额、回踩深度、入场后是否快速触发 ATR 止损，逐步建立过滤条件。</p></div></div>
  </section>
  <section class="footer">生成时间：2026-05-25。数据目录：{escape(str(root))}。本页用于回测复盘与研究展示，不构成实盘投资建议。</section>
</main>
</body>
</html>
"""

    leadership_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>领导版报告 - 半导体 EMA 回踩策略</title>
<style>{css}</style>
</head>
<body>
<header class="hero">
  <h1>领导版报告：半导体 EMA 回踩 ATR 策略</h1>
  <p>这份报告只回答三个问题：策略有没有研究价值，风险有多大，下一步该怎么推进。</p>
</header>
<main>
  <section class="grid">
    <div class="card metric"><span>最佳参数收益</span><strong>{_pct(float(best_row["total_return"]))}</strong><small>{escape(best_name)}</small></div>
    <div class="card metric"><span>最佳参数最大回撤</span><strong>{_pct(float(best_row["max_drawdown"]))}</strong><small>不能直接大资金单策略上线</small></div>
    <div class="card metric"><span>重点参数收益</span><strong>{_pct(float(focus_row["total_return"]))}</strong><small>{escape(FOCUS_PARAM)}</small></div>
    <div class="card metric"><span>重点参数胜率</span><strong>{_pct(float(focus_row["win_rate"]))}</strong><small>更像交易员可执行版本</small></div>
  </section>
  <section class="card">
    <h2>结论</h2>
    <ul class="clean">
      <li>策略具备继续研究价值，6 组参数全部为正收益，说明底层逻辑有效。</li>
      <li>收益最高的 A 组回撤和连亏也最高，对资金管理和执行纪律要求很高。</li>
      <li>F 组更适合作为下一阶段观察版本，胜率更高、连亏更低，但收益弹性下降。</li>
      <li>当前更适合作为半导体板块趋势信号模块，而不是独立重仓系统。</li>
    </ul>
  </section>
  <section class="card">
    <h2>管理建议</h2>
    <ul class="clean">
      <li>允许进入模拟盘和小资金灰度，初始可按策略资金 10%-25% 上限控制。</li>
      <li>上线前必须补交易成本、涨跌停成交、停牌和流动性约束。</li>
      <li>继续接入历史成分股口径与板块强度过滤，压缩回撤和假信号。</li>
      <li>后续重点盯住最大回撤、最大连亏、单票利润集中度和漏掉的大赢家。</li>
    </ul>
  </section>
  <section>
    <h2>参数比较</h2>
    <div class="table-wrap">{param_table}</div>
  </section>
  <section class="footer">关联完整看板：analysis_dashboard.html。本页为管理层摘要版。</section>
</main>
</body>
</html>
"""

    trader_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>交易员分析指南 - 半导体 EMA 回踩策略</title>
<style>{css}</style>
</head>
<body>
<header class="hero">
  <h1>交易员分析指南：半导体 EMA 回踩 ATR 策略</h1>
  <p>把回测结果翻译成日常执行、复盘和纠偏动作，帮助我们用一致的方法做同一套系统。</p>
</header>
<main>
  <section class="card">
    <h2>执行定位</h2>
    <p style="line-height:1.75;color:var(--muted)">这是一套趋势回踩系统。交易员的任务不是追求天天高胜率，而是在可控亏损前提下，让真正走出来的趋势单尽量活得更久。</p>
  </section>
  <section class="card">
    <h2>每日流程</h2>
    <div class="guide-step"><b>1</b><div><strong>板块过滤。</strong><p>优先执行半导体板块强度靠前、成交额保持活跃、指数未明显走弱时出现的信号。</p></div></div>
    <div class="guide-step"><b>2</b><div><strong>信号确认。</strong><p>EMA21 在 EMA55 上方，最低价回踩 EMA55 附近，收盘仍然站稳。若启用 F 组，还要确认 EMA55 斜率向上。</p></div></div>
    <div class="guide-step"><b>3</b><div><strong>次日开盘执行。</strong><p>信号日在收盘后确认，次日开盘执行。若开盘跳空导致风险收益比显著恶化，要明确记录跳过原因。</p></div></div>
    <div class="guide-step"><b>4</b><div><strong>固定 ATR 止损。</strong><p>止损价格在入场前就确定，不因盘中主观情绪而下移。先接受小亏，才能保住系统的一致性。</p></div></div>
    <div class="guide-step"><b>5</b><div><strong>死叉退出。</strong><p>未触发止损时，等待 EMA21 下穿 EMA55 后次日开盘退出，不轻易提前截断趋势单。</p></div></div>
  </section>
  <section class="two-col">
    <div>
      <h2>重点参数 F：主要赚钱股票</h2>
      <div class="table-wrap">{focus_top_table}</div>
    </div>
    <div>
      <h2>重点参数 F：主要拖累股票</h2>
      <div class="table-wrap">{focus_bottom_table}</div>
    </div>
  </section>
  <section class="card">
    <h2>复盘清单</h2>
    <ul class="clean">
      <li>亏损单是否主要出现在板块弱势阶段，如果是，优先强化板块强度过滤。</li>
      <li>大赢家是否主要集中在龙头和高辨识度个股，如果是，可研究龙头优先级排序。</li>
      <li>ATR 止损是否过紧导致回踩后被洗出，可对比 A、B、F 三组的止损差异。</li>
      <li>死叉退出是否存在明显利润回吐，必要时再研究分批止盈，但不能伤害趋势持有能力。</li>
    </ul>
  </section>
  <section class="footer">关联完整看板：analysis_dashboard.html。交易员优先复盘 F 组的 signal_log、trades 与 stock_summary。</section>
</main>
</body>
</html>
"""

    outputs = {
        "dashboard": root / "analysis_dashboard.html",
        "leadership_report": root / "leadership_report.html",
        "trader_analysis_guide": root / "trader_analysis_guide.html",
    }
    outputs["dashboard"].write_text(dashboard_html, encoding="utf-8")
    outputs["leadership_report"].write_text(leadership_html, encoding="utf-8")
    outputs["trader_analysis_guide"].write_text(trader_html, encoding="utf-8")

    summary = {
        "run_root": str(root),
        "dashboard": str(outputs["dashboard"]),
        "leadership_report": str(outputs["leadership_report"]),
        "trader_analysis_guide": str(outputs["trader_analysis_guide"]),
        "best_parameter": best_name,
        "best_total_return": float(best_row["total_return"]),
        "focus_parameter": FOCUS_PARAM,
        "focus_total_return": float(focus_row["total_return"]),
    }
    (root / "analysis_outputs.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {key: str(value) for key, value in outputs.items()}


if __name__ == "__main__":
    report_root = Path("data/reports/semiconductor_ema/20260525_110928_708d0e93")
    result = build_semiconductor_report_html(report_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
