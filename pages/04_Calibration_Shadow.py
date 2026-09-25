from __future__ import annotations

import pandas as pd
import streamlit as st

from src.research.prospective_shadow_runtime_v1 import load_calibration_shadow_runtime


@st.cache_data(ttl=180, show_spinner=False)
def _cached_calibration_shadow_runtime():
    return load_calibration_shadow_runtime()


st.set_page_config(
    page_title="Christiania — Calibration & Prospective Shadow",
    page_icon="🧪",
    layout="wide",
)

st.title("Christiania — Calibration & Prospective Shadow")
st.caption(
    "Prospective evidence, probability-calibration readiness and shadow lifecycle review. "
    "No automatic promotion or trading authority."
)

state = _cached_calibration_shadow_runtime()

if state.state == "DESCRIPTIVE_REVIEW_AVAILABLE":
    st.success(state.state)
elif state.state.startswith("ACCUMULATING"):
    st.info(state.state)
else:
    st.warning(state.state)

st.write(state.detail)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Prospective dates", state.prospective.prospective_independent_dates)
m2.metric("Frozen hypotheses", state.prospective.hypothesis_count)
m3.metric("Shadow candidates", state.shadow.candidate_count)
m4.metric("Complete shadow marks", state.shadow.complete_mark_count)

st.subheader("Prospective governance firewall")
firewall_rows = [
    {"control": "p-values", "enabled": state.prospective.p_values_enabled},
    {"control": "FDR", "enabled": state.prospective.fdr_enabled},
    {"control": "admission", "enabled": state.prospective.admission_enabled},
    {"control": "decision", "enabled": state.prospective.decision_enabled},
]
st.dataframe(pd.DataFrame(firewall_rows), use_container_width=True, hide_index=True)
st.caption(
    "Package D does not turn these controls on. A descriptive review becoming available is not model promotion."
)

st.subheader("Prospective freeze")
st.write(
    {
        "freeze_run_id": state.prospective.freeze_run_id,
        "frozen_through_session_date": state.prospective.frozen_through_session_date,
        "prospective_start_session_date": state.prospective.prospective_start_session_date,
        "protocol_state": state.prospective.protocol_state,
        "promotion_authority": state.promotion_authority,
    }
)

st.subheader("Shadow lifecycle evidence")
shadow_rows = [
    {"metric": "shadow tracked", "count": state.shadow.shadow_tracked_count},
    {"metric": "closed or expired", "count": state.shadow.closed_or_expired_count},
    {"metric": "scored", "count": state.shadow.scored_count},
    {"metric": "rejected", "count": state.shadow.rejected_count},
    {"metric": "complete marks", "count": state.shadow.complete_mark_count},
    {"metric": "incomplete marks", "count": state.shadow.incomplete_mark_count},
    {"metric": "profitable marks", "count": state.shadow.profitable_mark_count},
    {"metric": "losing marks", "count": state.shadow.losing_mark_count},
    {"metric": "zero marks", "count": state.shadow.zero_mark_count},
    {"metric": "marked candidates", "count": state.shadow.marked_candidate_count},
    {"metric": "marked research runs", "count": state.shadow.marked_research_run_count},
]
st.dataframe(pd.DataFrame(shadow_rows), use_container_width=True, hide_index=True)

st.subheader("Probability-calibration channels")
c1, c2 = st.columns(2)
c1.metric("P(thesis correct)", state.thesis_probability_channel_state)
c2.metric("P(trade profitable)", state.profit_probability_channel_state)
st.caption(
    "The two probability channels are deliberately separate. Shadow P&L outcomes cannot be used to pretend that a thesis probability was calibrated, and vice versa."
)

st.subheader("Decision-time probability capture")
st.write(state.shadow.decision_time_probability_state)
st.caption(
    "If shadow decision-time probabilities are not captured immutably, Package D reports the gap instead of fabricating a calibration score from hindsight."
)
