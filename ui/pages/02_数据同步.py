from __future__ import annotations

import streamlit as st

from ui.streamlit_app import render_sync_controls


st.set_page_config(page_title="数据同步", layout="wide")

st.title("数据同步")
st.caption("在这里执行行情同步，并查看同步说明。")

db_path = st.text_input("DuckDB", "data/duckdb/mns.duckdb")
render_sync_controls(db_path)
st.divider()

st.subheader("可用数据源")
st.markdown(
    """
    - `miniQMT`：优先推荐，适合日线和分钟线，本地连接速度快。
    - `BaoStock`：公开数据源，适合补充和校验日线数据。
    - `BaoStock 断点同步工具`：适合长时间回补分钟线，支持状态文件续跑，并可本地从 5m 升周期到 15m / 30m / 1h。
    - `AKShare`：当前主要用于日线补充。
    """
)

st.subheader("关键概念")
st.markdown(
    """
    - `DuckDB`：本地数据库，页面查询主要从这里读取。
    - `Parquet`：本地分区文件，用于归档和批量处理。
    - `timeframe`：周期，例如 `1d`、`5m`、`15m`。
    - `复权方式`：前复权、后复权、不复权。
    """
)

st.subheader("操作步骤")
st.markdown(
    """
    1. 先在本页选择 `DuckDB` 路径
    2. 再执行 `同步 miniQMT 行情` 或 `同步 BaoStock 行情`
    3. 默认会同步全部股票；如果只想补个股，可以取消勾选后输入股票代码
    4. 点击同步按钮
    5. 同步完成后，回到 `主工作台` 查看本地数据
    """
)

st.success("如果你主要做 5 分钟策略，优先同步 miniQMT 的 `5m` 数据。")
