from __future__ import annotations

import streamlit as st


st.set_page_config(page_title="自选观察", layout="wide")

st.title("自选观察")
st.caption("这是后续要扩展的观察池入口，目前先说明用途。")

st.subheader("计划用途")
st.markdown(
    """
    后续这里会承载：

    - 自选股列表
    - 重点标的观察
    - 盘前候选池
    - 复盘后需要持续跟踪的股票
    """
)

st.info("当前版本还没有独立的自选观察功能，先以主工作台里的候选股、信号和交易结果为主。")
