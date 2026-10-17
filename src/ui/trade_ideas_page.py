"""Trade Ideas page: every proposed trade with each model's verdict side by side.

Pure formatting helpers (``ideas_to_rows`` etc.) are separated from the
Streamlit rendering so they can be unit tested.
"""
from __future__ import annotations

import os
import sqlite3
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
        return "Not tracked yet"
    if idea.admission_decision == "ADMITTED":
        return "Being tracked"
    return f"Not tracked: {(idea.admission_reason or 'unspecified').replace('_', ' ').lower()}"


def ideas_to_rows(ideas: Sequence[TradeIdea]) -> list[dict[str, Any]]:
    rows = []
    for idea in ideas:
        row: dict[str, Any] = {
            "Stock": idea.underlying,
            "Trade": structure_label(idea),
            "Expires": f"{idea.expiration} ({idea.dte}d)" if idea.dte is not None else idea.expiration,
        }
        for model_id in MODEL_ORDER:
            row[MODEL_LABELS[model_id]] = verdict_cell(idea.judgements[model_id])
        row["Models that see edge"] = f"{idea.favouring} of {len(MODEL_ORDER)}"
        row["Most you can lose"] = usd(idea.max_loss_usd)
        row["Most you can make"] = usd(idea.profile.max_profit_usd) if idea.profile else "—"
        row["Status"] = status_text(idea)
        rows.append(row)
    return rows


def evidence_banner(records: dict[str, ModelRecord], resolved_total: int) -> tuple[str, str]:
    """(tone, text). Says what has actually been tested, nothing more."""
    if resolved_total == 0:
        return (
            "warning",
            "Not proven yet. No trade has reached its expiry date, so none of these models has a track record. "
            "Treat every ✓ as an idea to check, not a result.",
        )
    judged = sum(r.n_favoured for r in records.values())
    if judged == 0:
        return (
            "info",
            f"{resolved_total} trade(s) have expired, but no model had picked any of them in advance, "
            "so their picks are still untested.",
        )
    return (
        "info",
        f"{resolved_total} trade(s) have expired. The table at the bottom shows how each model's picks did. "
        "Few trades means wide uncertainty.",
    )


