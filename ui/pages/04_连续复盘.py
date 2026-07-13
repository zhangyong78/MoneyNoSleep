from __future__ import annotations

import streamlit as st


st.set_page_config(page_title="连续复盘", layout="wide")

st.title("连续复盘")
st.caption("这里说明当前系统里的两种复盘方式。")

st.subheader("1. 日线快速复盘")
st.markdown(
    """
    适合先验证筛选条件有没有基础效果。它会完成这些步骤：

    - 从本地日线数据里找候选股
    - 生成信号
    - 按简化规则做快速回测
    - 输出交易、资金曲线、导出文件
    """
)

st.subheader("2. 5分钟回踩复盘")
st.markdown(
    """
    适合验证盘中节奏。当前版本核心逻辑包括：

    - `EMA21 > MA55`
    - `close > MA55`
    - 回踩 `EMA21`
    - 用 `ATR10` 设置止损和止盈
    - 用风险预算控制仓位
    """
)

st.subheader("在哪里运行")
st.markdown(
    """
    打开 `主工作台`，在侧边栏中运行：

    - `运行快速复盘`
    - `运行 5分钟回踩复盘`
    """
)

st.warning("当前这两类复盘都属于研究和验证工具，不代表真实可下单执行。")
