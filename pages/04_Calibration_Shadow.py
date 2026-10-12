from __future__ import annotations

import pandas as pd
import streamlit as st

from src.research.prospective_shadow_runtime_v1 import load_calibration_shadow_runtime



st.set_page_config(
    page_title="Christiania — Calibration & Prospective Shadow",
    page_icon="🧪",
    layout="wide",
)

@st.cache_data(ttl=180, show_spinner=False)
def _cached_calibration_shadow_runtime():
    return load_calibration_shadow_runtime()

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


st.divider()
st.subheader("Strategy falsification — Stage 0")
st.caption(
    "Explore all 11 strategy families under explicit HYPOTHETICAL quotes and costs. "
    "Nothing here is a broker quote, verified fill, forecast, positive expectancy, "
    "approved trade or recorded Shadow Lab outcome."
)

from dataclasses import replace as _scenario_replace
from decimal import Decimal as _StageDecimal
from src.research.strategy_falsification_v1 import CATALOGUE as _stage_catalogue, evaluate as _stage_evaluate
from src.research.shadow_stage0_scenarios_v1 import hypothetical_scenario as _stage_scenario

with st.expander("Open the 11-strategy scenario workbench", expanded=False):
    st.dataframe(
        pd.DataFrame(
            [{"ID": k, "Strategy": label, "Class": group,
              "Forward edge": "UNVERIFIED"} for k, (label, group) in _stage_catalogue.items()]
        ),
        hide_index=True, use_container_width=True,
    )
    selected = st.selectbox(
        "Structure family",
        list(_stage_catalogue),
        format_func=lambda k: f"{k} — {_stage_catalogue[k][0]}",
        key="shadow_stage0_selected",
    )
    scenario, default_policy = _stage_scenario(selected)
    st.caption(
        "Illustrative premiums and quote timestamps are generated for this simulation. "
        "They are not fetched from ThetaData or Saxo. The €500 ceiling is fixed; "
        "fees, slippage, tax and FX below are user assumptions, not verified brokerage costs."
    )
    with st.form("shadow_stage0_illustrative_form"):
        st.markdown("**Manually adjust indicative entry-side premiums (USD per share)**")
        modified_legs = []
        for idx, leg in enumerate(scenario.legs):
            descriptor = (
                f"Leg {idx + 1}: {leg.side} {leg.quantity} "
                f"{leg.kind} " + (f"strike {leg.strike}" if leg.strike is not None else "shares")
            )
            side_price = leg.ask if leg.side == "BUY" else leg.bid
            synthetic_price = st.number_input(
                descriptor, min_value=0.0, max_value=100000.0,
                value=float(side_price), step=0.25,
                key=f"stage0_leg_{selected}_{idx}",
            )
            corrected = _StageDecimal(str(synthetic_price))
            modified_legs.append(_scenario_replace(
                leg,
                ask=corrected if leg.side == "BUY" else leg.ask,
                bid=corrected if leg.side == "SELL" else leg.bid,
            ))
        a, b, c, d = st.columns(4)
        assumed_fee = a.number_input("Option fee, USD/contract/side", 0.0, 1000.0, 3.0, 0.5)
        assumed_slippage = b.number_input("Additional round-trip costs, USD", 0.0, 1000.0, 1.0, 0.5)
        assumed_tax = c.number_input("Tax assumption, USD", 0.0, 1000.0, 1.0, 0.5)
        assumed_fx = d.number_input("Assumed USD per EUR", 0.01, 10.0, 1.10, 0.01)
        submitted = st.form_submit_button("Evaluate synthetic feasibility")
    if submitted:
        assumptions = _scenario_replace(
            default_policy,
            option_cost_per_contract_side_usd=_StageDecimal(str(assumed_fee)),
            additional_round_trip_cost_usd=_StageDecimal(str(assumed_slippage)),
            tax_cost_usd=_StageDecimal(str(assumed_tax)),
            eur_to_usd=_StageDecimal(str(assumed_fx)),
        )
        evaluated = _stage_evaluate(
            _scenario_replace(scenario, legs=tuple(modified_legs)), assumptions,
        ).as_dict()
        st.warning(
            f"**{evaluated['state']}** — simulated structure, NOT an executable "
            "market opportunity or a trading recommendation."
        )
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Gross maximum loss (USD)", evaluated.get("gross_max_loss_usd") or "Unknown")
        m2.metric("Gross maximum profit (USD)", evaluated.get("gross_max_profit_usd") or
                  ("Unbounded theory" if evaluated.get("unlimited_profit") else "Unknown"))
        m3.metric("Estimated capital (EUR)", evaluated.get("conservative_capital_eur") or "Unknown")
        m4.metric("Budget cap (EUR)", "500")
        st.write("**Rejection / uncertainty reasons:**",
                 list(evaluated.get("reasons") or ()) or ["None for these assumed inputs; execution still unverified"])
        st.caption(
            "Hypothetical expiry payoff and costs only. Bid/ask sizes, FX, timestamps "
            "and fees were assumed. No broker strategy fill, live quote entitlement, "
            "forward holdout performance or independent receipt is established."
        )