def record_rows(records: dict[str, ModelRecord]) -> list[dict[str, Any]]:
    rows = []
    for model_id in MODEL_ORDER:
        r = records[model_id]
        if r.n_favoured == 0:
            hit, mean = "—", "—"
        else:
            lo, hi = r.hit_rate_ci
            hit = f"{r.hit_rate * 100:.0f}% (range {lo * 100:.0f}–{hi * 100:.0f}%)"
            mean = usd(r.mean_net_pnl_usd, signed=True)
            if r.mean_ci is not None:
                mean += f"  (range {usd(r.mean_ci[0], signed=True)} to {usd(r.mean_ci[1], signed=True)})"
        rows.append({
            "Model": MODEL_LABELS[model_id],
            "Expired trades it could judge": r.n_scored,
            "Trades it picked": r.n_favoured,
            "Made money": r.wins,
            "Win rate": hit,
            "Average result": mean,
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
            "Trades the system found, and what each of three independent models says about them.",
        )
        ideas, errors, session_date = _cached_ideas(key, db_path)
        try:
            records, resolved_total = _cached_records(key, db_path)
        except sqlite3.OperationalError as exc:
            records, resolved_total = None, 0
            st.error(
                "The track record could not be read because the database schema is out of date "
                f"({exc}). Run the database migrations, then reload."
            )
        else:
            tone, text = evidence_banner(records, resolved_total)
            (st.warning if tone == "warning" else st.info)(text)

        if not ideas:
            st.info(
                "No trade ideas right now"
                + (f" (latest session {session_date})." if session_date else ".")
                + " They appear when the system spots a mispriced option and builds a limited-risk trade around it."
            )
            if errors:
                st.caption(f"{len(errors)} idea(s) could not be scored.")
            return

        as_of = max((i.as_of for i in ideas if i.as_of), default=None)
        agree2 = sum(1 for i in ideas if i.favouring >= 2)
        st.caption(
            f"{len(ideas)} ideas · {agree2} where at least 2 models see an edge"
            + (f" · market data from {format_local_datetime(as_of)}" if as_of else "")
        )

        min_models = st.select_slider(
            "Only show trades where this many models see an edge",
            options=[0, 1, 2, 3], value=2, key="ideas_min_models",
            help="An edge means: worth more than its price according to the model, after the bid/ask spread and fees.",
        )
        shown = [i for i in ideas if i.favouring >= min_models]
        if not shown:
            st.info("No trade meets this filter. Lower the number to see every idea.")
        else:
            rows = ideas_to_rows(shown)
            event = st.dataframe(
                pd.DataFrame(rows), hide_index=True, width="stretch",
                on_select="rerun", selection_mode="single-row", key="ideas_table",
                column_config={
                    MODEL_LABELS[m]: st.column_config.TextColumn(
                        help="✓ edge after costs · ≈ small edge, costs eat it · ✗ model says it is worth less than "
                             "its price · n/a model could not judge. The dollar figure is the expected gain after costs.")
                    for m in MODEL_ORDER
                },
            )
            st.caption("Click a row for details.")
            selected = None
            try:
                picked = event.selection.rows
                if picked:
                    selected = shown[int(picked[0])]
            except (AttributeError, IndexError, TypeError):
                selected = None
            _detail(selected or shown[0], alt, pd, st)

        if errors:
            with st.expander(f"{len(errors)} idea(s) could not be scored"):
                for proposal_id, message in errors:
                    st.caption(f"Idea {proposal_id}: {message}")

        if records is not None:
            st.markdown("#### Has it worked so far?")
            st.dataframe(pd.DataFrame(record_rows(records)), hide_index=True, width="stretch")
        with st.expander("How to read this page"):
            st.markdown(
                "- Each model estimates what the option's volatility *should* be. If that makes the trade worth "
                "more than its price, even after the bid/ask spread and fees, it shows ✓ and the dollar gain.\n"
                "- The three models look at the same option prices in different ways. When they agree it is "
                "a stronger hint, but it is not proof.\n"
                "- The gain is what the model expects **if it is right**. Prices can also differ from the model "
                "for good reasons, and with many options scanned some will look good by chance.\n"
                "- Only the table above is evidence, and only once trades have expired.\n"
                "- Nothing here places an order or is advice."
            )

    _page()


def _detail(idea: TradeIdea, alt, pd, st) -> None:  # pragma: no cover - rendering
    st.markdown(f"#### {idea.underlying} · {structure_label(idea)} · expires {idea.expiration}")
    st.markdown(md(_summary(idea)))
    cols = st.columns(len(MODEL_ORDER))
    for col, model_id in zip(cols, MODEL_ORDER, strict=True):
        j = idea.judgements[model_id]
        with col:
            st.markdown(f"**{MODEL_LABELS[model_id]}**")
            if not j.available:
                st.caption(j.reason or "Could not judge this trade.")
                continue
            st.metric(_verdict_words(j), usd(j.net_edge_usd, signed=True, decimals=2),
                      help="Expected gain after the bid/ask spread and fees, if the model is right.")
            fair = j.fair_iv_by_strike.get(idea.target_strike)
            market = next((l.market_iv for l in idea.legs if l.strike == idea.target_strike), None)
            if fair is not None and market is not None:
                st.caption(f"Volatility at {idea.target_strike:g}: model {fair * 100:.1f}%, market {market * 100:.1f}%.")
            st.caption(md(
                f"Before costs {usd(j.gross_edge_usd, signed=True, decimals=2)}, "
                f"spread −{usd(j.spread_cost_usd, decimals=2)}, fees −{usd(j.fees_usd, decimals=2)}."
            ))

    if idea.profile is not None and idea.legs and idea.spot:
        em = idea.profile.expected_move_1sd
        lo = min(idea.strikes[0], idea.spot) - 2 * em
        hi = max(idea.strikes[-1], idea.spot) + 2 * em
        curve = pd.DataFrame(payoff_curve(idea.legs, idea.fees_usd or 0.0, max(lo, 0.01), hi),
                             columns=["Price at expiry", "Profit / loss ($)"])
        x_title, y_title = "Price of the stock at expiry", "Profit / loss ($)"
        x_scale = alt.Scale(domain=[max(lo, 0.01), hi], zero=False, nice=False)
        line = alt.Chart(curve).mark_line(color="#2EC4D6").encode(
            x=alt.X("Price at expiry:Q", scale=x_scale, title=x_title),
            y=alt.Y("Profit / loss ($):Q", title=y_title),
        )
        zero = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(
            color="#8FA3B5", strokeDash=[4, 4]).encode(y=alt.Y("y:Q", title=y_title))
        spot = alt.Chart(pd.DataFrame({"x": [idea.spot]})).mark_rule(
            color="#E9B44C", strokeDash=[2, 2], strokeWidth=2).encode(
            x=alt.X("x:Q", scale=x_scale, title=x_title))
        st.altair_chart(line + zero + spot, width="stretch")
        st.caption(f"Yellow line = current price {eu(idea.spot, 2)}. Costs are included.")

    with st.expander("The individual options"):
        legs = pd.DataFrame([{
            "Action": l.side, "Contracts": l.quantity, "Strike": l.strike,
            "Type": "Call" if l.right.upper().startswith("C") else "Put",
            "Bid": l.bid, "Ask": l.ask, "Price used": l.entry_price,
        } for l in idea.legs])
        st.dataframe(legs, hide_index=True, width="stretch")
    for note in idea.notes:
        st.caption(f"Note: {note}")


def _verdict_words(j: ModelJudgement) -> str:
    if j.verdict == VERDICT_EDGE:
        return "Sees an edge"
    if j.verdict == VERDICT_COSTS_EAT_EDGE:
        return "Edge too small"
    return "Sees no edge"


def _summary(idea: TradeIdea) -> str:
    n = len(MODEL_ORDER)
    if idea.available == 0:
        head = "No model could judge this trade."
    elif idea.favouring == 0:
        head = "No model sees an edge after costs."
    else:
        head = f"{idea.favouring} of {n} models see an edge after costs."
    if idea.profile is None:
        return head
    zone = zone_text(idea)
    return (
        f"{head} You risk at most {usd(idea.max_loss_usd)} to make at most {usd(idea.profile.max_profit_usd)}. "
        f"It makes money if the stock ends {zone.replace('–', 'to')} at expiry "
        f"(about {idea.profile.p_profit * 100:.0f}% likely on a simple price-movement assumption)."
    )
