from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from typing import Sequence

import pandas as pd
import streamlit as st

from mns.data.duckdb_store import DuckDBStore
from mns.data.khquant_cache import A_SHARE_PREFIXES as DEFAULT_A_SHARE_PREFIXES
from mns.data.local_data import LocalMarketData
from mns.data.timeframes import timeframe_aliases
from mns.review.chart_indicators import (
    ChartIndicatorSpec,
    add_price_overlay_indicators,
    available_price_overlay_indicators,
    indicator_display_names,
    load_default_price_overlay_indicators,
    required_indicator_history,
    resolve_price_overlay_indicators,
)
from mns.review.chart_style import DOWN_COLOR, LIMIT_UP_COLOR, UP_COLOR, build_kline_colors, build_limit_up_mask

screening = importlib.import_module("mns.pipelines.condition_screening")
ConditionGroupConfig = screening.ConditionGroupConfig
ConditionScreeningConfig = screening.ConditionScreeningConfig
ConditionScreeningRunner = screening.ConditionScreeningRunner
ConditionTimelineConfig = screening.ConditionTimelineConfig
ConditionTimelineRunner = screening.ConditionTimelineRunner
UNIVERSE_LABELS = screening.UNIVERSE_LABELS
A_SHARE_PREFIXES = getattr(screening, "A_SHARE_PREFIXES", DEFAULT_A_SHARE_PREFIXES)


st.set_page_config(page_title="条件选股", layout="wide")

