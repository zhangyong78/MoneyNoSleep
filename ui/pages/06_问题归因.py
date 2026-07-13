from __future__ import annotations

import streamlit as st


st.set_page_config(page_title="问题归因", layout="wide")

st.title("问题归因")
st.caption("这里说明人工复核完成后，问题标签统计怎么理解。")

st.subheader("问题标签是什么")
st.markdown(
    """
    当前常见标签包括：

    - 追高
    - 买早
    - 买晚
    - 卖早
    - 卖晚
    - 板块退潮
    - 非龙头
    - 止损过紧
    - 止损过宽
    - 市场环境过滤不足
    """
)

st.subheader("它的作用")
st.markdown(
    """
    它不是为了给某一笔交易找借口，而是为了做批量复盘：

    - 看错误是否反复出现
    - 看主要损失来自哪里
    - 看策略问题和执行问题怎么区分
    """
)

st.subheader("结果在哪里看")
st.markdown(
    """
    `主工作台` 里的 `问题归因` 结果区会展示统计表。  
    前提是你已经在 `人工验证` 里给交易打过标签。
    """
)
