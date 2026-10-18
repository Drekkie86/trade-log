"""Trade Ideas page: every proposed trade with each model's verdict side by side.

Pure formatting helpers (``ideas_to_rows`` etc.) are separated from the
Streamlit rendering so they can be unit tested.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Any, Sequence

import streamlit as st

from src.decision.opportunity import (
    VERDICT_MARGINAL,
    VERDICT_SKIP,
    VERDICT_WORTH,
    OpportunityAssessment,
    rank_by_opportunity,
)
from src.decision.opportunity_evidence import STATE_EVIDENCE, EvidenceReport, evaluate
from src.research.opportunity_pipeline import load_evidence_rows
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
    # An old proposal must not appear as an actionable current candidate.
    try:
        if date.fromisoformat(idea.expiration) < datetime.now(
            ZoneInfo("America/New_York")
        ).date():
            return "Expired — historical proposal"
    except ValueError:
        return "Expiry unavailable"
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
            "Expires": (
                f"{date.fromisoformat(idea.expiration):%d %b %Y}"
                + (f" · {idea.dte} DTE at quote" if idea.dte is not None else "")
            ),
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
            "Not proven yet. No usable resolved expiry outcome is available for this retrospective replay. "
            "Treat every ✓ as an idea to check, not a result. The three models read the same prices, so they "
            "often agree even when the apparent mispricing is only noise.",
        )
    judged = sum(r.n_favoured for r in records.values())
    if judged == 0:
        return (
            "info",
            f"{resolved_total} distinct trades have resolved expiry outcomes, but none had a positive "
            "model-implied difference in the retrospective replay. No prospective picks are proven.",
        )
    return (
        "info",
        f"{resolved_total} distinct trades have resolved expiry outcomes. The table below replays models "
        "using historical entry quotes; these were not necessarily predictions recorded at the time. "
        "Few trades mean wide uncertainty.",
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


@st.cache_data(ttl=600, show_spinner="Checking the score against random strikes…")
def _cached_evidence(key: str, db_path):
    return evaluate(load_evidence_rows(db_path=db_path))


VERDICT_BADGE = {
    VERDICT_WORTH: "● Worth a look",
    VERDICT_MARGINAL: "◐ Marginal",
    VERDICT_SKIP: "○ Skip",
}
FILTERS = {
    "Worth a look": (VERDICT_WORTH,),
    "Worth a look + marginal": (VERDICT_WORTH, VERDICT_MARGINAL),
    "Everything": (VERDICT_WORTH, VERDICT_MARGINAL, VERDICT_SKIP),
}


def opportunity_rows(pairs: Sequence[tuple[TradeIdea, OpportunityAssessment]]) -> list[dict[str, Any]]:
    rows = []
    for idea, a in pairs:
        rows.append({
            "Verdict": VERDICT_BADGE[a.verdict],
            "Stock": idea.underlying,
            "Trade": structure_label(idea),
            "Expires": f"{date.fromisoformat(idea.expiration):%d %b %Y}"
                       + (f" · {idea.dte}d" if idea.dte is not None else ""),
            "Why": a.headline,
            "Edge after costs": usd(a.net_edge_usd, signed=True) if a.net_edge_usd is not None else "—",
            "Most you can lose": usd(idea.max_loss_usd),
            "Most you can make": usd(idea.profile.max_profit_usd) if idea.profile else "—",
            "Status": status_text(idea),
        })
    return rows


def score_banner(report: EvidenceReport | None) -> tuple[str, str]:
    """(tone, text) for the one question that matters: has the score beaten chance?"""
    if report is None:
        return ("warning", "Score evidence is unavailable until the database is updated. "
                           "Treat every verdict as a suggestion to look, not a result.")
    if report.state == STATE_EVIDENCE:
        return ("success", report.headline)
    return (
        "warning",
        f"Not proven yet. {report.headline} A verdict is a suggestion to look, never a result. "
        "No order is ever placed.",
    )


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
            "Each idea gets one verdict: is the price gap clearly bigger than costs and quote noise?",
        )
        ideas, errors, session_date = _cached_ideas(key, db_path)
        try:
            report = _cached_evidence(key, db_path)
        except sqlite3.OperationalError:
            report = None
        tone, text = score_banner(report)
        {"success": st.success, "warning": st.warning}[tone](text)

        if not ideas:
            st.info(
                "No trade ideas right now"
                + (f" (latest session {session_date})." if session_date else ".")
                + " They appear when the system spots a mispriced option and builds a limited-risk trade around it."
            )
            if errors:
                st.caption(f"{len(errors)} idea(s) could not be scored.")
            return

        try:
            today_ny = datetime.now(ZoneInfo("America/New_York")).date()
            age_days = (today_ny - date.fromisoformat(session_date)).days if session_date else 0
        except ValueError:
            age_days = 0
        if age_days >= 3:
            st.warning(
                f"These ideas come from the {session_date} market session, "
                "not current quotes. Review as historical observations only."
            )

        pairs = rank_by_opportunity(ideas)
        counts = {v: sum(1 for _, a in pairs if a.verdict == v) for v in VERDICT_BADGE}
        as_of = max((i.as_of for i in ideas if i.as_of), default=None)
        c1, c2, c3 = st.columns(3)
        c1.metric("Worth a look", counts[VERDICT_WORTH])
        c2.metric("Marginal", counts[VERDICT_MARGINAL])
        c3.metric("Skip", counts[VERDICT_SKIP])
        if as_of:
            st.caption(f"Market data from {format_local_datetime(as_of)}.")

        choice = st.radio(
            "Show", list(FILTERS), index=2, horizontal=True, key="ideas_filter",
            help="Worth a look: the edge after costs is at least twice the noise in the quotes. "
                 "Marginal: positive after costs but between one and two times the noise.",
        )
        shown = [(i, a) for i, a in pairs if a.verdict in FILTERS[choice]]
        if not shown:
            st.info("Nothing meets this filter. Choose a wider one to see every idea.")
        else:
            event = st.dataframe(
                pd.DataFrame(opportunity_rows(shown)), hide_index=True, width="stretch",
                on_select="rerun", selection_mode="single-row", key="ideas_table",
            )
            st.caption("Click a row for details. Dollar figures are model values after estimated costs, not forecasts.")
            selected = None
            try:
                picked = event.selection.rows
                if picked:
                    selected = shown[int(picked[0])]
            except (AttributeError, IndexError, TypeError):
                selected = None
            idea, assessment = selected or shown[0]
            _detail(idea, assessment, report, alt, pd, st)

        if errors:
            with st.expander(f"{len(errors)} idea(s) could not be scored"):
                for proposal_id, message in errors:
                    st.caption(f"Idea {proposal_id}: {message}")

        if report is not None and report.buckets:
            with st.expander("Is the score working? (finished trades vs random strikes)"):
                st.markdown(md(_evidence_text(report)))
                st.dataframe(pd.DataFrame(_bucket_rows(report)), hide_index=True, width="stretch")
        try:
            records, resolved_total = _cached_records(key, db_path)
        except sqlite3.OperationalError:
            records, resolved_total = None, 0
        if records is not None:
            with st.expander("Older check: the three models replayed on expired trades"):
                tone2, text2 = evidence_banner(records, resolved_total)
                (st.warning if tone2 == "warning" else st.info)(text2)
                st.dataframe(pd.DataFrame(record_rows(records)), hide_index=True, width="stretch")
        with st.expander("How to read this page"):
            st.markdown(
                "- **The verdict** compares the price gap (what the models think the option is worth versus its "
                "quote) with two things: what it costs to trade and how noisy the quotes are. Noise comes from "
                "the bid/ask width of the quotes behind the estimate, plus disagreement between the three models.\n"
                "- **Worth a look** means the edge after costs is at least twice that noise. It does *not* mean "
                "the trade will make money. Prices can differ for good reasons, and with many options scanned "
                "some will look good by chance.\n"
                "- **Is it working?** Every idea is logged with its verdict before the outcome is known, next to a "
                "random-strike twin of the same shape. Only if 'worth a look' ideas beat their twins by more "
                "than chance, over enough expiry dates, does the banner above say so.\n"
                "- The three models read the same prices, so they often agree even when the gap is noise; "
                "that is why agreement is not part of the verdict.\n"
                "- Nothing here places an order or is advice."
            )

    _page()


def _evidence_text(report: EvidenceReport) -> str:
    lines = [report.headline]
    if report.primary_signal_mean_net_usd is not None:
        lines.append(
            f"- Selected trades average {usd(report.primary_signal_mean_net_usd, signed=True)} "
            f"net; matched random-strike twins average "
            f"{usd(report.primary_placebo_mean_net_usd, signed=True)} net. "
            "Both are paper estimates after assumed costs."
        )
    if report.primary_excess_usd is not None:
        lines.append(
            f"- 'Worth a look' trades finished: {report.primary_bets} on {report.primary_expiry_dates} "
            f"expiry dates. Average result versus the random-strike twin: {usd(report.primary_excess_usd, signed=True)}"
            + (f" (range {usd(report.primary_ci_usd[0], signed=True)} to {usd(report.primary_ci_usd[1], signed=True)})"
               if report.primary_ci_usd else "")
            + "."
        )
    if report.placebo_mean_net_usd is not None:
        lines.append(f"- Random-strike twins average {usd(report.placebo_mean_net_usd, signed=True)} "
                     "(about the cost of trading, as expected if strike choice is random).")
    if report.bets_without_placebo:
        lines.append(f"- {report.bets_without_placebo} trade(s) had no eligible twin and are not compared.")
    return "\n".join(lines)


def _bucket_rows(report: EvidenceReport) -> list[dict[str, Any]]:
    rows = []
    for b in report.buckets:
        rows.append({
            "Verdict": VERDICT_BADGE.get(b.verdict, b.verdict),
            "Finished trades": b.bets,
            "Expiry dates": b.expiry_dates,
            "Average result": usd(b.mean_net_usd, signed=True),
            "Random-strike twin": usd(b.mean_placebo_net_usd, signed=True),
            "Difference": usd(b.mean_excess_usd, signed=True),
        })
    return rows


def _sigma_total(a: OpportunityAssessment) -> float | None:
    if a.sigma_quote_vol_pts is None or a.sigma_model_vol_pts is None:
        return None
    return (a.sigma_quote_vol_pts ** 2 + a.sigma_model_vol_pts ** 2) ** 0.5


def _detail(idea: TradeIdea, a: OpportunityAssessment, report, alt, pd, st) -> None:  # pragma: no cover - rendering
    st.markdown(f"#### {idea.underlying} · {structure_label(idea)} · expires {idea.expiration}")
    st.markdown(f"**{VERDICT_BADGE[a.verdict]}.** {a.headline}")
    if idea.profile is not None:
        st.markdown(md(
            f"You risk at most {usd(idea.max_loss_usd)} to make at most {usd(idea.profile.max_profit_usd)}. "
            f"At expiry it is positive if the stock ends {zone_text(idea).replace('–', 'to')}."
        ))
    c1, c2, c3 = st.columns(3)
    c1.metric("Edge after costs", usd(a.net_edge_usd, signed=True, decimals=2) if a.net_edge_usd is not None else "—",
              help="Model value minus the half-spread and fees. A valuation gap, not a forecast of profit.")
    c2.metric("Noise in the quotes",
              f"±{_sigma_total(a):.1f} vol pts" if _sigma_total(a) is not None else "—",
              help="How far the quotes could be off just from bid/ask width, plus disagreement between models.")
    c3.metric("Price gap",
              f"{a.residual_vol_pts:+.1f} vol pts" if a.residual_vol_pts is not None else "—",
              help="Model volatility minus market volatility at the centre strike.")
    if a.fair_iv is not None and a.market_iv is not None:
        st.caption(f"Volatility at {idea.target_strike:g}: models say {a.fair_iv * 100:.1f}%, market says {a.market_iv * 100:.1f}%.")
    if a.score is not None:
        st.caption(f"Score {a.score:.1f} (edge after costs ÷ noise). Worth a look needs 2.0, marginal 1.0.")
    st.caption(f"{a.models_favouring} of {a.models_available} models see an edge. They read the same prices, so this is not independent confirmation.")

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
        f"The expiry payoff is positive if the stock ends {zone.replace('–', 'to')} "
        f"(a {idea.profile.p_profit * 100:.0f}% risk-neutral model probability, "
        "not an observed or real-world success rate)."
    )
