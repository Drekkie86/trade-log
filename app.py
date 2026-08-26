import streamlit as st


st.set_page_config(
    page_title="Christiania",
    page_icon="📈",
    layout="wide",
)


st.title("Christiania")

st.caption(
    "Options research, candidate tracking, "
    "risk analysis and learning."
)

st.divider()


st.subheader("Research mode")

st.write(
    "Christiania is currently being prepared for "
    "automated market-data ingestion and trial candidate tracking."
)


col_1, col_2, col_3 = st.columns(3)

with col_1:
    st.metric(
        "Tracked candidates",
        "—",
    )

with col_2:
    st.metric(
        "Paper positions",
        "—",
    )

with col_3:
    st.metric(
        "Live positions",
        "—",
    )


st.divider()

st.info(
    "Next milestone: ingest a real option chain, "
    "store market snapshots, generate candidates, "
    "and compare them with matched controls."
)