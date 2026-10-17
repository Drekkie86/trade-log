"""Trade Ideas page: every proposed trade with each model's verdict side by side.

Pure formatting helpers (``ideas_to_rows`` etc.) are separated from the
Streamlit rendering so they can be unit tested.
"""
from __future__ import annotations

import os
from typing import Any, Sequence

import streamlit as st

from src.decision.trade_ideas import (
    MODEL_LABELS,
    MODEL_ORDER,
    VERDICT_AGAINST,
    VERDICT_COSTS_EAT_EDGE,
    VERDICT_EDGE,
    ModelJudgement,
    ModelRecord,
    TradeIdea,
    load_current_ideas,
    model_track_record,
    payoff_curve,
)

# --------------------------------------------------------------------------
# Formatting (Belgian convention: 12.345,67)
# --------------------------------------------------------------------------
def eu(value: float, decimals: int = 0) -> str:
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def usd(value: float | None, *, signed: bool = False, decimals: int = 0) -> str:
    if value is None:
        return "—"
    sign = "+" if signed and value > 0 else ("−" if value < 0 else "")
    return f"{sign}${eu(abs(value), decimals)}"


def md(text: str) -> str:
    """Escape dollar signs so Streamlit markdown does not typeset them as LaTeX."""
    return text.replace("$", "\\$")


def structure_label(idea: TradeIdea) -> str:
    sid = (idea.structure_id or "").upper()
    kind = "Reverse fly" if "REVERSE" in sid else "Long fly" if "LONG" in sid else (idea.structure_id or "Structure")
    strikes = "/".join(f"{k:g}" for k in idea.strikes)
    return f"{kind} {strikes} {'call' if idea.right.upper().startswith('C') else 'put'}"


def verdict_cell(j: ModelJudgement) -> str:
    if not j.available:
        return "n/a"
    net = usd(j.net_edge_usd, signed=True)
    if j.verdict == VERDICT_EDGE:
        return f"✓ {net}"
    if j.verdict == VERDICT_COSTS_EAT_EDGE:
        return f"≈ {net}"
    if j.verdict == VERDICT_AGAINST:
        return f"✗ {net}"
    return "n/a"


def zone_text(idea: TradeIdea) -> str:
    if idea.profile is None or not idea.profile.profit_intervals:
        return "—"
    parts = []
    for lo, hi in idea.profile.profit_intervals:
        if lo is None:
            parts.append(f"< {eu(hi, 2)}")
        elif hi is None:
            parts.append(f"> {eu(lo, 2)}")
        else:
            parts.append(f"{eu(lo, 2)} – {eu(hi, 2)}")
    return "  |  ".join(parts)


def status_text(idea: TradeIdea) -> str:
    if idea.admission_decision is None:
        return "Not yet decided"
    if idea.admission_decision == "ADMITTED":
        return "Shadow-tracked"
    return f"Blocked: {(idea.admission_reason or 'unspecified').replace('_', ' ').lower()}"


def ideas_to_rows(ideas: Sequence[TradeIdea]) -> list[dict[str, Any]]:
    rows = []
    for idea in ideas:
        row: dict[str, Any] = {
            "Underlying": idea.underlying,
            "Trade": structure_label(idea),
            "Expiry": f"{idea.expiration} ({idea.dte}d)" if idea.dte is not None else idea.expiration,
        }
        for model_id in MODEL_ORDER:
            row[MODEL_LABELS[model_id]] = verdict_cell(idea.judgements[model_id])
        row["Models seeing edge"] = f"{idea.favouring}/{len(MODEL_ORDER)}"
        row["Profit-zone odds*"] = (
            f"{idea.profile.p_profit * 100:.0f}%" if idea.profile is not None else "—"
        )
        row["Max loss (USD)"] = usd(idea.max_loss_usd)
        row["Max profit (USD)"] = usd(idea.profile.max_profit_usd) if idea.profile else "—"
        row["Status"] = status_text(idea)
        row["Profit zone at expiry"] = zone_text(idea)
        rows.append(row)
    return rows


def evidence_banner(records: dict[str, ModelRecord], resolved_total: int) -> tuple[str, str]:
    """(tone, text). Describes what has actually been tested, nothing more."""
    if resolved_total == 0:
        return (
            "warning",
            "No trade has been tested against a real expiry yet, so none of the models below has a track record. "
            "Read every verdict as a hypothesis, not a result.",
        )
    judged = sum(r.n_favoured for r in records.values())
    if judged == 0:
        return (
            "info",
            f"{resolved_total} trade(s) have resolved, but none was one the models favoured at entry, "
            "so the models' calls are still untested.",
        )
    return (
        "info",
        f"{resolved_total} trade(s) have resolved at expiry. Each model's record below counts only the trades "
        "that model favoured at entry. Small samples carry wide uncertainty; the intervals are shown, not hidden.",
    )