st.markdown(
    """
    <style>
    div.block-container {padding-top: 0.85rem; padding-bottom: 1.1rem; max-width: 1500px;}
    div[data-testid="stHorizontalBlock"] > div {padding-right: 0.45rem;}
    h1 {font-size: 2.1rem; margin-bottom: 0.1rem;}
    h3 {font-size: 1.08rem; letter-spacing: 0;}
    div[data-testid="stMetric"] {
        background: #f8fbff;
        border: 1px solid #d8e4f2;
        border-radius: 8px;
        padding: 0.48rem 0.62rem;
    }
    div[data-testid="stMetricLabel"] p {font-size: 0.74rem; color: #667085;}
    div[data-testid="stMetricValue"] {font-size: 0.98rem;}
    div[data-testid="stExpander"] {
        border: 1px solid #dde5ef;
        border-radius: 8px;
        background: #fbfcfe;
    }
    div[data-testid="stTabs"] button {padding-top: 0.34rem; padding-bottom: 0.34rem;}
    label[data-testid="stWidgetLabel"] p {font-size: 0.78rem; margin-bottom: 0.12rem;}
    div[data-baseweb="input"] input {font-size: 0.88rem; padding-top: 0.28rem; padding-bottom: 0.28rem;}
    div[data-baseweb="select"] > div {min-height: 2rem;}
    div[data-testid="stDateInput"] input {font-size: 0.88rem;}
    div[data-testid="stNumberInput"] > div,
    div[data-testid="stDateInput"] > div {min-height: 2rem;}
    div[data-testid="stNumberInput"] button,
    div[data-testid="stDateInput"] button {min-height: 1.95rem;}
    div[data-testid="stCheckbox"] {padding-top: 0.05rem;}
    div[data-testid="stRadio"] label p,
    div[data-testid="stCheckbox"] label p {font-size: 0.82rem;}
    .mns-page-kicker {
        color: #4b5563;
        font-size: 0.88rem;
        margin: -0.15rem 0 0.85rem 0;
    }
    .mns-compact-note {
        font-size: 0.81rem;
        color: #64748b;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 0.38rem 0.7rem;
        margin: 0.05rem 0 0.5rem 0;
    }
    .mns-section-title {
        font-size: 0.92rem;
        font-weight: 700;
        color: #1f2937;
        margin: 0.1rem 0 0.05rem 0;
    }
    .mns-section-help {
        color: #667085;
        font-size: 0.78rem;
        margin: 0 0 0.5rem 0;
    }
    .mns-group-header {
        border-left: 3px solid #ef4444;
        padding: 0.15rem 0 0.2rem 0.65rem;
        margin-bottom: 0.4rem;
    }
    .mns-action-band {
        border-top: 1px solid #e5e7eb;
        padding-top: 0.75rem;
        margin-top: 0.35rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _expand_payload(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty or "payload_json" not in raw.columns:
        return raw
    payload = raw["payload_json"].apply(lambda value: json.loads(value) if isinstance(value, str) and value else {})
    expanded = pd.json_normalize(payload)
    if expanded.empty:
        return raw
    result = raw.drop(columns=["payload_json"]).copy()
    for column in expanded.columns:
        result[column] = expanded[column]
    return result


def _load_rule_runs(db_path: str) -> pd.DataFrame:
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return DuckDBStore(path).list_screening_rule_runs(limit=50)
    except Exception:
        return pd.DataFrame()


def _load_rule_hits(db_path: str, run_id: str) -> pd.DataFrame:
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return _expand_payload(DuckDBStore(path).get_screening_rule_hits(run_id))
    except Exception:
        return pd.DataFrame()


def _load_timeline_runs(db_path: str) -> pd.DataFrame:
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return DuckDBStore(path).list_screening_timeline_runs(limit=50)
    except Exception:
        return pd.DataFrame()


def _load_timeline_hits(db_path: str, run_id: str) -> pd.DataFrame:
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return _expand_payload(DuckDBStore(path).get_screening_timeline_hits(run_id))
    except Exception:
        return pd.DataFrame()


def _percent_series(series: pd.Series) -> pd.Series:
    return series.apply(lambda value: f"{float(value) * 100:.2f}%" if pd.notna(value) else "")


def _float_series(series: pd.Series) -> pd.Series:
    return series.apply(lambda value: f"{float(value):.2f}" if pd.notna(value) else "")


def _get_latest_trade_date(db_path: str, timeframe: str = "1d") -> str | None:
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        frame = DuckDBStore(path).query_frame(
            """
            SELECT MAX(trade_date) AS latest_trade_date
            FROM kline_bars
            WHERE timeframe IN (SELECT UNNEST(?))
            """,
            (list(timeframe_aliases(timeframe)),),
        )
    except Exception:
        return None
    if frame.empty or "latest_trade_date" not in frame.columns:
        return None
    value = frame.iloc[0]["latest_trade_date"]
    if value is None or pd.isna(value):
        return None
    return str(pd.Timestamp(value).date())


def _get_stock_count(db_path: str, trade_date: str | None, *, exclude_st: bool = True) -> int:
    if not trade_date:
        return 0
    path = Path(db_path)
    if not path.exists():
        return 0
    try:
        st_filter = "AND COALESCE(s.is_st, FALSE) = FALSE" if exclude_st else ""
        a_share_filter = " OR ".join([f"b.stock_code LIKE '{prefix[3:]}%'" for prefix in A_SHARE_PREFIXES])
        frame = DuckDBStore(path).query_frame(
            f"""
            SELECT COUNT(DISTINCT b.stock_code) AS stock_count
            FROM kline_bars AS b
            LEFT JOIN securities AS s ON s.stock_code = b.stock_code
            WHERE b.timeframe = '1d'
              AND b.trade_date = ?
              {st_filter}
              AND ({a_share_filter})
            """,
            (trade_date,),
        )
    except Exception:
        return 0
    if frame.empty:
        return 0
    value = frame.iloc[0]["stock_count"]
    return int(value) if pd.notna(value) else 0


def _load_stock_kline(
    db_path: str,
    stock_code: str,
    *,
    start_date: str,
    end_date: str,
    timeframe: str = "1d",
) -> pd.DataFrame:
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = LocalMarketData(DuckDBStore(path)).get_kline(
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            stock_codes=[stock_code],
        )
    except Exception:
        return pd.DataFrame()
    if frame.empty:
        return frame
    frame = frame.sort_values("bar_time").copy()
    frame["bar_time"] = pd.to_datetime(frame["bar_time"])
    return frame


def _format_pct(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100:.2f}%"


def _coerce_timestamp(value) -> pd.Timestamp | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def _format_hit_display_df(hit_df: pd.DataFrame) -> pd.DataFrame:
    display_df = hit_df.copy()
    for column in ("signal_change_pct", "breakout_pct", "relative_low_position", "hold_return_pct", "upper_shadow_pct", "lower_shadow_pct", "body_pct", "amplitude_pct", "return_next_5d", "max_return_next_5d"):
        if column in display_df.columns:
            display_df[column] = _percent_series(display_df[column])
    for column in ("close", "volume_ratio", "daily_k_angle", "turnover_rate", "amount_sum_next_5d", "recent_amount_max"):
        if column in display_df.columns:
            display_df[column] = _float_series(display_df[column])
    return display_df


def _available_columns(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column in frame.columns]


def _build_stock_summary(hit_df: pd.DataFrame) -> pd.DataFrame:
    aggregations: dict[str, tuple[str, str]] = {
        "stock_name": ("stock_name", "first"),
        "hit_count": ("trade_date", "count"),
        "first_hit": ("trade_date", "min"),
        "last_hit": ("trade_date", "max"),
    }
    if "group_name" in hit_df.columns:
        aggregations["group_count"] = ("group_name", "nunique")
    return (
        hit_df.groupby("stock_code")
        .agg(**aggregations)
        .reset_index()
        .sort_values(["hit_count", "stock_code"], ascending=[False, True])
    )


def _build_stock_option_labels(stock_summary: pd.DataFrame) -> dict[str, str]:
    labels: dict[str, str] = {}
    for _, row in stock_summary.iterrows():
        label_parts: list[str] = []
        if "group_count" in row and pd.notna(row["group_count"]):
            label_parts.append(f"{int(row['group_count'])}组")
        label_parts.append(f"{int(row['hit_count'])}次")
        labels[str(row["stock_code"])] = f"{row['stock_name']}  {row['stock_code']}  ({' / '.join(label_parts)})"
    return labels


def _render_hit_kline_browser(
    db_path: str,
    hit_df: pd.DataFrame,
    *,
    state_prefix: str,
    heading: str,
    show_stock_summary: bool,
) -> None:
    stock_summary = _build_stock_summary(hit_df)
    if stock_summary.empty:
        return

    if show_stock_summary:
        st.dataframe(stock_summary, use_container_width=True, hide_index=True)

    stock_options = stock_summary["stock_code"].astype(str).tolist()
    stock_labels = _build_stock_option_labels(stock_summary)
    stock_state_key = f"{state_prefix}_stock"
    if stock_options and st.session_state.get(stock_state_key) not in stock_options:
        st.session_state[stock_state_key] = stock_options[0]

    st.markdown(f"#### {heading}")
    browser_left, browser_right = st.columns([0.95, 2.05])

    with browser_left:
        selected_stock_code = st.radio(
            "点击股票名称查看K线",
            options=stock_options,
            format_func=lambda value: stock_labels[value],
            key=stock_state_key,
            label_visibility="collapsed",
        )

        stock_hits = hit_df[hit_df["stock_code"].astype(str) == str(selected_stock_code)].copy()
        sort_columns = ["trade_date"]
        ascending = [False]
        if "score" in stock_hits.columns:
            sort_columns.append("score")
            ascending.append(False)
        stock_hits = stock_hits.sort_values(sort_columns, ascending=ascending).reset_index(drop=True)
        date_options = stock_hits["trade_date"].astype(str).drop_duplicates().tolist()
        date_state_key = f"{state_prefix}_trade_date_{selected_stock_code}"
        if date_options and st.session_state.get(date_state_key) not in date_options:
            st.session_state[date_state_key] = date_options[0]

        if len(date_options) > 1:
            selected_trade_date = st.selectbox("命中日期", options=date_options, key=date_state_key)
        else:
            selected_trade_date = date_options[0]

        selected_date_hits = stock_hits[stock_hits["trade_date"].astype(str) == str(selected_trade_date)].copy()
        if "score" in selected_date_hits.columns:
            selected_date_hits = selected_date_hits.sort_values("score", ascending=False)
        selected_hit = selected_date_hits.iloc[0]

        group_names: list[str] = []
        if "group_name" in selected_date_hits.columns:
            group_names = sorted({str(value) for value in selected_date_hits["group_name"].tolist() if str(value).strip()})
        st.caption(f"命中组合：{'、'.join(group_names) if group_names else '-'}")
        st.caption(f"命中记录：{len(selected_date_hits)} 条")

    with browser_right:
        signal_ts = _coerce_timestamp(selected_hit["trade_date"])
        if signal_ts is None:
            st.warning("当前命中记录缺少有效的信号日期，无法加载K线数据。")
            return

        available_chart_indicators = available_price_overlay_indicators()
        default_chart_indicators = load_default_price_overlay_indicators()
        selected_indicator_names = st.multiselect(
            "显示指标",
            options=indicator_display_names(available_chart_indicators),
            default=indicator_display_names(default_chart_indicators),
            key=f"{state_prefix}_timeline_chart_indicators",
        )
        chart_indicators = resolve_price_overlay_indicators(selected_indicator_names)
        display_start_ts = signal_ts - pd.Timedelta(days=90)
        calc_history_days = max(90, required_indicator_history(chart_indicators))
        start_date = (signal_ts - pd.Timedelta(days=calc_history_days)).date().isoformat()
        end_ts = signal_ts + pd.Timedelta(days=25)
        sell_ts = _coerce_timestamp(selected_hit.get("sell_date"))
        if sell_ts is not None:
            end_ts = max(end_ts, sell_ts + pd.Timedelta(days=15))

        kline_df = _load_stock_kline(
            db_path,
            str(selected_hit["stock_code"]),
            start_date=start_date,
            end_date=end_ts.date().isoformat(),
        )
        if kline_df.empty:
            st.info("没有找到这只股票对应的本地日线数据，暂时无法显示K线图。")
            return

        info_cols = st.columns(4)
        info_cols[0].metric("信号日期", str(selected_hit["trade_date"]))
        info_cols[1].metric("收盘价", _float_series(pd.Series([selected_hit.get("close")])).iloc[0])
        info_cols[2].metric("量比", _float_series(pd.Series([selected_hit.get("volume_ratio")])).iloc[0])
        info_cols[3].metric("日K角度", _float_series(pd.Series([selected_hit.get("daily_k_angle")])).iloc[0])

        detail_lines: list[str] = []
        for _, row in selected_date_hits.iterrows():
            detail = str(row.get("group_name", "-"))
            reason = str(row.get("candidate_reason", "")).strip()
            earnings_signal = str(row.get("earnings_signal", "")).strip()
            if reason:
                detail = f"{detail}：{reason}"
            if earnings_signal:
                detail = f"{detail} | 业绩信号：{earnings_signal}"
            detail_lines.append(detail)
        with st.expander("命中原因与组合明细", expanded=False):
            st.markdown("\n".join(f"- {line}" for line in detail_lines if line))

        chart_key = f"{state_prefix}_chart_{selected_stock_code}_{selected_trade_date}"
        _plot_timeline_hit_chart(
            kline_df,
            selected_hit,
            chart_key=chart_key,
            display_start_ts=display_start_ts,
            indicators=chart_indicators,
        )


def _plot_timeline_hit_chart(
    selected: pd.DataFrame,
    hit_row: pd.Series,
    *,
    chart_key: str,
    display_start_ts: pd.Timestamp | None = None,
    indicators: Sequence[ChartIndicatorSpec] | None = None,
) -> None:
    import plotly.graph_objects as go

    indicators = tuple(indicators) if indicators is not None else load_default_price_overlay_indicators()
    selected = add_price_overlay_indicators(selected, indicators)
    if display_start_ts is not None:
        selected = selected[selected["bar_time"] >= display_start_ts].copy()
    else:
        selected = selected.copy()
    selected = selected.sort_values("bar_time")
    selected["is_limit_up"] = build_limit_up_mask(selected)
    x_values = selected["bar_time"].dt.strftime("%Y-%m-%d")
    volume_colors = build_kline_colors(selected)
    normal_bars = selected[~selected["is_limit_up"]]
    limit_up_bars = selected[selected["is_limit_up"]]

    signal_ts = _coerce_timestamp(hit_row["trade_date"])
    if signal_ts is None:
        st.warning("当前命中记录缺少有效的信号日期，无法绘制K线图。")
        return
    signal_date = signal_ts.strftime("%Y-%m-%d")
    price_low = float(selected["low"].min())
    price_high = float(selected["high"].max())

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=x_values,
            y=selected["volume"],
            name="成交量",
            marker={"color": volume_colors},
            yaxis="y2",
            opacity=0.78,
        )
    )
    fig.add_trace(
        go.Candlestick(
            x=normal_bars["bar_time"].dt.strftime("%Y-%m-%d"),
            open=normal_bars["open"],
            high=normal_bars["high"],
            low=normal_bars["low"],
            close=normal_bars["close"],
            name="日K",
            increasing_line_color=UP_COLOR,
            increasing_fillcolor=UP_COLOR,
            decreasing_line_color=DOWN_COLOR,
            decreasing_fillcolor=DOWN_COLOR,
        )
    )
    if not limit_up_bars.empty:
        fig.add_trace(
            go.Candlestick(
                x=limit_up_bars["bar_time"].dt.strftime("%Y-%m-%d"),
                open=limit_up_bars["open"],
                high=limit_up_bars["high"],
                low=limit_up_bars["low"],
                close=limit_up_bars["close"],
                name="涨停",
                increasing_line_color=LIMIT_UP_COLOR,
                increasing_fillcolor=LIMIT_UP_COLOR,
                decreasing_line_color=LIMIT_UP_COLOR,
                decreasing_fillcolor=LIMIT_UP_COLOR,
            )
        )
    for indicator in indicators:
        if indicator.column_name not in selected.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=selected[indicator.column_name],
                mode="lines",
                name=indicator.display_name,
                line={"color": indicator.color, "width": indicator.width},
            )
        )
    fig.add_trace(
        go.Scatter(
            x=[signal_date, signal_date],
            y=[price_low, price_high],
            mode="lines",
            name="信号日",
            line={"color": "#f59e0b", "width": 1.5, "dash": "dot"},
            opacity=0.9,
        )
    )

    signal_bar = selected[selected["bar_time"].dt.strftime("%Y-%m-%d") == signal_date]
    signal_price = float(signal_bar["high"].iloc[-1]) if not signal_bar.empty else float(hit_row.get("close", selected["close"].iloc[-1]))
    fig.add_trace(
        go.Scatter(
            x=[signal_date],
            y=[signal_price],
            mode="markers+text",
            name="信号",
            text=["信号"],
            textposition="top center",
            marker={"color": "#f59e0b", "size": 12, "symbol": "circle"},
        )
    )

    buy_date = hit_row.get("buy_date")
    buy_ts = _coerce_timestamp(buy_date)
    if buy_ts is not None:
        buy_date = buy_ts.strftime("%Y-%m-%d")
        buy_bar = selected[selected["bar_time"].dt.strftime("%Y-%m-%d") == buy_date]
        buy_price = float(hit_row["buy_open"]) if pd.notna(hit_row.get("buy_open")) else None
        if buy_price is None and not buy_bar.empty:
            buy_price = float(buy_bar["open"].iloc[-1])
        if buy_price is not None:
            fig.add_trace(
                go.Scatter(
                    x=[buy_date],
                    y=[buy_price],
                    mode="markers+text",
                    name="买入",
                    text=["买入"],
                    textposition="top center",
                    marker={"color": "#2563eb", "size": 12, "symbol": "triangle-up"},
                )
            )

    sell_date = hit_row.get("sell_date")
    sell_ts = _coerce_timestamp(sell_date)
    if sell_ts is not None:
        sell_date = sell_ts.strftime("%Y-%m-%d")
        sell_bar = selected[selected["bar_time"].dt.strftime("%Y-%m-%d") == sell_date]
        sell_price = float(hit_row["sell_close"]) if pd.notna(hit_row.get("sell_close")) else None
        if sell_price is None and not sell_bar.empty:
            sell_price = float(sell_bar["close"].iloc[-1])
        if sell_price is not None:
            fig.add_trace(
                go.Scatter(
                    x=[sell_date],
                    y=[sell_price],
                    mode="markers+text",
                    name="卖出",
                    text=["卖出"],
                    textposition="bottom center",
                    marker={"color": "#16a34a", "size": 12, "symbol": "triangle-down"},
                )
            )

    title = f"{hit_row['stock_code']} {hit_row['stock_name']}  信号日 {signal_date}"
    fig.update_layout(
        title={"text": title, "x": 0.01, "xanchor": "left"},
        height=560,
        margin={"l": 20, "r": 20, "t": 60, "b": 20},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        xaxis={"title": "交易日期", "type": "category", "rangeslider": {"visible": False}},
        yaxis={"title": "价格", "domain": [0.25, 1.0], "side": "right", "fixedrange": False},
        yaxis2={"title": "成交量", "domain": [0.0, 0.17], "side": "right", "fixedrange": False, "showgrid": False},
        bargap=0.12,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch", key=chart_key)


def _render_section_title(title: str, help_text: str) -> None:
    st.markdown(
        f"""
        <div class="mns-section-title">{title}</div>
        <div class="mns-section-help">{help_text}</div>
        """,
        unsafe_allow_html=True,
    )



def _render_group_editor(index: int) -> ConditionGroupConfig:
    prefix = f"group_{index}"
    st.markdown(
        f"""
        <div class="mns-group-header">
            <div class="mns-section-title">组合 {index + 1} 条件面板</div>
            <div class="mns-section-help">先定义这组条件是否参与筛选，再调整趋势、量价和质地约束。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    header_cols = st.columns([1.3, 0.7, 0.8, 2.2])
    name = header_cols[0].text_input("组名", value=f"组合{index + 1}", key=f"{prefix}_name")
    enabled = header_cols[1].checkbox("启用本组", value=index == 0, key=f"{prefix}_enabled")
    hold_days = header_cols[2].number_input("持有天数", min_value=0, value=0, step=1, key=f"{prefix}_hold")
    header_cols[3].markdown(
        "<div class='mns-compact-note'>同一个组合内的启用条件默认同时满足；多组合之间由上方“组合关系”控制。</div>",
        unsafe_allow_html=True,
    )

    core_left, core_right = st.columns([1.0, 1.0])
    with core_left:
        with st.container(border=True):
            _render_section_title("趋势突破", "控制均线、上穿和日K角度，决定走势强度。")
            switch_cols = st.columns(2)
            enable_ema_breakout = switch_cols[0].checkbox("EMA上穿", value=False, key=f"{prefix}_ema_breakout")
            enable_daily_k_angle = switch_cols[1].checkbox("日K角度", value=True, key=f"{prefix}_enable_angle")
            value_cols = st.columns(3)
            ema_period = value_cols[0].number_input("EMA周期", min_value=2, value=21, step=1, key=f"{prefix}_ema")
            daily_k_angle_window = value_cols[1].number_input("日K窗口", min_value=2, value=5, step=1, key=f"{prefix}_angle_win")
            daily_k_angle_min = value_cols[2].number_input("日K角度下限", min_value=0.0, value=40.0, step=1.0, key=f"{prefix}_angle_min")

    with core_right:
        with st.container(border=True):
            _render_section_title("量价活跃", "过滤放量、换手和窗口内成交额，优先保留更活跃的标的。")
            switch_cols = st.columns(3)
            enable_volume_ratio = switch_cols[0].checkbox("带量过滤", value=True, key=f"{prefix}_enable_vol")
            enable_turnover = switch_cols[1].checkbox("换手率", value=True, key=f"{prefix}_enable_turnover")
            enable_recent_volume_spike = switch_cols[2].checkbox("成交额达标", value=index == 0, key=f"{prefix}_enable_recent_vol")
            value_cols = st.columns(4)
            volume_ma_window = value_cols[0].number_input("量均线", min_value=2, value=20, step=1, key=f"{prefix}_vol_ma")
            volume_ratio_min = value_cols[1].number_input("量比阈值", min_value=0.0, value=3.0, step=0.1, key=f"{prefix}_vol_ratio")
            turnover_min = value_cols[2].number_input("换手率下限(%)", min_value=0.0, value=10.0, step=0.5, key=f"{prefix}_turnover")
            recent_volume_spike_min_yi = value_cols[3].number_input("成交额阈值(亿)", min_value=0.0, value=10.0, step=1.0, key=f"{prefix}_recent_vol_min")
            recent_volume_spike_window = st.number_input("成交额回看天数", min_value=2, value=20, step=1, key=f"{prefix}_recent_vol_window")

    with st.container(border=True):
        _render_section_title("质地与位置", "把低位、业绩和价格上限放在一起，方便判断这组条件的偏好。")
        switch_cols = st.columns(3)
        enable_relative_low = switch_cols[0].checkbox("相对低位", value=True, key=f"{prefix}_enable_low")
        enable_earnings_filter = switch_cols[1].checkbox("业绩预期", value=True, key=f"{prefix}_enable_earnings")
        enable_price_max = switch_cols[2].checkbox("股价上限", value=True, key=f"{prefix}_enable_price")
        value_cols = st.columns(5)
        relative_low_window = value_cols[0].number_input("低位周期", min_value=2, value=120, step=1, key=f"{prefix}_low_win")
        relative_low_position_max_pct = value_cols[1].number_input("区间位置上限(%)", min_value=0.0, max_value=100.0, value=30.0, step=1.0, key=f"{prefix}_low_pos")
        earnings_forecast_change_min = value_cols[2].number_input("预告增幅下限(%)", min_value=0.0, value=20.0, step=1.0, key=f"{prefix}_forecast")
        earnings_yoy_min = value_cols[3].number_input("同比下限(%)", min_value=0.0, value=10.0, step=1.0, key=f"{prefix}_yoy")
        price_max = value_cols[4].number_input("股价上限", min_value=0.0, value=50.0, step=1.0, key=f"{prefix}_price")

    with st.expander("高级事件条件：涨停、影线、成交额后续表现、均线突破时序", expanded=False):
        event_cols = st.columns(3)
        enable_limit_up_count = event_cols[0].checkbox("涨停次数", value=False, key=f"{prefix}_enable_limit_up")
        limit_up_count_window = event_cols[1].number_input("涨停回看天数", min_value=2, value=30, step=1, key=f"{prefix}_limit_up_window")
        limit_up_count_min = event_cols[2].number_input("涨停次数下限", min_value=0, value=1, step=1, key=f"{prefix}_limit_up_min")

        shadow_cols = st.columns(4)
        enable_upper_shadow_count = shadow_cols[0].checkbox("上影线次数", value=False, key=f"{prefix}_enable_upper_shadow")
        upper_shadow_window = shadow_cols[1].number_input("上影线回看天数", min_value=2, value=30, step=1, key=f"{prefix}_upper_shadow_window")
        upper_shadow_threshold_pct = shadow_cols[2].number_input("上影线阈值(%)", min_value=0.0, value=5.0, step=0.5, key=f"{prefix}_upper_shadow_pct")
        upper_shadow_count_min = shadow_cols[3].number_input("上影线次数下限", min_value=0, value=1, step=1, key=f"{prefix}_upper_shadow_min")

        lower_shadow_cols = st.columns(4)
        enable_lower_shadow_count = lower_shadow_cols[0].checkbox("下影线次数", value=False, key=f"{prefix}_enable_lower_shadow")
        lower_shadow_window = lower_shadow_cols[1].number_input("下影线回看天数", min_value=2, value=30, step=1, key=f"{prefix}_lower_shadow_window")
        lower_shadow_threshold_pct = lower_shadow_cols[2].number_input("下影线阈值(%)", min_value=0.0, value=5.0, step=0.5, key=f"{prefix}_lower_shadow_pct")
        lower_shadow_count_min = lower_shadow_cols[3].number_input("下影线次数下限", min_value=0, value=1, step=1, key=f"{prefix}_lower_shadow_min")

        follow_cols = st.columns(5)
        enable_amount_followup = follow_cols[0].checkbox("成交额事件后表现", value=False, key=f"{prefix}_enable_amount_follow")
        amount_followup_lookback_window = follow_cols[1].number_input("后续成交额回看天数", min_value=2, value=30, step=1, key=f"{prefix}_amount_follow_window")
        amount_followup_trigger_min_yi = follow_cols[2].number_input("触发成交额(亿)", min_value=0.0, value=10.0, step=1.0, key=f"{prefix}_amount_follow_trigger")
        amount_followup_sum_min_yi = follow_cols[3].number_input("后5日成交额和下限(亿)", min_value=0.0, value=50.0, step=1.0, key=f"{prefix}_amount_follow_sum")
        amount_followup_days = follow_cols[4].number_input("后续统计天数", min_value=1, value=5, step=1, key=f"{prefix}_amount_follow_days")

        breakout_cols = st.columns(3)
        enable_breakout_sequence = breakout_cols[0].checkbox("均线突破时序", value=False, key=f"{prefix}_enable_breakout_sequence")
        breakout_ma20_within_days = breakout_cols[1].number_input("MA20突破距今天数", min_value=1, value=10, step=1, key=f"{prefix}_breakout_ma20_days")
        breakout_ma55_within_days = breakout_cols[2].number_input("MA55突破距今天数", min_value=1, value=5, step=1, key=f"{prefix}_breakout_ma55_days")

    with st.expander("板块强度过滤：按本地板块库筛掉弱板块个股", expanded=False):
        sector_switch_cols = st.columns(4)
        enable_sector_strength_filter = sector_switch_cols[0].checkbox("启用板块过滤", value=False, key=f"{prefix}_enable_sector_strength")
        sector_source = sector_switch_cols[1].text_input("板块源", value="qmt", key=f"{prefix}_sector_source")
        sector_type = sector_switch_cols[2].selectbox("板块类型", options=["", "industry", "concept", "theme", "index", "region"], index=1, key=f"{prefix}_sector_type")
        max_sector_rank = sector_switch_cols[3].number_input("板块排名上限", min_value=0, value=0, step=1, key=f"{prefix}_sector_rank")
        sector_value_cols = st.columns(2)
        min_sector_strength_score = sector_value_cols[0].number_input("板块强度下限", min_value=0.0, value=0.0, step=0.05, key=f"{prefix}_sector_score")
        required_sector_name_keywords = sector_value_cols[1].text_input("板块名关键词", value="", key=f"{prefix}_sector_keywords")

    group_kwargs = dict(
        name=name,
        enabled=enabled,
        ema_period=int(ema_period),
        enable_ema_breakout=enable_ema_breakout,
        volume_ma_window=int(volume_ma_window),
        enable_volume_ratio=enable_volume_ratio,
        volume_ratio_min=float(volume_ratio_min),
        daily_k_angle_window=int(daily_k_angle_window),
        enable_daily_k_angle=enable_daily_k_angle,
        daily_k_angle_min=float(daily_k_angle_min),
        relative_low_window=int(relative_low_window),
        enable_relative_low=enable_relative_low,
        relative_low_position_max=float(relative_low_position_max_pct) / 100.0,
        enable_earnings_filter=enable_earnings_filter,
        earnings_forecast_change_min=float(earnings_forecast_change_min),
        earnings_yoy_min=float(earnings_yoy_min),
        enable_price_max=enable_price_max,
        price_max=float(price_max),
        enable_turnover=enable_turnover,
        turnover_min=float(turnover_min),
        enable_recent_volume_spike=enable_recent_volume_spike,
        recent_volume_spike_window=int(recent_volume_spike_window),
        recent_volume_spike_min=float(recent_volume_spike_min_yi) * 100000000.0,
        enable_limit_up_count=enable_limit_up_count,
        limit_up_count_window=int(limit_up_count_window),
        limit_up_count_min=int(limit_up_count_min),
        enable_upper_shadow_count=enable_upper_shadow_count,
        upper_shadow_window=int(upper_shadow_window),
        upper_shadow_threshold_pct=float(upper_shadow_threshold_pct),
        upper_shadow_count_min=int(upper_shadow_count_min),
        enable_lower_shadow_count=enable_lower_shadow_count,
        lower_shadow_window=int(lower_shadow_window),
        lower_shadow_threshold_pct=float(lower_shadow_threshold_pct),
        lower_shadow_count_min=int(lower_shadow_count_min),
        enable_amount_followup=enable_amount_followup,
        amount_followup_lookback_window=int(amount_followup_lookback_window),
        amount_followup_trigger_min=float(amount_followup_trigger_min_yi) * 100000000.0,
        amount_followup_sum_min=float(amount_followup_sum_min_yi) * 100000000.0,
        amount_followup_days=int(amount_followup_days),
        enable_breakout_sequence=enable_breakout_sequence,
        breakout_ma20_within_days=int(breakout_ma20_within_days),
        breakout_ma55_within_days=int(breakout_ma55_within_days),
        enable_sector_strength_filter=enable_sector_strength_filter,
        sector_source=str(sector_source).strip(),
        sector_type=str(sector_type).strip(),
        max_sector_rank=int(max_sector_rank),
        min_sector_strength_score=float(min_sector_strength_score),
        required_sector_name_keywords=str(required_sector_name_keywords).strip(),
        hold_days=int(hold_days),
    )
    supported_fields = set(inspect.signature(ConditionGroupConfig).parameters)
    filtered_kwargs = {key: value for key, value in group_kwargs.items() if key in supported_fields}
    return ConditionGroupConfig(**filtered_kwargs)


st.title("条件选股工作台")
st.markdown(
    "<div class='mns-page-kicker'>单日筛选、多组条件、历史溯源集中在这一页。先定范围，再调组合，最后执行。</div>",
    unsafe_allow_html=True,
)

db_path = st.sidebar.text_input("DuckDB 路径", value="data/duckdb/mns.duckdb")
main_db_latest_trade_date = _get_latest_trade_date(db_path, "1d")
main_db_stock_count = _get_stock_count(db_path, main_db_latest_trade_date, exclude_st=True)

with st.container(border=True):
    _render_section_title("数据状态", "确认主库日期和可筛选范围，避免拿旧数据直接跑条件。")
    status_cols = st.columns([1.0, 1.0, 1.0, 1.2])
    status_cols[0].metric("主库最新日期", main_db_latest_trade_date or "-")
    status_cols[1].metric("可筛选股票数", f"{main_db_stock_count:,}" if main_db_latest_trade_date else "-")
    status_cols[2].metric("选股数据源", "MoneyNoSleep 主库")
    status_cols[3].metric("状态", "可用" if main_db_latest_trade_date else "不可用")

default_signal_date = pd.Timestamp(main_db_latest_trade_date).date() if main_db_latest_trade_date else pd.Timestamp.today().date()
with st.container(border=True):
    _render_section_title("筛选范围", "这里决定本次运行的日期、股票池和多组合合并方式。")
    base_cols = st.columns([1.0, 1.0, 1.0, 0.9, 0.9, 0.9])
    signal_date = base_cols[0].date_input("信号日期", value=default_signal_date, key="signal_date")
    timeline_start = base_cols[1].date_input("溯源开始", value=default_signal_date - pd.Timedelta(days=30), key="timeline_start")
    timeline_end = base_cols[2].date_input("溯源结束", value=default_signal_date, key="timeline_end")
    universe = base_cols[3].selectbox("股票池", options=list(UNIVERSE_LABELS.keys()), format_func=lambda value: UNIVERSE_LABELS.get(value, value), index=0, key="universe")
    combine_mode = base_cols[4].selectbox("组合关系", options=["any", "all"], format_func=lambda value: "任意一组命中" if value == "any" else "必须同时命中", index=0, key="combine_mode")
    group_count = base_cols[5].selectbox("组合数量", options=[1, 2, 3], index=0, key="group_count")

    options_cols = st.columns([0.8, 3.2])
    exclude_st = options_cols[0].checkbox("排除 ST", value=True, key="exclude_st")
    options_cols[1].markdown(
        "<div class='mns-compact-note'>支持多组并集 / 交集，历史溯源按时间轴回放，命中原因按组合归档展示。</div>",
        unsafe_allow_html=True,
    )

group_tabs = st.tabs([f"组合{i + 1}" for i in range(group_count)])
groups: list[ConditionGroupConfig] = []
for index, tab in enumerate(group_tabs):
    with tab:
        groups.append(_render_group_editor(index))

st.markdown("<div class='mns-action-band'></div>", unsafe_allow_html=True)
action_cols = st.columns([1, 1, 3])
run_screening = action_cols[0].button("执行选股", use_container_width=True, type="primary")
run_timeline = action_cols[1].button("历史溯源", use_container_width=True)
action_cols[2].markdown(
    "<div class='mns-compact-note'>执行会保存一个可回看的批次；历史溯源会按日期生成时间轴结果。</div>",
    unsafe_allow_html=True,
)

if run_screening:
    try:
        result = ConditionScreeningRunner(
            ConditionScreeningConfig(
                db_path=db_path,
                signal_date=str(signal_date),
                universe=universe,
                exclude_st=exclude_st,
                combine_mode=combine_mode,
                groups=groups,
            )
        ).run()
        st.session_state["selected_rule_run_id"] = result["run_id"]
        st.success(f"执行完成：命中 {result['summary']['hit_count']} 只，已保存批次 {result['run_id']}")
    except Exception as exc:
        st.error(f"执行失败：{exc}")

if run_timeline:
    try:
        result = ConditionTimelineRunner(
            ConditionTimelineConfig(
                db_path=db_path,
                start_date=str(timeline_start),
                end_date=str(timeline_end),
                universe=universe,
                exclude_st=exclude_st,
                combine_mode=combine_mode,
                groups=groups,
            )
        ).run()
        st.session_state["selected_timeline_run_id"] = result["run_id"]
        st.success(
            f"历史溯源完成：{result['summary']['date_count']} 个交易日，"
            f"{result['summary']['hit_count']} 次命中，"
            f"{result['summary']['unique_stock_count']} 只股票。"
        )
    except Exception as exc:
        st.error(f"历史溯源失败：{exc}")

result_tabs = st.tabs(["单日结果", "历史时间轴", "历史批次"])

with result_tabs[0]:
    rule_runs = _load_rule_runs(db_path)
    if rule_runs.empty:
        st.info("还没有单日筛选批次。")
    else:
        run_options = rule_runs["run_id"].astype(str).tolist()
        default_rule_run = st.session_state.get("selected_rule_run_id", run_options[0])
        if default_rule_run not in run_options:
            default_rule_run = run_options[0]
        selected_rule_run = st.selectbox("单日筛选批次", options=run_options, index=run_options.index(default_rule_run))
        st.session_state["selected_rule_run_id"] = selected_rule_run
        run_row = rule_runs[rule_runs["run_id"].astype(str) == selected_rule_run].iloc[0]
        result_json = json.loads(run_row["result_json"]) if run_row.get("result_json") else {}
        rule_json = json.loads(run_row["rule_json"]) if run_row.get("rule_json") else {}
        hit_df = _load_rule_hits(db_path, selected_rule_run)

        metrics = st.columns(5)
        metrics[0].metric("筛选日期", str(result_json.get("signal_date", "-")))
        metrics[1].metric("股票池", UNIVERSE_LABELS.get(result_json.get("universe", ""), result_json.get("universe_label", "-")))
        metrics[2].metric("股票总数", f"{int(result_json.get('universe_size', 0)):,}")
        metrics[3].metric("命中数量", f"{int(result_json.get('hit_count', 0)):,}")
        metrics[4].metric("组合关系", "任意一组命中" if result_json.get("combine_mode") == "any" else "必须同时命中")

        with st.expander("本次规则参数", expanded=False):
            st.json(rule_json)

        if hit_df.empty:
            st.warning("该批次没有命中股票。")
        else:
            display_df = _format_hit_display_df(hit_df)
            result_columns = _available_columns(
                display_df,
                [
                    "trade_date",
                    "stock_code",
                    "stock_name",
                    "group_name",
                    "score",
                    "close",
                    "volume_ratio",
                    "daily_k_angle",
                    "turnover_rate",
                    "primary_sector_name",
                    "primary_sector_type",
                    "sector_source",
                    "sector_strength_score",
                    "sector_rank",
                    "limit_up_count_recent",
                    "upper_shadow_count_recent",
                    "lower_shadow_count_recent",
                    "days_since_break_ma20",
                    "days_since_break_ma55",
                    "amount_sum_next_5d",
                    "earnings_signal",
                    "candidate_reason",
                    "hold_return_pct",
                ],
            )
            st.dataframe(
                display_df[result_columns],
                use_container_width=True,
                hide_index=True,
            )
            _render_hit_kline_browser(
                db_path,
                hit_df,
                state_prefix=f"rule_run_{selected_rule_run}",
                heading="单日个股联动K线",
                show_stock_summary=False,
            )

with result_tabs[1]:
    timeline_runs = _load_timeline_runs(db_path)
    if timeline_runs.empty:
        st.info("还没有历史溯源批次。")
    else:
        run_options = timeline_runs["run_id"].astype(str).tolist()
        default_timeline_run = st.session_state.get("selected_timeline_run_id", run_options[0])
        if default_timeline_run not in run_options:
            default_timeline_run = run_options[0]
        selected_timeline_run = st.selectbox("历史溯源批次", options=run_options, index=run_options.index(default_timeline_run))
        st.session_state["selected_timeline_run_id"] = selected_timeline_run
        run_row = timeline_runs[timeline_runs["run_id"].astype(str) == selected_timeline_run].iloc[0]
        result_json = json.loads(run_row["result_json"]) if run_row.get("result_json") else {}
        hit_df = _load_timeline_hits(db_path, selected_timeline_run)

        metrics = st.columns(5)
        metrics[0].metric("开始日期", str(result_json.get("start_date", "-")))
        metrics[1].metric("结束日期", str(result_json.get("end_date", "-")))
        metrics[2].metric("交易日数量", f"{int(result_json.get('date_count', 0)):,}")
        metrics[3].metric("总命中次数", f"{int(result_json.get('hit_count', 0)):,}")
        metrics[4].metric("去重股票数", f"{int(result_json.get('unique_stock_count', 0)):,}")

        if hit_df.empty:
            st.warning("该历史溯源批次没有命中股票。")
        else:
            timeline_tab_1, timeline_tab_2, timeline_tab_3 = st.tabs(["按日时间轴", "股票汇总", "命中明细"])

            with timeline_tab_1:
                daily_counts = hit_df.groupby("trade_date").size().rename("命中数").reset_index()
                st.dataframe(daily_counts, use_container_width=True, hide_index=True)

            with timeline_tab_2:
                _render_hit_kline_browser(
                    db_path,
                    hit_df,
                    state_prefix=f"timeline_run_{selected_timeline_run}",
                    heading="历史股票联动K线",
                    show_stock_summary=True,
                )

            with timeline_tab_3:
                display_df = _format_hit_display_df(hit_df)
                detail_columns = _available_columns(
                    display_df,
                    [
                        "trade_date",
                        "stock_code",
                        "stock_name",
                        "group_name",
                        "score",
                        "close",
                        "volume_ratio",
                        "daily_k_angle",
                        "turnover_rate",
                        "limit_up_count_recent",
                        "upper_shadow_count_recent",
                        "lower_shadow_count_recent",
                        "days_since_break_ma20",
                        "days_since_break_ma55",
                        "amount_sum_next_5d",
                        "candidate_reason",
                    ],
                )
                st.dataframe(
                    display_df[detail_columns],
                    use_container_width=True,
                    hide_index=True,
                )

with result_tabs[2]:
    left, right = st.columns(2)
    with left:
        st.subheader("单日筛选批次")
        rule_runs = _load_rule_runs(db_path)
        if rule_runs.empty:
            st.info("暂无单日筛选批次。")
        else:
            st.dataframe(rule_runs[["run_id", "screening_date", "universe", "strategy_name", "created_time"]], use_container_width=True, hide_index=True)
    with right:
        st.subheader("历史溯源批次")
        timeline_runs = _load_timeline_runs(db_path)
        if timeline_runs.empty:
            st.info("暂无历史溯源批次。")
        else:
            st.dataframe(timeline_runs[["run_id", "start_date", "end_date", "universe", "created_time"]], use_container_width=True, hide_index=True)
