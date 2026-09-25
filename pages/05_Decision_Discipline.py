from __future__ import annotations

import pandas as pd
import streamlit as st

from src.research.decision_discipline_runtime_v1 import load_decision_discipline_runtime
from src.research.decision_discipline_v1 import DecisionEvidence, evaluate_manual_review_eligibility


@st.cache_data(ttl=180, show_spinner=False)
def _cached_decision_discipline_runtime():
    return load_decision_discipline_runtime()


st.set_page_config(
    page_title="Christiania — Decision & Discipline",
    page_icon="🧭",
    layout="wide",
)

st.title("Christiania — Decision Engine & Discipline Leakage")
st.caption(
    "Governance before execution. NO TRADE is a successful outcome. This page has no broker authority."
)

runtime = _cached_decision_discipline_runtime()
if runtime.state == "DISCIPLINE_EVIDENCE_AVAILABLE":
    st.success(runtime.state)
elif runtime.state == "DATABASE_UNAVAILABLE":
    st.error(runtime.state)
else:
    st.info(runtime.state)

c1, c2, c3 = st.columns(3)
c1.metric("Decision authority", runtime.decision_authority)
c2.metric("Approved executions", runtime.approved_execution_count)
c3.metric("Discretionary executions", runtime.discretionary_execution_count)

st.write(runtime.detail)
st.write(
    {
        "calibration_shadow_state": runtime.calibration_shadow_state,
        "promotion_authority": runtime.promotion_authority,
        "execution_classification_state": runtime.execution_classification_state,
    }
)

st.subheader("Discipline leakage")
if runtime.discipline_leakage is None:
    st.info(
        "No explicit approved-vs-discretionary execution evidence is scoreable yet. Christiania will not infer operator behaviour from ambiguous historical fields."
    )
else:
    leakage = runtime.discipline_leakage
    a, b, c = st.columns(3)
    a.metric("Discretionary share", f"{100 * leakage['discretionary_share']:.1f}%")
    b.metric("Leakage state", leakage["discipline_leakage_state"])
    c.metric("Failure attribution", leakage["failure_attribution"])
    segments = pd.DataFrame(
        [
            {"segment": "Model-approved", **leakage["approved"]},
            {"segment": "Discretionary/unapproved", **leakage["discretionary"]},
        ]
    )
    st.dataframe(segments, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Manual-review eligibility sandbox")
st.caption(
    "Research-only decision governance. Eligibility means a human may review a candidate; it never means submit an order."
)

r1, r2, r3, r4 = st.columns(4)
defined_risk = r1.checkbox("Defined risk", value=True)
family_state = r2.selectbox(
    "Edge family activation",
    ["NOT_ACTIVATED", "ACTIVATED_FOR_MANUAL_REVIEW"],
    index=0,
)
calibration_state = r3.selectbox("Calibration", ["ACCUMULATING", "CALIBRATED"], index=0)
robustness_state = r4.selectbox("Robustness", ["UNTESTED", "ROBUST"], index=0)

s1, s2, s3, s4 = st.columns(4)
sample_state = s1.selectbox("Sample sufficiency", ["INSUFFICIENT", "SUFFICIENT"], index=0)
ev_score = s2.slider("Evidence quality", 0.0, 1.0, 0.50, 0.01)
cal_score = s3.slider("Calibration score", 0.0, 1.0, 0.50, 0.01)
rob_score = s4.slider("Robustness score", 0.0, 1.0, 0.50, 0.01)

p1, p2, p3, p4 = st.columns(4)
risk_score = p1.slider("Risk compensation score", 0.0, 1.0, 0.50, 0.01)
expected_max = p2.number_input("Expected P&L / max loss", value=0.00, step=0.01, format="%.4f")
expected_cvar = p3.number_input("Expected P&L / CVaR95", value=0.00, step=0.01, format="%.4f")
prob_profit = p4.number_input("P(profit)", min_value=0.0, max_value=1.0, value=0.50, step=0.01)

if st.button("Evaluate governance state", type="primary"):
    result = evaluate_manual_review_eligibility(
        DecisionEvidence(
            structure_defined_risk=bool(defined_risk),
            family_activation_state=str(family_state),
            calibration_state=str(calibration_state),
            robustness_state=str(robustness_state),
            sample_state=str(sample_state),
            expected_pnl_to_max_loss=float(expected_max),
            expected_pnl_to_cvar95=float(expected_cvar),
            probability_of_profit=float(prob_profit),
            evidence_quality_score=float(ev_score),
            calibration_score=float(cal_score),
            robustness_score=float(rob_score),
            risk_compensation_score=float(risk_score),
        )
    )
    st.metric("Decision", result.decision)
    st.metric("Composite score", f"{result.score:.3f}")
    st.write(
        {
            "hard_block_reasons": result.hard_block_reasons,
            "soft_review_reasons": result.soft_review_reasons,
            "decision_authority": result.decision_authority,
        }
    )

st.caption(
    "Win rate is displayed only as descriptive evidence. Christiania ranks governance on bounded downside, evidence quality, calibration, robustness and risk compensation."
)
