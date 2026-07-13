from __future__ import annotations

import streamlit as st


st.set_page_config(page_title="Moneynosleep", layout="wide")
st.set_option("client.toolbarMode", "minimal")

navigation = st.navigation(
    [
        st.Page("streamlit_app.py", title="主工作台", default=True),
        st.Page("pages/01_使用说明.py", title="使用说明"),
        st.Page("pages/02_数据同步.py", title="数据同步"),
        st.Page("pages/03_条件选股.py", title="条件选股"),
        st.Page("pages/04_连续复盘.py", title="连续复盘"),
        st.Page("pages/05_交易复核.py", title="交易复核"),
        st.Page("pages/06_问题归因.py", title="问题归因"),
        st.Page("pages/07_自选观察.py", title="自选观察"),
        st.Page("pages/08_条件特征说明.py", title="条件特征说明"),
    ],
    position="sidebar",
)

navigation.run()