def record_rows(records: dict[str, ModelRecord]) -> list[dict[str, Any]]:
    rows = []
    for model_id in MODEL_ORDER:
        r = records[model_id]
        if r.n_favoured == 0:
            hit, mean = "—", "—"
        else:
            lo, hi = r.hit_rate_ci
            hit = f"{r.hit_rate * 100:.0f}% ({lo * 100:.0f}–{hi * 100:.0f}%)"
            mean = usd(r.mean_net_pnl_usd, signed=True)
            if r.mean_ci is not None:
                mean += f"  ({usd(r.mean_ci[0], signed=True)} to {usd(r.mean_ci[1], signed=True)})"
        rows.append({
            "Model": MODEL_LABELS[model_id],
            "Resolved trades it could judge": r.n_scored,
            "…of which it saw edge": r.n_favoured,
            "Made money": r.wins,
            "Hit rate (95% interval)": hit,
            "Mean net P&L per trade": mean,
        })
    return rows


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def _db_cache_key(db_path) -> str:
    from src.database.repository_impl import resolve_db_path

    path = resolve_db_path(db_path)
    try:
        return f"{path}:{os.stat(path).st_mtime_ns}"
    except OSError:
        return str(path)


@st.cache_data(ttl=120, show_spinner="Scoring proposed trades with each model…")
def _cached_ideas(key: str, db_path):
    return load_current_ideas(db_path=db_path)


@st.cache_data(ttl=600, show_spinner="Checking each model against resolved expiries…")
def _cached_records(key: str, db_path):
    return model_track_record(db_path=db_path)


def render_trade_ideas_page(db_path=None) -> None:  # pragma: no cover - exercised by AppTest
    import altair as alt
    import pandas as pd

    from src.ui.components import section_heading
    from src.ui.datetime_display import format_local_datetime

    key = _db_cache_key(db_path)

    @st.fragment
    def _page() -> None:
        section_heading(
            "Trade Ideas",
            "Every proposed trade, with what each model says about it. Models are judged separately and never blended.",
        )
        ideas, errors, session_date = _cached_ideas(key, db_path)
        records, resolved_total = _cached_records(key, db_path)

        tone, text = evidence_banner(records, resolved_total)
        (st.warning if tone == "warning" else st.info)(text)

        if not ideas:
            st.info(
                "No proposed trades in the latest research session"
                + (f" ({session_date})." if session_date else ".")
                + " Proposals appear when the daemon surfaces a local IV anomaly and builds a defined-risk structure."
            )
            if errors:
                st.caption(f"{len(errors)} proposal(s) could not be scored.")
            return

        as_of = max((i.as_of for i in ideas if i.as_of), default=None)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Session", session_date or "—")
        m2.metric("Trades scored", len(ideas))
        m3.metric("2+ models see edge", sum(1 for i in ideas if i.favouring >= 2))
        m4.metric("Resolved at expiry", resolved_total)
        if as_of:
            st.caption(f"Newest market data in this view: {format_local_datetime(as_of)}.")

        f1, f2 = st.columns([2, 3])
        min_models = f1.select_slider(
            "Show trades where at least this many models see edge after costs",
            options=[0, 1, 2, 3], value=2, key="ideas_min_models",
        )
        names = sorted({i.underlying for i in ideas})
        chosen = f2.multiselect("Underlyings", names, default=[], key="ideas_underlyings",
                                placeholder="All")
        shown = [i for i in ideas if i.favouring >= min_models and (not chosen or i.underlying in chosen)]
        if not shown:
            st.info("No trade meets this filter. Lower the number of models required to see every scored trade.")
        else:
            rows = ideas_to_rows(shown)
            event = st.dataframe(
                pd.DataFrame(rows), hide_index=True, width="stretch",
                on_select="rerun", selection_mode="single-row", key="ideas_table",
                column_config={
                    "Profit-zone odds*": st.column_config.TextColumn(
                        help="Risk-neutral lognormal probability, at the at-the-money IV, that the underlying "
                             "finishes inside the profit zone. An intuition aid about shape, not a forecast."),
                    **{
                        MODEL_LABELS[m]: st.column_config.TextColumn(
                            help="✓ edge after spread and fees · ≈ edge exists but costs eat it · ✗ model thinks "
                                 "the position is worth less than the market · n/a model could not judge. "
                                 "Dollar figure = model value minus market value minus costs.")
                        for m in MODEL_ORDER
                    },
                },
            )
            selected = None
            try:
                picked = event.selection.rows
                if picked:
                    selected = shown[int(picked[0])]
            except (AttributeError, IndexError, TypeError):
                selected = None
            _detail(selected or shown[0], alt, pd, st)

        if errors:
            with st.expander(f"{len(errors)} proposal(s) could not be scored"):
                for proposal_id, message in errors:
                    st.caption(f"Proposal {proposal_id}: {message}")

        st.markdown("#### Track record")
        st.caption(
            "How each model's calls actually turned out, from trades resolved at expiry. A call counts only if the "
            "model saw edge after costs at entry. This is the evidence; the verdicts above are not."
        )
        st.dataframe(pd.DataFrame(record_rows(records)), hide_index=True, width="stretch")
        with st.expander("How to read this page"):
            st.markdown(
                "- **Each model re-prices the structure** at its own fair implied volatility and compares with the "
                "market's. The dollar figure is that difference, minus crossing the bid/ask spread, minus fees.\n"
                "- **V1 chord** and **V2 quadratic** fit a line / parabola through neighbouring strikes. "
                "**SVI smile** fits one smooth curve through the whole expiry. They are different views of the same "
                "chain, so agreement is informative but not independent proof.\n"
                "- **Profit-zone odds** describe the shape of the trade under a standard lognormal assumption. "
                "They say nothing about whether the models are right.\n"
                "- **Resolved at expiry** uses the last sampled price of the expiry session, not the official "
                "settlement, and stops 15 minutes before the close.\n"
                "- Christiania places no orders. Nothing here is a recommendation."
            )

    _page()


