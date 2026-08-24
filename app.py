import streamlit as st

st.set_page_config(
    page_title="Trade Log",
    page_icon="📈",
    layout="wide",
)

st.title("Trade Log")
st.caption("Personal options trade calibration and research log")

st.subheader("v0.1")

st.write(
    """
    The goal of this tool is to record trade ideas before entering them,
    track what actually happened, and measure whether our predictions
    are becoming better calibrated over time.
    """
)

st.info(
    "For now, this is a local research log. "
    "No live trading, no broker connection, and no automated execution."
)

st.metric("Trades logged", 0)
st.metric("Open positions", 0)
st.metric("Closed trades", 0)