from __future__ import annotations

import pandas as pd
import streamlit as st

from src.quant.risk import OptionLeg
from src.quant.risk_selection import (
    DistributionAssumptions,
    RiskBudget,
    evaluate_structure_distribution,
)
from src.research.edge_risk_runtime_v1 import load_edge_risk_runtime


st.set_page_config(
    page_title="Christiania — Edge Library & Risk Lab",
    page_icon="⚖️",
    layout="wide",
)

st.title("Christiania — Edge Library & Risk Lab")
st.caption(
    "Risk selection, not risk avoidance. Research-only diagnostics; no edge family activation, "
    "trade approval or broker execution authority."
)

with st.sidebar:
    st.subheader("Research runtime")
    train_window = st.number_input("Forecast training window", min_value=30, max_value=252, value=40, step=5)
    horizon_days = st.number_input("Forecast horizon (sessions)", min_value=1, max_value=30, value=5, step=1)
    limit_underlyings = st.number_input("Underlying limit", min_value=1, max_value=26, value=8, step=1)
    bootstrap_samples = st.number_input("Bootstrap samples", min_value=50, max_value=5000, value=500, step=50)

runtime = load_edge_risk_runtime(
    train_window=int(train_window),
    horizon_days=int(horizon_days),
    limit_underlyings=int(limit_underlyings),
    bootstrap_samples=int(bootstrap_samples),
)

if runtime.state == "RESEARCH_DIAGNOSTICS_AVAILABLE":
    st.success(runtime.state)
elif runtime.state == "ACCUMULATING_EVIDENCE":
    st.info(runtime.state)
else:
    st.warning(runtime.state)

col1, col2 = st.columns(2)
col1.metric("Decision authority", runtime.decision_authority)
col2.metric("Family activation authority", runtime.family_activation_authority)

st.subheader("Governed Edge Library")
st.dataframe(pd.DataFrame(runtime.edge_library), use_container_width=True, hide_index=True)

st.subheader("IV vs forecast-RV research diagnostics")
if runtime.observations:
    rows = []
    for item in runtime.observations:
        gap = item.variance_gap or {}
        rows.append(
            {
                "underlying": item.underlying,
                "state": item.state,
                "returns": item.return_count,
                "forecast_model": item.forecast_model_id,
                "matched_expiration": item.matched_expiration,
                "matched_dte": item.matched_dte,
                "surface_median_iv": item.surface_median_iv,
                "forecast_ann_vol": gap.get("forecast_volatility_annualized"),
                "variance_gap": gap.get("variance_gap_annualized"),
                "normalized_gap": gap.get("normalized_gap"),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.info("No runtime observations are available yet.")

st.caption(
    "These diagnostics are descriptive only. A positive IV-minus-forecast-RV gap is not, by itself, "
    "a tradable edge or evidence that short volatility is correctly compensated."
)

st.divider()
st.subheader("Bounded-risk structure sandbox")
st.caption(
    "Manual assumption-conditioned distribution analysis. The expected P&L below depends on the drift, "
    "volatility and jump assumptions you enter; it is not a forecast or trade recommendation."
)

c1, c2, c3, c4 = st.columns(4)
spot = c1.number_input("Spot", min_value=0.01, value=100.0, step=1.0)
dte = c2.number_input("DTE", min_value=0, max_value=3650, value=30, step=1)
annual_drift = c3.number_input("Assumed annual drift", value=0.00, step=0.01, format="%.4f")
annual_vol = c4.number_input("Assumed annual vol", min_value=0.0, value=0.20, step=0.01, format="%.4f")

st.markdown("**Two-leg vertical example**")
l1, l2 = st.columns(2)
with l1:
    long_right = st.selectbox("Long leg right", ["CALL", "PUT"], index=0)
    long_strike = st.number_input("Long strike", min_value=0.01, value=100.0, step=1.0)
    long_premium = st.number_input("Long premium", min_value=0.0, value=6.0, step=0.25)
with l2:
    short_right = st.selectbox("Short leg right", ["CALL", "PUT"], index=0)
    short_strike = st.number_input("Short strike", min_value=0.01, value=110.0, step=1.0)
    short_premium = st.number_input("Short premium", min_value=0.0, value=2.0, step=0.25)

b1, b2, b3, b4 = st.columns(4)
bankroll = b1.number_input("Bankroll", min_value=1.0, value=500.0, step=25.0)
max_loss_fraction = b2.number_input("Max loss fraction", min_value=0.001, max_value=1.0, value=0.02, step=0.005, format="%.3f")
transaction_costs = b3.number_input("Transaction costs", min_value=0.0, value=0.0, step=0.10)
slippage = b4.number_input("Slippage", min_value=0.0, value=0.0, step=0.10)

j1, j2, j3 = st.columns(3)
jump_intensity = j1.number_input("Annual jump intensity", min_value=0.0, value=0.0, step=0.25)
jump_mean = j2.number_input("Mean log jump", value=0.0, step=0.01, format="%.4f")
jump_vol = j3.number_input("Jump volatility", min_value=0.0, value=0.0, step=0.01, format="%.4f")

if st.button("Evaluate bounded-risk structure", type="primary"):
    legs = [
        OptionLeg(long_right, float(long_strike), 1, float(long_premium)),
        OptionLeg(short_right, float(short_strike), -1, float(short_premium)),
    ]
    result = evaluate_structure_distribution(
        legs,
        spot=float(spot),
        time_to_expiry=float(dte) / 365.0,
        assumptions=DistributionAssumptions(
            annual_drift=float(annual_drift),
            annual_volatility=float(annual_vol),
            jump_intensity=float(jump_intensity),
            jump_mean=float(jump_mean),
            jump_volatility=float(jump_vol),
        ),
        transaction_costs=float(transaction_costs),
        slippage=float(slippage),
        risk_budget=RiskBudget(
            bankroll=float(bankroll),
            max_loss_fraction=float(max_loss_fraction),
        ),
        simulation_paths=100_000,
        seed=4242,
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Expected P&L", f"{result.expected_pnl:.4f}")
    m2.metric("Max loss", "unbounded" if result.max_loss is None else f"{result.max_loss:.4f}")
    m3.metric("CVaR 95% loss", f"{result.loss_cvar_95:.4f}")
    m4.metric("P(profit)", f"{100 * result.probability_of_profit:.2f}%")

    st.write(
        {
            "defined_risk": result.structure_defined_risk,
            "budget_state": result.budget_state,
            "max_contracts_at_budget": result.max_contracts_at_budget,
            "expected_pnl_to_max_loss": result.expected_pnl_to_max_loss,
            "expected_pnl_to_cvar95": result.expected_pnl_to_cvar95,
            "probability_of_bankroll_ruin": result.probability_of_bankroll_ruin,
            "decision_authority": result.decision_authority,
        }
    )
    st.dataframe(
        pd.DataFrame(
            [
                {"percentile": "P05", "pnl": result.pnl_p05},
                {"percentile": "P25", "pnl": result.pnl_p25},
                {"percentile": "P50", "pnl": result.pnl_p50},
                {"percentile": "P75", "pnl": result.pnl_p75},
                {"percentile": "P95", "pnl": result.pnl_p95},
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
