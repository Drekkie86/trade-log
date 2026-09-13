from __future__ import annotations

import streamlit as st

from src.dashboard.research_command_deck_v1 import load_research_command_deck

st.set_page_config(
    page_title="Christiania — Research Command Deck",
    page_icon="⚓",
    layout="wide",
)

st.title("Christiania — Research Command Deck")
st.caption(
    "Discovery and prospective evidence surface. Research status is not a trading recommendation."
)

if st.button("Refresh research state", type="primary"):
    st.rerun()

state = load_research_command_deck()
runtime = state.runtime
governance = state.governance

if state.ready:
    st.success(f"{state.operating_state} — {state.operating_detail}")
else:
    st.error(f"{state.operating_state} — {state.operating_detail}")

st.subheader("Programme governance")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Family budget", governance.get("budget_status") or "UNKNOWN")
col2.metric("Opened families", governance.get("opened_family_count", 0))
remaining = governance.get("remaining_family_slots")
col3.metric("Remaining family slots", "UNSET" if remaining is None else remaining)
col4.metric("Hypothesis evaluations", governance.get("hypothesis_evaluation_count", 0))

st.write(f"**Activation gate:** `{governance.get('activation_state', 'UNKNOWN')}`")
st.write(governance.get("activation_detail") or "No activation detail available.")
st.write(f"**Inference gate:** `{governance.get('inference_state', 'UNKNOWN')}`")
st.write(governance.get("inference_detail") or "No inference detail available.")

if governance.get("budget_errors"):
    for item in governance["budget_errors"]:
        st.error(f"Budget error: {item}")
if governance.get("budget_warnings"):
    for item in governance["budget_warnings"]:
        st.warning(item)

flags1, flags2, flags3, flags4 = st.columns(4)
flags1.metric("Calibration dates", governance.get("calibration_distinct_dates") or 0)
flags2.metric("p-values", "ENABLED" if governance.get("p_values_enabled") else "OFF")
flags3.metric("FDR", "ENABLED" if governance.get("fdr_enabled") else "OFF")
flags4.metric("Decision use", "ENABLED" if governance.get("decision_enabled") else "OFF")
st.caption(f"Calibration readiness: {governance.get('calibration_readiness') or 'NO EVIDENCE YET'}")

family_usage = governance.get("family_usage") or []
if family_usage:
    st.write("**Logged hypothesis families**")
    st.dataframe(family_usage, use_container_width=True, hide_index=True)
else:
    st.info("No hypothesis-family evaluations are present in the append-only programme log yet.")

st.divider()
st.subheader("Research heartbeat")
latest_iteration = runtime.get("latest_iteration") or {}
latest_run = runtime.get("latest_run") or {}
daemon_health = runtime.get("daemon_health") or {}
market_clock = runtime.get("market_clock") or {}

h1, h2, h3, h4 = st.columns(4)
h1.metric("Daemon", daemon_health.get("state") or "UNKNOWN")
h2.metric("Latest iteration", latest_iteration.get("status") or "NONE")
h3.metric("Latest research run", latest_run.get("status") or "NONE")
h4.metric("US market", market_clock.get("session_state") or market_clock.get("state") or "UNKNOWN")

st.caption(
    f"Latest iteration completed: {latest_iteration.get('completed_at') or 'n/a'} · "
    f"research run: {latest_iteration.get('research_run_id') or 'n/a'}"
)

st.subheader("Prospective evidence accumulation")
prospective = runtime.get("prospective") or {}
p1, p2, p3, p4 = st.columns(4)
p1.metric("Observation rows", prospective.get("observation_rows", 0))
p2.metric("Independent dates", prospective.get("independent_dates", 0))
p3.metric("Recovered rows", prospective.get("recovered_rows", 0))
p4.metric("Recovered samples", prospective.get("recovered_samples", 0))
st.caption(
    f"Prospective start session: {prospective.get('prospective_start_session_date') or 'not recorded'}"
)

st.subheader("Research funnel")
counts = runtime.get("research_counts") or {}
f1, f2, f3, f4, f5 = st.columns(5)
f1.metric("Surfaced", counts.get("surfaced_total", 0))
f2.metric("Proposed", counts.get("proposals_total", 0))
f3.metric("Admitted", counts.get("admitted_total", 0))
f4.metric("Shadow candidates", counts.get("shadow_candidates", 0))
f5.metric("Shadow marks", counts.get("shadow_marks", 0))

st.subheader("Frozen model governance")
models = runtime.get("models") or []
if models:
    st.dataframe(models, use_container_width=True, hide_index=True)
else:
    st.info("No model-governance registry rows are available.")

st.subheader("Prospective hypotheses")
hypotheses = runtime.get("hypotheses") or []
if hypotheses:
    st.dataframe(hypotheses, use_container_width=True, hide_index=True)
else:
    st.info("No prospective hypothesis freeze is available.")

st.subheader("Recent surfaced anomalies")
anomalies = runtime.get("recent_anomalies") or []
if anomalies:
    st.dataframe(anomalies, use_container_width=True, hide_index=True)
else:
    st.info("No surfaced anomalies in the current read model.")

st.subheader("Recent shadow candidates")
candidates = runtime.get("recent_candidates") or []
if candidates:
    st.dataframe(candidates, use_container_width=True, hide_index=True)
else:
    st.info("No shadow candidates in the current read model.")

with st.expander("Recent daemon iterations"):
    iterations = runtime.get("recent_iterations") or []
    if iterations:
        st.dataframe(iterations, use_container_width=True, hide_index=True)
    else:
        st.write("No daemon iteration history available.")

with st.expander("Programme allocation detail"):
    st.json(
        {
            "period_id": governance.get("period_id"),
            "period_start": governance.get("period_start"),
            "period_end": governance.get("period_end"),
            "max_families": governance.get("max_families"),
            "allocated_family_ids": governance.get("allocated_family_ids", []),
            "logged_family_ids": governance.get("logged_family_ids", []),
        }
    )

st.divider()
st.caption(
    "Christiania doctrine: academic or historical evidence is a hypothesis source, not proof of current tradable edge. "
    "New families remain fail-closed until programme allocation, prospective evidence, costs, robustness and calibration permit promotion."
)
