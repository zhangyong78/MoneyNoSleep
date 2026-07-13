from __future__ import annotations

import streamlit as st


st.set_page_config(page_title="交易复核", layout="wide")

st.title("交易复核")
st.caption("这里说明怎么查看买卖点，以及怎么做人工复核。")

st.subheader("主要看哪里")
st.markdown(
    """
    在 `主工作台` 里重点看这些结果区：

    - `交易列表`
    - `K线复核`
    - `人工验证`
    """
)

st.subheader("人工复核会记录什么")
st.markdown(
    """
    - 复核状态
    - 买点评级
    - 卖点评级
    - 风控评价
    - 市场环境
    - 板块环境
    - 问题标签
    - 人工备注
    """
)

st.subheader("典型使用方式")
st.markdown(
    """
    1. 先跑出交易结果
    2. 在 `K线复核` 看买卖点位置
    3. 在 `人工验证` 给每笔交易打标签
    4. 最后去 `问题归因` 看整体统计
    """
)
