from __future__ import annotations

import streamlit as st

from src.research.forecast_surface_runtime_v1 import load_forecast_surface_runtime


st.set_page_config(
    page_title="Christiania — Forecasting & Surface Intelligence",
    page_icon="📐",
    layout="wide",
)

st.title("Christiania — Forecasting & Surface Intelligence")
st.caption(
    "Rolling-origin volatility forecasts and observational surface-model comparison. "
    "Research-only: no model promotion or trading authority."
)

with st.sidebar:
    st.subheader("Research settings")
    train_window = st.number_input("Training window (session returns)", min_value=30, max_value=252, value=40, step=5)
    horizon_days = st.number_input("Forecast horizon (sessions)", min_value=1, max_value=30, value=5, step=1)
    limit_underlyings = st.number_input("Underlying limit", min_value=1, max_value=26, value=8, step=1)
    bootstrap_samples = st.number_input("Bootstrap samples", min_value=50, max_value=5000, value=500, step=50)

if st.button("Refresh intelligence", type="primary"):
    st.rerun()

state = load_forecast_surface_runtime(
    train_window=int(train_window),
    horizon_days=int(horizon_days),
    limit_underlyings=int(limit_underlyings),
    bootstrap_samples=int(bootstrap_samples),
)

if state.state == "RESEARCH_COMPARISONS_AVAILABLE":
    st.success(state.state)
elif state.state == "ACCUMULATING_EVIDENCE":
    st.info(state.state)
else:
    st.warning(state.state)

st.metric("Decision authority", state.decision_authority)

st.subheader("Rolling-origin variance forecast tournaments")
if not state.underlying_forecasts:
    st.info("No session-price history is available for forecast evaluation yet.")
else:
    summary_rows = []
    for item in state.underlying_forecasts:
        winner = None
        model_count = 0
        winner_margin = None
        if item.tournament:
            winner = item.tournament.get("winner")
            model_count = item.tournament.get("comparable_model_count") or 0
            winner_margin = item.tournament.get("winner_margin")
        summary_rows.append(
            {
                "underlying": item.underlying,
                "state": item.state,
                "session_prices": item.session_price_count,
                "returns": item.return_count,
                "models": model_count,
                "winner": winner,
                "winner_margin": winner_margin,
                "detail": item.detail,
            }
        )
    st.dataframe(summary_rows, use_container_width=True, hide_index=True)

    for item in state.underlying_forecasts:
        if not item.tournament:
            continue
        with st.expander(f"{item.underlying} forecast tournament"):
            st.write(f"**Scoring rule:** {item.tournament.get('scoring_rule')}")
            st.write(f"**Ranking:** {' → '.join(item.tournament.get('ranking') or [])}")
            st.dataframe(item.tournament.get("summaries") or [], use_container_width=True, hide_index=True)

st.divider()
st.subheader("Surface challenger tournament")
surface = state.surface
meta1, meta2, meta3, meta4 = st.columns(4)
meta1.metric("State", surface.state)
meta2.metric("Research run", surface.research_run_id or "n/a")
meta3.metric("Underlying", surface.underlying or "n/a")
meta4.metric("Surface points", surface.point_count)
st.caption(
    f"Expiration: {surface.expiration or 'n/a'} · Right: {surface.right or 'n/a'} · {surface.detail}"
)

if surface.tournament:
    result = surface.tournament
    m1, m2, m3, m4 = st.columns(4)
    incumbent_mae = result.get("incumbent_mae")
    challenger_mae = result.get("challenger_mae")
    win_rate = result.get("challenger_win_rate")
    sign_agreement = result.get("sign_agreement_rate")
    m1.metric("Incumbent MAE", "n/a" if incumbent_mae is None else f"{incumbent_mae:.6f}")
    m2.metric("Challenger MAE", "n/a" if challenger_mae is None else f"{challenger_mae:.6f}")
    m3.metric("Challenger win rate", "n/a" if win_rate is None else f"{win_rate:.1%}")
    m4.metric("Residual sign agreement", "n/a" if sign_agreement is None else f"{sign_agreement:.1%}")
    st.write(f"**Promotion state:** `{result.get('promotion_state')}`")
    st.write(result.get("promotion_detail") or "")
    with st.expander("Surface point diagnostics"):
        st.dataframe(result.get("observations") or [], use_container_width=True, hide_index=True)
else:
    st.info("Surface comparison is still accumulating evidence.")

st.divider()
st.caption(
    "Forecast rankings are descriptive research evidence. They do not activate a hypothesis family, "
    "promote a challenger, enable p-values/FDR, or authorize an option trade."
)