def _detail(idea: TradeIdea, alt, pd, st) -> None:  # pragma: no cover - rendering
    st.markdown(f"#### {idea.underlying} · {structure_label(idea)} · expires {idea.expiration}")
    cols = st.columns(len(MODEL_ORDER))
    for col, model_id in zip(cols, MODEL_ORDER, strict=True):
        j = idea.judgements[model_id]
        with col:
            st.markdown(f"**{MODEL_LABELS[model_id]}**")
            if not j.available:
                st.caption(j.reason or "Unavailable.")
                continue
            fair = j.fair_iv_by_strike.get(idea.target_strike)
            market = next((l.market_iv for l in idea.legs if l.strike == idea.target_strike), None)
            if fair is not None and market is not None:
                st.caption(f"Fair IV at {idea.target_strike:g}: {fair * 100:.1f}% vs market {market * 100:.1f}%")
            st.metric("Net edge after costs", usd(j.net_edge_usd, signed=True, decimals=2),
                      f"{(j.net_edge_to_max_loss or 0) * 100:+.0f}% of max loss", delta_color="off")
            st.caption(md(
                f"Model vs market {usd(j.gross_edge_usd, signed=True, decimals=2)} · "
                f"spread −{usd(j.spread_cost_usd, decimals=2)} · fees −{usd(j.fees_usd, decimals=2)}"
            ))

    if idea.profile is not None and idea.legs and idea.spot:
        em = idea.profile.expected_move_1sd
        lo = min(idea.strikes[0], idea.spot) - 2 * em
        hi = max(idea.strikes[-1], idea.spot) + 2 * em
        curve = pd.DataFrame(payoff_curve(idea.legs, idea.fees_usd or 0.0, max(lo, 0.01), hi),
                             columns=["Underlying at expiry", "P&L (USD)"])
        x_title, y_title = "Underlying at expiry", "P&L (USD)"
        x_scale = alt.Scale(domain=[max(lo, 0.01), hi], zero=False, nice=False)
        line = alt.Chart(curve).mark_line(color="#2EC4D6").encode(
            x=alt.X("Underlying at expiry:Q", scale=x_scale, title=x_title),
            y=alt.Y("P&L (USD):Q", title=y_title),
        )
        zero = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(
            color="#8FA3B5", strokeDash=[4, 4]).encode(y=alt.Y("y:Q", title=y_title))
        spot = alt.Chart(pd.DataFrame({"x": [idea.spot]})).mark_rule(
            color="#E9B44C", strokeDash=[2, 2], strokeWidth=2).encode(
            x=alt.X("x:Q", scale=x_scale, title=x_title))
        st.altair_chart(line + zero + spot, width="stretch")
        st.caption(
            f"Expiry P&L after entry cost and fees. Amber dashed line = spot {eu(idea.spot, 2)}. "
            f"One standard move to expiry ≈ ±{eu(em, 2)} at {idea.profile.atm_iv * 100:.1f}% IV."
        )

    legs = pd.DataFrame([{
        "Side": l.side, "Qty": l.quantity, "Strike": l.strike, "Right": l.right,
        "Bid": l.bid, "Ask": l.ask, "Entry price": l.entry_price, "Market IV": f"{l.market_iv * 100:.1f}%",
    } for l in idea.legs])
    st.dataframe(legs, hide_index=True, width="stretch")
    for note in idea.notes:
        st.caption(f"Note: {note}")
