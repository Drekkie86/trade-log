"""Plain-language home pages: Results ("is it working?") and System ("is it running?").

Every sentence here is written for a non-expert. Verdict logic lives in pure
functions so it can be tested without Streamlit.
"""
from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from src.ui.components import section_heading
from src.ui.datetime_display import format_local_datetime

# Below these, a win rate is noise. Deliberately conservative.
MIN_RESOLVED_BETS = 30
MIN_EXPIRY_DATES = 5


def num(value: Any, decimals: int = 0) -> str:
    """Belgian-style number: 12.345,67."""
    if value is None:
        return "—"
    try:
        text = f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def eur_from_minor(value: Any, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    amount = float(value) / 100.0
    sign = "+" if signed and amount > 0 else "-" if amount < 0 else ""
    return f"{sign}€{num(abs(amount), 2)}"


def banner(tone: str, headline: str, detail: str = "") -> None:
    """One big answer at the top of a page. tone: good | warn | bad."""
    colors = {"good": "#52D987", "warn": "#E9B44C", "bad": "#F0645A"}
    color = colors.get(tone, colors["warn"])
    detail_html = (
        f'<div style="margin-top:.35rem;color:#C9D6DF;font-size:.95rem">{escape(detail)}</div>'
        if detail
        else ""
    )
    st.markdown(
        f'<div style="border:1px solid {color};border-left:6px solid {color};'
        'border-radius:10px;padding:1rem 1.2rem;margin:.2rem 0 1.1rem;'
        'background:rgba(5,29,43,.92)">'
        f'<div style="font-size:1.45rem;font-family:Georgia,serif;color:{color}">{escape(headline)}</div>'
        f"{detail_html}</div>",
        unsafe_allow_html=True,
    )


def status_row(label: str, ok: bool | None, text: str) -> None:
    mark = {True: ("✔", "#52D987"), False: ("✖", "#F0645A"), None: ("•", "#E9B44C")}[ok]
    st.markdown(
        '<div style="display:flex;gap:.8rem;padding:.55rem .2rem;'
        'border-bottom:1px solid rgba(255,255,255,.06);align-items:baseline;flex-wrap:wrap">'
        f'<span style="color:{mark[1]};font-size:1.1rem;width:1.2rem">{mark[0]}</span>'
        f'<strong style="min-width:9rem;color:#F4F0E7">{escape(label)}</strong>'
        f'<span style="color:#C9D6DF">{escape(text)}</span></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------- results ---
def results_verdict(expiry: dict[str, Any]) -> tuple[str, str, str]:
    """(tone, headline, detail) — candidate-level replay, never live proof."""
    resolved = int(expiry.get("resolved", 0) or 0)
    dates = int(expiry.get("resolved_expiration_dates", 0) or 0)
    if resolved == 0:
        return (
            "warn",
            "No resolved expiry outcomes yet.",
            "Some candidates may have expired without usable terminal-price evidence. "
            "There is not yet a resolved outcome to evaluate.",
        )
    if resolved < MIN_RESOLVED_BETS or dates < MIN_EXPIRY_DATES:
        return (
            "warn",
            "Too early to tell.",
            f"{num(resolved)} resolved candidate outcome(s) on {num(dates)} expiry date(s). "
            "Repeated observations may represent the same trade idea, so these are not "
            "independent bets or evidence of a statistically validated win rate.",
        )
    total = expiry.get("total_net_eur_minor")
    if total is not None and float(total) < 0:
        return (
            "bad",
            "Negative candidate replay so far.",
            f"{num(resolved)} resolved candidate outcomes sum to {eur_from_minor(total, signed=True)} "
            "after assumed costs. Correlated entries may be counted repeatedly; "
            "this is not a portfolio result or permission to trade live.",
        )
    return (
        "warn",
        "Positive candidate replay, not proven.",
        f"{num(resolved)} resolved candidate outcomes sum to {eur_from_minor(total, signed=True)} "
        "after assumed costs. Repeated trade ideas can inflate this sum; "
        "it is not an independent-bet or investable return estimate.",
    )


def _score_panel() -> None:
    """Does the 'worth a look' score beat random strikes? Fail-soft before migration 037."""
    import sqlite3

    from src.decision.opportunity_evidence import STATE_EVIDENCE, evaluate
    from src.research.opportunity_pipeline import load_evidence_rows

    section_heading("Does the 'worth a look' score work?")
    try:
        report = evaluate(load_evidence_rows())
    except (sqlite3.Error, OSError):
        st.info("Not available until the database is updated.")
        return
    (st.success if report.state == STATE_EVIDENCE else st.warning)(report.headline)
    if report.primary_signal_mean_net_usd is not None:
        st.caption(
            f"Average net per selected trade: ${report.primary_signal_mean_net_usd:+,.2f}; "
            f"matched random-strike trade: ${report.primary_placebo_mean_net_usd:+,.2f}. "
            "Paper estimates after assumed costs, not brokerage fills."
        )
    if report.primary_excess_usd is not None:
        lo, hi = report.primary_ci_usd or (None, None)
        st.caption(
            f"{report.primary_bets} finished 'worth a look' trades on {report.primary_expiry_dates} expiry dates. "
            f"Average versus random strikes: ${report.primary_excess_usd:+,.2f}"
            + (f" (range ${lo:+,.2f} to ${hi:+,.2f})." if lo is not None else ".")
        )


def render_results_page(snapshot: dict[str, Any]) -> None:
    expiry = snapshot.get("shadow_expiry_outcomes", {}) or {}
    counts = snapshot.get("research_counts", {}) or {}
    prospective = snapshot.get("prospective", {}) or {}

    section_heading("Results", "Is this making money on paper? Paper only: no real orders are ever placed.")
    tone, headline, detail = results_verdict(expiry)
    banner(tone, headline, detail)

    resolved = int(expiry.get("resolved", 0) or 0)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ideas found", num(counts.get("surfaced_total", 0)))
    c2.metric("Recorded paper candidates", num(counts.get("shadow_candidates", 0)))
    c3.metric("Resolved outcomes", num(resolved), f"{num(expiry.get('unresolved', 0))} unresolved", delta_color="off")
    c4.metric("Market-data days", num(counts.get("market_snapshot_days", 0)),
              "distinct stored market sessions", delta_color="off")
    st.caption(
        "Market-data days include historical and recovered snapshots. "
        f"Prospective research evidence spans {num(prospective.get('independent_dates', 0))} "
        "independent session day(s); those are a separate, narrower population "
        "and cannot be increased by historical backfills."
    )

    if resolved:
        section_heading("Resolved candidate outcomes — not independent bets")
        wins, losses, flat = (int(expiry.get(k, 0) or 0) for k in ("wins", "losses", "flat"))
        r1, r2, r3 = st.columns(3)
        r1.metric("Won / lost / flat", f"{num(wins)} / {num(losses)} / {num(flat)}")
        r2.metric("Sum of candidate estimates", eur_from_minor(expiry.get("total_net_eur_minor"), signed=True), "not portfolio P&L", delta_color="off")
        r3.metric("Average per candidate", eur_from_minor(expiry.get("mean_net_eur_minor"), signed=True))

    _score_panel()

    with st.expander("What do these numbers mean?"):
        st.markdown(
            "- **Ideas found**: unusual prices the scanner spotted.\n"
            "- **Recorded paper candidates**: all stored candidate entries, including closed ones.\n"
            "- **Resolved outcomes**: candidate entries with a modelled expiry result, "
            "not independent bets. Multiple entries may refer to the same underlying idea.\n"
            "- **Market-data days**: distinct US session dates with stored market snapshots, "
            "including historical and recovered observations. This is not a count of "
            "independent prospective results.\n\n"
            "Results use stored prices and assumed costs. They are not real profits or "
            "a deduplicated portfolio, and candidates without usable evidence are not counted as wins."
        )


# ----------------------------------------------------------------- system ---
def system_checks(
    snapshot: dict[str, Any], theta: dict[str, Any], backups: dict[str, Any],
    saxo: dict[str, Any] | None = None,
) -> list[tuple[str, bool | None, str]]:
    """Plain rows: (label, ok, sentence). ok=None means unknown."""
    rows: list[tuple[str, bool | None, str]] = []

    daemon = snapshot.get("daemon_health", {}) or {}
    state = str(daemon.get("state") or "UNKNOWN")
    if state == "HEALTHY":
        rows.append(("Collector", True, "Running. It reported in within the last 3 minutes."))
    elif state == "STALE_DAEMON_LEASE":
        rows.append(("Collector", False, "Stopped reporting. It may have crashed or be stuck."))
    elif state == "NO_DAEMON_LEASE":
        rows.append(("Collector", False, "Not running. No sign of it on this database."))
    else:
        rows.append(("Collector", False, "Status is damaged or unreadable."))

    tstate = str(theta.get("state") or "UNKNOWN")
    if tstate == "NOT_PROBED":
        rows.append(("Market data", None, "Not checked on this screen."))
    elif theta.get("ready"):
        rows.append(("Market data", True, "Theta Terminal is answering."))
    else:
        rows.append(("Market data", False, "Theta Terminal is not answering. No new prices will arrive."))

    db = snapshot.get("database", {}) or {}
    if db.get("schema_version") is None or db.get("expected_schema_version") is None:
        rows.append(("Database", None, "Database schema version was not checked."))
    elif db.get("schema_version") != db.get("expected_schema_version"):
        rows.append(("Database", False, "Schema version does not match the expected release."))
    elif db.get("quick_check") == "ok":
        rows.append(("Database", True, "Schema current; SQLite quick check passed."))
    elif db.get("quick_check") is None:
        rows.append(("Database", None, "Schema current; SQLite integrity was not checked here."))
    else:
        rows.append(("Database", False, "SQLite quick check reported an error."))

    age = backups.get("latest_valid_age_hours")
    if backups.get("total_files", 0) == 0 and age is None:
        rows.append(("Backups", None, "Not checked on this screen."))
    elif age is None:
        rows.append(("Backups", False, "No valid backup found."))
    elif float(age) > 36:
        rows.append(("Backups", False, f"Last indexed backup is {num(age, 0)} hours old; verify a fresh recovery."))
    else:
        rows.append(("Backups", True, f"Last indexed backup is {num(age, 0)} hours old; full restore not checked here."))

    latest = snapshot.get("latest_iteration")
    if latest:
        status = str(latest.get("status") or "unknown").replace("_", " ").lower()
        rows.append(
            ("Last collection", status == "completed",
             f"{status.capitalize()} at {format_local_datetime(latest.get('scheduled_for'))}.")
        )
    else:
        rows.append(("Last collection", None, "No collection recorded yet."))

    if saxo is not None:
        state = str(saxo.get("state") or "PROBE_FAILED")
        if saxo.get("auth_ok") is True:
            rows.append((
                "Saxo LIVE", True,
                "Read-only OAuth connection works. No orders can be placed.",
            ))
        elif state == "NOT_CONFIGURED":
            rows.append((
                "Saxo LIVE", None,
                "Not connected. Set up Saxo LIVE OAuth on an authorized device.",
            ))
        elif state == "LOGIN_REQUIRED":
            rows.append((
                "Saxo LIVE", False,
                "Interactive login is required; refresh credentials are missing or expired.",
            ))
        else:
            rows.append((
                "Saxo LIVE", False,
                str(saxo.get("detail") or "Saxo connection check failed."),
            ))
        option_access = saxo.get("stock_option_eligible")
        if option_access is False:
            rows.append((
                "Saxo options eligibility", False,
                "StockOption is not listed among permitted asset types.",
            ))
        elif option_access is True:
            rows.append((
                "Saxo options eligibility", True,
                "StockOption is permitted, but trade and quote access remain unverified.",
            ))
        else:
            rows.append((
                "Saxo options eligibility", None,
                "Options eligibility has not been confirmed by Saxo.",
            ))
        quote_state = str(saxo.get("quote_state") or "UNVERIFIED_STOCK_AND_OPRA_QUOTES")
        if quote_state == "TERMS_NOT_ACCEPTED":
            rows.append((
                "Saxo market data", False,
                "OpenAPI market-data terms have not been accepted.",
            ))
        else:
            rows.append((
                "Saxo market data", None,
                "Real-time US stock and OPRA option quotes are not yet verified.",
            ))
    return rows


def system_verdict(rows: list[tuple[str, bool | None, str]]) -> tuple[str, str, str]:
    bad = [label for label, ok, _ in rows if ok is False]
    if bad:
        return ("bad", "Something needs attention.", "Problem: " + ", ".join(bad) + ".")
    unknown = [label for label, ok, _ in rows if ok is None]
    if unknown:
        return ("warn", "Running, with some checks skipped.", "Not checked: " + ", ".join(unknown) + ".")
    return ("good", "Everything is running.", "")


def render_system_page(
    snapshot: dict[str, Any], theta: dict[str, Any], backups: dict[str, Any],
    saxo: dict[str, Any] | None = None,
) -> None:
    section_heading("System", "Is the machine collecting data?")
    rows = system_checks(snapshot, theta, backups, saxo=saxo)
    banner(*system_verdict(rows))
    for label, ok, text in rows:
        status_row(label, ok, text)

    clock = snapshot.get("market_clock", {}) or {}
    open_now = str(clock.get("state") or "").upper() == "ACTIVE_SAMPLE_WINDOW"
    st.markdown("")
    st.caption(
        ("Collecting now. " if open_now else "Not collecting right now (market closed). ")
        + f"Next collection: {format_local_datetime(clock.get('next_sample_at'))}."
    )
