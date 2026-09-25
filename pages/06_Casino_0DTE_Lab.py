from __future__ import annotations

import pandas as pd
import streamlit as st

from src.research.casino_0dte_runtime_v1 import load_casino_0dte_runtime
from src.research.casino_0dte_v1 import (
    CasinoRiskPolicy,
    ScenarioOutcome,
    ZeroDteDiagnostics,
    evaluate_0dte_diagnostics,
    evaluate_casino_experiment,
)


@st.cache_data(ttl=180, show_spinner=False)
def _cached_casino_0dte_runtime():
    return load_casino_0dte_runtime()


st.set_page_config(
    page_title="Christiania — Casino 0DTE Lab",
    page_icon="🎲",
    layout="wide",
)

st.title("Christiania — Casino 0DTE Lab")
st.caption(
    "Casino in spirit, quant in discipline. Separate research namespace; no Main Engine authority and no broker execution."
)

runtime = _cached_casino_0dte_runtime()
if runtime.state == "ZERO_DTE_RESEARCH_EVIDENCE_AVAILABLE":
    st.success(runtime.state)
elif runtime.state == "DATABASE_UNAVAILABLE":
    st.error(runtime.state)
else:
    st.info(runtime.state)

m1, m2, m3, m4 = st.columns(4)
m1.metric("0DTE sessions", runtime.zero_dte_session_count)
m2.metric("0DTE quotes", runtime.zero_dte_quote_count)
m3.metric("Underlyings", runtime.zero_dte_underlying_count)
m4.metric("Greek observations", runtime.greek_observation_count)
st.write(
    {
        "namespace": runtime.namespace,
        "main_engine_authority": runtime.main_engine_authority,
        "casino_authority": runtime.casino_authority,
        "dealer_positioning_state": runtime.dealer_positioning_state,
    }
)
st.write(runtime.detail)

st.divider()
st.subheader("0DTE volatility / microstructure diagnostic")
st.caption(
    "Descriptive only. A positive implied-minus-forecast variance gap is not itself a tradable edge."
)

v1, v2, v3, v4 = st.columns(4)
iv = v1.number_input("Annualized IV", min_value=0.0, value=0.30, step=0.01)
rv = v2.number_input("Forecast annualized RV", min_value=0.0, value=0.22, step=0.01)
minutes_left = v3.number_input("Minutes remaining", min_value=0.0, max_value=390.0, value=195.0, step=5.0)
jump_var = v4.number_input("Remaining jump variance", min_value=0.0, value=0.0, step=0.00001, format="%.6f")

s1, s2, s3 = st.columns(3)
call_iv = s1.number_input("Call IV", min_value=0.0, value=0.29, step=0.01)
put_iv = s2.number_input("Put IV", min_value=0.0, value=0.31, step=0.01)
spread_fraction = s3.number_input("Bid/ask spread fraction", min_value=0.0, value=0.04, step=0.01)

g1, g2 = st.columns(2)
gamma_cash = g1.number_input("Gamma exposure cash proxy", value=0.0, step=10.0)
theta_cash = g2.number_input("Theta decay cash/day proxy", value=0.0, step=10.0)

remaining_year_fraction = float(minutes_left) / (390.0 * 252.0)
diagnostic = evaluate_0dte_diagnostics(
    ZeroDteDiagnostics(
        implied_volatility_annualized=float(iv),
        forecast_realized_volatility_annualized=float(rv),
        remaining_year_fraction=remaining_year_fraction,
        jump_variance_remaining=float(jump_var),
        call_iv=float(call_iv),
        put_iv=float(put_iv),
        gamma_exposure_cash=float(gamma_cash),
        theta_decay_cash_per_day=float(theta_cash),
        bid_ask_spread_fraction=float(spread_fraction),
    )
)

d1, d2, d3, d4 = st.columns(4)
d1.metric("Remaining variance gap", f"{diagnostic.variance_gap_remaining:.6f}")
d2.metric("Variance ratio", "n/a" if diagnostic.variance_ratio is None else f"{diagnostic.variance_ratio:.3f}")
d3.metric("Put-call IV skew", "n/a" if diagnostic.skew_put_minus_call is None else f"{diagnostic.skew_put_minus_call:.4f}")
d4.metric("Liquidity", diagnostic.liquidity_state)
st.caption(diagnostic.evidence_label)

st.divider()
st.subheader("Scenario EV + hard Casino risk budget")
st.caption(
    "A scenario can be exciting and still resolve to NO TRADE. Risk budget, liquidity and net EV are independent gates."
)

r1, r2, r3 = st.columns(3)
bankroll = r1.number_input("Laboratory bankroll", min_value=1.0, value=500.0, step=25.0)
casino_cap = r2.number_input("Casino capital cap", min_value=1.0, value=500.0, step=25.0)
max_fraction = r3.number_input("Max loss fraction per experiment", min_value=0.001, max_value=1.0, value=0.05, step=0.01)

p1, p2, p3 = st.columns(3)
max_loss = p1.number_input("Defined maximum loss", min_value=0.0, value=20.0, step=1.0)
transaction_costs = p2.number_input("Transaction costs", min_value=0.0, value=1.0, step=0.25)
slippage = p3.number_input("Slippage", min_value=0.0, value=1.0, step=0.25)

st.markdown("**Three-scenario distribution**")
scenario_df = pd.DataFrame(
    [
        {"scenario": "favorable", "probability": 0.55, "pnl_before_costs": 20.0},
        {"scenario": "middle", "probability": 0.30, "pnl_before_costs": -5.0},
        {"scenario": "tail", "probability": 0.15, "pnl_before_costs": -20.0},
    ]
)
edited = st.data_editor(
    scenario_df,
    use_container_width=True,
    hide_index=True,
    disabled=["scenario"],
)

if st.button("Evaluate Casino experiment", type="primary"):
    outcomes = [
        ScenarioOutcome(float(row["probability"]), float(row["pnl_before_costs"]))
        for _, row in edited.iterrows()
    ]
    try:
        result = evaluate_casino_experiment(
            outcomes,
            risk_policy=CasinoRiskPolicy(
                bankroll=float(bankroll),
                casino_cap=float(casino_cap),
                max_loss_fraction=float(max_fraction),
            ),
            defined_risk=True,
            max_loss=float(max_loss),
            transaction_costs=float(transaction_costs),
            slippage=float(slippage),
            liquidity_state=diagnostic.liquidity_state,
        )
    except ValueError as exc:
        st.error(str(exc))
    else:
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Casino state", result.state)
        q2.metric("Risk budget", f"{result.risk_budget:.2f}")
        q3.metric("Net scenario EV", f"{result.expected_pnl_net:.2f}")
        q4.metric("P(net profit)", f"{100 * result.probability_of_profit_net:.1f}%")
        st.write(
            {
                "loss_cvar95": result.loss_cvar95,
                "expected_pnl_to_max_loss": result.expected_pnl_to_max_loss,
                "reasons": result.reasons,
                "decision_authority": result.decision_authority,
                "namespace": result.namespace,
            }
        )

st.caption(
    "Dealer positioning is intentionally absent unless a measured, sourced input exists. Christiania does not infer dealer gamma from folklore or social-media heuristics."
)
