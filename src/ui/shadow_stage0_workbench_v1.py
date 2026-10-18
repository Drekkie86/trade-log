"""Visible Stage-0 hypothetical strategy workbench for the main Shadow Lab.

No broker calls, trade authority, DB writes or model admissions.
Inputs and quote timestamps are expressly synthetic, not market evidence.
"""
from __future__ import annotations

from dataclasses import replace as _scenario_replace
from decimal import Decimal as _StageDecimal

import pandas as pd
import streamlit as st

from src.research.strategy_falsification_v1 import (
    CATALOGUE as _stage_catalogue, evaluate as _stage_evaluate,
)
from src.research.shadow_stage0_scenarios_v1 import hypothetical_scenario as _stage_scenario


def render_shadow_stage0_workbench() -> None:
    """Render a visible scenario workbench without advancing shadow states."""
    st.subheader("Strategy falsification — Stage 0")
    st.caption(
        "Explore all 11 strategy families under explicit HYPOTHETICAL quotes and costs. "
        "Nothing here is a broker quote, verified fill, forecast, positive expectancy, "
        "approved trade or recorded Shadow Lab outcome."
    )


    with st.expander("Open the 11-strategy scenario workbench", expanded=True):
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
            "They are not fetched from ThetaData or Saxo. You choose the capital allocation; "
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
            bankroll_allocated_eur = st.number_input(
                "Capital allocated to Christiania (€)", min_value=0.0,
                value=0.0, step=50.0, key="stage0_allocated_capital_eur",
            )
            a, b, c, d = st.columns(4)
            assumed_fee = a.number_input("Option fee, USD/contract/side", 0.0, 1000.0, 3.0, 0.5)
            assumed_slippage = b.number_input("Additional round-trip costs, USD", 0.0, 1000.0, 1.0, 0.5)
            assumed_tax = c.number_input("Tax assumption, USD", 0.0, 1000.0, 1.0, 0.5)
            assumed_fx = d.number_input("Assumed USD per EUR", 0.01, 10.0, 1.10, 0.01)
            submitted = st.form_submit_button("Evaluate synthetic feasibility")
        if submitted:
            assumptions = _scenario_replace(
                default_policy,
                bankroll_eur=_StageDecimal(str(bankroll_allocated_eur)),
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
            m4.metric("Your allocation (EUR)", f"{bankroll_allocated_eur:,.2f}")
            st.write("**Rejection / uncertainty reasons:**",
                     list(evaluated.get("reasons") or ()) or ["None for these assumed inputs; execution still unverified"])
            st.caption(
                "Hypothetical expiry payoff and costs only. Bid/ask sizes, FX, timestamps "
                "and fees were assumed. No broker strategy fill, live quote entitlement, "
                "forward holdout performance or independent receipt is established."
            )
