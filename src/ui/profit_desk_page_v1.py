"""Profit-first Christiania front door. No duplicate research dashboards.

Data is reused from the existing indexed Trade Ideas read-model until the
unified ranker has prospective candidates. Its old scores are diagnostics,
NOT actionable trades. No tables by default; bounded drill-down only.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import streamlit as st

from src.decision.operator_profit_desk_v1 import (
    build_trading_desk_state, load_underlying_source_coverage,
)
from src.decision.opportunity import rank_by_opportunity
from src.decision.unified_frozen_read_model_v1 import load_latest_frozen_book
from src.ui.components import section_heading
from src.ui.datetime_display import format_local_datetime
from src.ui.trade_ideas_page import (
    _cached_ideas, _cached_prior_noise, _db_cache_key,
)


@st.cache_data(ttl=120, show_spinner=False)
def _source_coverage(key: str, db_path):
    return load_underlying_source_coverage(db_path=db_path)


@st.cache_data(ttl=120, show_spinner=False)
def _current_frozen_book(key: str, db_path):
    return load_latest_frozen_book(db_path=db_path)


def _money(value: float | None) -> str:
    return "not established" if value is None else f"${value:,.2f}"


def _friendly_reason(value: str) -> str:
    return value.replace("_", " ").capitalize()


def render_profit_desk_page(db_path=None) -> None:  # pragma: no cover - AppTest exercised
    """Use one named Streamlit fragment, short cards and one strong verdict."""
    key = _db_cache_key(db_path)

    @st.fragment
    def _show() -> None:
        section_heading(
            "Trade Desk",
            "One objective: rank opportunities by realistic net return after costs, "
            "risk and independent evidence. Doing nothing is always an option.",
        )
        try:
            ideas, errors, session = _cached_ideas(key, db_path)
            proposal_ids = tuple(int(x.proposal_id) for x in ideas)
            noise = _cached_prior_noise(key, proposal_ids, db_path)
            pairs = rank_by_opportunity(ideas, prior_noise_by_proposal=noise)
        except (sqlite3.Error, OSError, ValueError) as exc:
            st.error(
                "UNAVAILABLE — trading evidence cannot be verified. "
                "Christiania will not display an actionable trade."
            )
            st.caption(f"Read-model failure: {type(exc).__name__}.")
            return

        # The immutable v38 multi-strategy decision book is the ONLY source
        # of reviewed options candidates; legacy butterflies stay diagnostics.
        try:
            book = _current_frozen_book(key, db_path)
        except (sqlite3.Error, OSError, ValueError, KeyError):
            st.error(
                "NO TRADE — the authoritative prospective decision book "
                "is unavailable or failed integrity checks."
            )
            return
        desk = build_trading_desk_state(
            pairs, latest_session=session, authoritative=book.decision,
            authoritative_latest_snapshot_at=book.latest_snapshot_at,
        )
        st.caption(
            f"Frozen cross-strategy decisions: {book.records}; "
            f"latest decision run: {book.last_run_id or 'none'}. "
            "Model-only evidence cannot confer trading authority."
        )
        if desk.promotable_trades:
            st.warning(desk.verdict + " — broker re-quote required")
        else:
            st.warning(desk.verdict)
        st.write(desk.explanation)

        try:
            coverage = _source_coverage(key, db_path)
        except (sqlite3.Error, OSError, ValueError):
            coverage = None
            st.warning("Independent stock-price coverage could not be verified.")

        a, b, c, d = st.columns(4)
        a.metric("Trades clearing the complete gate", desk.promotable_trades)
        b.metric(
            "Prospective decisions recorded",
            "Unverified" if coverage is None
            else coverage.prospective_decisions_frozen,
        )
        c.metric(
            "Snapshots assessed for trade selection",
            "Unverified" if coverage is None else coverage.capture_attempts,
        )
        d.metric(
            "Qualified source prices",
            "Unverified" if coverage is None
            else f"{coverage.independent_fresh_prices}/{coverage.sampled_snapshots}",
        )
        if coverage is not None and coverage.state == "NO_INDEPENDENT_STOCK_PRICES":
            st.warning(
                "No qualifying independent stock-price observations in the "
                "latest research run. Selection evidence is incomplete."
            )
        if coverage is not None and coverage.capture_failures:
            st.error(
                f"{coverage.capture_failures} new unified selection capture "
                "attempt(s) failed. No trading permission is inferred."
            )
        if coverage is not None and coverage.rejected_reasons:
            with st.expander("Why stock observations failed the evidence gate"):
                for reason, count in coverage.rejected_reasons[:6]:
                    st.write(f"{_friendly_reason(reason)}: {count:,} snapshot(s)")
                st.caption(
                    "Diagnostics describe recorded provider evidence, not "
                    "forecast edge or realized option-trading performance."
                )

        session_text = session or "not recorded"
        source = (
            format_local_datetime(desk.latest_snapshot_at)
            if desk.latest_snapshot_at else "none"
        )
        st.caption(
            f"Last completed research session: {session_text} · "
            f"Last proposal snapshot: {source} · "
            "No live broker order or independent positive expectancy has been established."
        )

        section_heading(
            "Why aren't there profitable trades to show?",
            "These are the largest evidence and economic blockers, not hidden opportunities.",
        )
        problems = desk.no_trade_reasons[:5]
        for code, count in problems:
            col_l, col_r = st.columns([7, 1])
            col_l.write(_friendly_reason(code))
            col_r.markdown(f"**{count:,}**")

        if desk.ranked_candidates:
            section_heading(
                "Ranked candidates",
                "Model-screened only; manual broker re-quote is mandatory.",
            )
            for proposed in desk.ranked_candidates[:5]:
                with st.container(border=True):
                    st.markdown(
                        f"**#{proposed.rank} · {proposed.underlying} · "
                        f"{proposed.strategy_id} · {proposed.expiration}**"
                    )
                    x, y, z = st.columns(3)
                    x.metric(
                        "Conservative model net EV (USD)",
                        _money(proposed.conservative_net_ev_usd),
                    )
                    y.metric(
                        "Modeled downside incl. assumed costs (USD)",
                        _money(proposed.assumed_worst_loss_usd),
                    )
                    z.metric(
                        "Independent models confirming / opposing",
                        f"{proposed.confirming_model_groups} / "
                        f"{proposed.opposing_model_groups}",
                    )
                    st.caption(
                        "Hypothetical ranking only, not a verified achievable "
                        "profit or executable broker quote. Final manual re-quote required."
                    )

        if desk.legacy_near_misses:
            with st.expander(
                "Historical model-screened structures (not trade suggestions)"
            ):
                st.caption(
                    "The old butterfly scanner did not test independent "
                    "strategies or independently calibrated returns."
                )
                item = desk.legacy_near_misses[0]
                with st.container(border=True):
                    left, right = st.columns([4, 2])
                    with left:
                        st.markdown(
                            f"**{item.underlying} · {item.structure.replace('_', ' ').title()}**"
                        )
                        st.caption(
                            f"Expires {item.expiration} · "
                            f"{_friendly_reason(item.reason)}"
                        )
                    with right:
                        st.metric(
                            "Modeled price gap after costs",
                            _money(item.model_net_edge_usd),
                        )
                    st.caption(
                        "Not forecast net P&L. Maximum theoretical loss "
                        f"(USD, includes modeled fees): {_money(item.proposed_max_loss_usd)}. "
                        "Not an executable broker quote."
                    )

        if errors:
            with st.expander(f"Data that could not be assessed ({len(errors)})"):
                for pid, message in errors[:10]:
                    st.caption(f"Proposal {pid}: {message[:180]}")
                if len(errors) > 10:
                    st.caption(f"{len(errors)-10} further unscorable proposals.")

        with st.expander("What must happen before a trade can appear?"):
            st.markdown(
                "A candidate must clear the same source, timestamp, contract, "
                "liquidity, cost, downside and calibrated forecast tests as "
                "every other option structure. Independent models can reject it. "
                "Its estimated net return must exceed doing nothing and comparable "
                "structures. After that it still requires a broker re-quote and "
                "manual decision. Christiania does not place orders."
            )

    _show()


def render_performance_page(snapshot: dict) -> None:
    """A short accountability page; no proxies disguised as win rates."""
    section_heading(
        "Performance",
        "The scoreboard is money after costs, versus NO TRADE and matched controls.",
    )
    expiry = snapshot.get("shadow_expiry_outcomes") or {}
    resolved = int(expiry.get("resolved") or 0)
    unresolved = int(expiry.get("unresolved") or 0)
    distinct_dates = int(expiry.get("resolved_expiration_dates") or 0)
    st.warning(
        "PROFITABILITY NOT PROVEN. Neither research payoffs nor model-estimated "
        "expiry returns are realised brokerage profits."
    )
    x, y, z = st.columns(3)
    x.metric("Qualified modeled expiry outcomes", resolved)
    y.metric("Unresolved expiry outcomes", unresolved)
    z.metric("Independent priced expiry dates", distinct_dates)

    section_heading(
        "Money made by following Christiania",
        "Broker-confirmed net P&L, after all fees and slippage.",
    )
    st.metric("Verified realized net profit", "Not available")
    st.caption(
        "There is no verified broker execution ledger in this view. "
        "Never substitute ThetaData model-based expiry proxies or duplicate "
        "paper candidates for investable returns."
    )
    with st.expander("What evidence do we currently have?"):
        st.write(
            f"{resolved} candidate-level modeled expiry result(s) have qualifying "
            f"underlying observations across {distinct_dates} expiry dates. "
            "These are not independently filled positions or a portfolio. "
            "A validated strategy edge requires prospective cohorts, realistic "
            "exit prices and matched controls; win rates across correlated "
            "candidate copies are misleading."
        )
        st.write(
            "Retrospective provider-model payoffs belong to a separate, "
            "unvalidated evidence tier and do not count as confirmed trades."
        )
