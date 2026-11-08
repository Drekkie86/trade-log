"""Christiania screens: Today's trades, 0DTE, Track record and System.

Everything shown comes from the engine's frozen scans, picks and the trades the
operator recorded. The UI never computes or changes a recommendation; the only
things it writes are the operator's own trades and a live re-price request.
"""
from __future__ import annotations

import math
import os
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from html import escape
from typing import Any

import streamlit as st

from src.engine.chains import NY, parse_utc
from src.engine.ledger import (
    close_trade, exposure, latest_scan, load_backtest_summary, picks_with_outcomes,
    record_trade, scorecard, session_picks, trades_with_closes, verdict,
)
from src.engine.pipeline import LANE_MAIN, LANE_ZERO_DTE
from src.engine.structures import FAMILY_LABELS
from src.ui.design import (
    Col, bar, finite, html, line_svg, money, payoff_svg, percent, table, tone, usd,
)

REJECTION_LABELS = {
    "EV_TOO_SMALL": "expected profit too small after costs",
    "STRESS_EV_NEGATIVE": "loses money once a shock is allowed for",
    "RETURN_ON_RISK_TOO_LOW": "profit too small for the tail risk",
    "WIDE_SPREAD": "bid/ask spread too wide",
    "ONE_SIDED_QUOTE": "a leg has no two-sided quote",
    "NO_REAL_MARKET": "a leg's bid is below 0.05",
    "LOW_OPEN_INTEREST": "too little open interest",
    "STALE_QUOTE": "quotes too old",
    "QUOTE_AGE_UNKNOWN": "quote age unknown",
    "MODEL_UNAVAILABLE": "no smile, or less than a year of implied/realised history",
    "QUOTE_INCONSISTENT": "a leg's quote is off the smile (stale or crossed); not a fillable credit",
    "NO_USABLE_EXPIRY": "no usable expiry",
    "EVENT_BLACKOUT": "earnings before expiry (blackout list)",
    "MAX_LOSS_TOO_LARGE": "max loss above the per-lot limit",
    "NOT_A_CREDIT": "not a credit",
    "NO_RISK_ARBITRAGE_SUSPECT": "suspect quotes",
    "OPEN_POSITION": "a pick on this name is still open",
    "EXPIRED": "expired",
}
SHAPE_LABELS = {
    "PUT_CREDIT_SPREAD": "Put credit spread",
    "CALL_CREDIT_SPREAD": "Call credit spread",
    "IRON_CONDOR": "Iron condor",
    "IRON_FLY": "Iron fly",
}
STALE_SCAN_MINUTES = 30
EXIT_RULE = ("Expiry day: if the price is within 1% of a short strike at 15:30 New York, close "
             "the whole spread. US stock and ETF options are physically delivered; a short leg "
             "assigned while its hedge expires worthless leaves you with stock over the weekend.")


# --------------------------------------------------------------------- helpers
def ny_time(value: Any, fmt: str = "%a %d %b, %H:%M") -> str:
    stamp = parse_utc(value)
    if stamp is None:
        return "–"
    text = stamp.astimezone(NY).strftime(fmt)
    return text + " NY" if "%H" in fmt else text


def minutes_ago(value: Any, now: datetime) -> float | None:
    stamp = parse_utc(value)
    return None if stamp is None else (now - stamp).total_seconds() / 60.0


def days_to(expiration: str, today: date) -> int:
    return (date.fromisoformat(expiration) - today).days


def short_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d %b")


def contracts_for(max_loss: float, risk_budget: float | None) -> int | None:
    if not risk_budget or max_loss <= 0:
        return None
    return int(risk_budget // max_loss)


def limit_price(record: dict) -> float:
    """Net limit per share: the modelled fill, the worst price to accept."""
    return abs(float(record["entry_cash_usd"])) / 100.0


def shape(record: dict) -> str:
    return SHAPE_LABELS.get(record.get("shape"), FAMILY_LABELS.get(record.get("family"), ""))


def why_text(c: dict) -> str:
    parts = []
    ratio, n = c.get("premium_ratio"), c.get("premium_observations")
    if finite(c.get("atm_iv")):
        parts.append(f"The options price {percent(c['atm_iv'])}% volatility.")
    if finite(ratio) and finite(c.get("premium_implied_vol")) and finite(c.get("premium_realised_vol")):
        parts.append(
            f"Over the last {n} sessions {c['underlying']}'s options priced "
            f"{percent(c['premium_implied_vol'])}% and the stock realised "
            f"{percent(c['premium_realised_vol'])}%: {float(ratio):.0%} of the priced variance was "
            "delivered. The score prices this trade under the market's own smile shrunk to that "
            f"width: {usd(c.get('ev_usd'), signed=True)}. Under the smile as priced it pays "
            f"{usd(c.get('implied_ev_usd'), signed=True)}, which is about the costs."
        )
    if finite(c.get("stress_ev_usd")):
        parts.append(f"With the stress shock it pays {usd(c['stress_ev_usd'], signed=True)}.")
    return " ".join(parts)


def sigma_move(c: dict) -> float | None:
    """One real-world standard deviation to expiry: ATM vol scaled by sqrt(lambda)."""
    vol, days, ratio = c.get("atm_iv"), c.get("trading_days"), c.get("premium_ratio")
    if not (finite(vol) and finite(days)) or days <= 0:
        return None
    scale = math.sqrt(float(ratio)) if finite(ratio) and float(ratio) > 0 else 1.0
    return float(vol) * scale * math.sqrt(float(days) / 252.0)


def head(title: str, right: str = "", *, stale: bool = False) -> None:
    html(f'<div class="chr-head"><h1>{escape(title)}</h1>'
         f'<div class="fresh{" stale" if stale else ""}">{escape(right)}</div></div>')


def lede(text: str) -> None:
    html(f'<p class="chr-lede">{escape(text)}</p>')


def h2(text: str) -> None:
    html(f'<div class="chr-h2" role="heading" aria-level="2">{escape(text)}</div>')


def note(text: str, *, warn: bool = False) -> None:
    html(f'<p class="chr-note{" chr-warn" if warn else ""}">{escape(text)}</p>')


def verdict_line(kind: str, text: str) -> None:
    html(f'<p class="chr-verdict {kind}">{escape(text)}</p>')


def _db_key(db_path) -> str | None:
    return None if db_path is None else str(db_path)


def _engine_tables_missing(exc: Exception) -> bool:
    return "no such table" in str(exc).lower()


# ------------------------------------------------------------------------ reads
@st.cache_data(ttl=60, show_spinner=False)
def _read_scan(lane: str, db_key: str | None) -> dict | None:
    from src.operations.sqlite_runtime import open_readonly_connection

    conn = open_readonly_connection(db_key)
    try:
        return latest_scan(conn, lane)
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner=False)
def _read_session_picks(lane: str, session_date: str, db_key: str | None) -> list[dict]:
    from src.operations.sqlite_runtime import open_readonly_connection

    conn = open_readonly_connection(db_key)
    try:
        return session_picks(conn, lane, session_date)
    finally:
        conn.close()


@st.cache_data(ttl=120, show_spinner=False)
def _read_picks(db_key: str | None) -> list[dict]:
    from src.operations.sqlite_runtime import open_readonly_connection

    conn = open_readonly_connection(db_key)
    try:
        return picks_with_outcomes(conn)
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner=False)
def _read_trades(db_key: str | None) -> list[dict]:
    from src.operations.sqlite_runtime import open_readonly_connection

    conn = open_readonly_connection(db_key)
    try:
        return trades_with_closes(conn)
    finally:
        conn.close()


def read_trades_safe(db_path=None) -> list[dict]:
    try:
        return _read_trades(_db_key(db_path))
    except Exception:
        return []


def open_risk_cap() -> float:
    try:
        return float(os.environ.get("CHRISTIANIA_MAX_OPEN_RISK_USD", "0") or 0)
    except ValueError:
        return 0.0


# ------------------------------------------------------------------ trade table
def trade_columns(today: date, top_score: float) -> list[Col]:
    def trade_cell(c: dict) -> str:
        return (f'<span class="tick">{escape(c["underlying"])}</span> {escape(shape(c))}'
                f'<span class="sub">{escape(c["description"])}</span>')

    def expiry_cell(c: dict) -> str:
        d = days_to(c["expiration"], today)
        when = "today" if d == 0 else "tomorrow" if d == 1 else f"{d} days"
        return f'{short_date(c["expiration"])}<span class="sub">{when}</span>'

    return [
        Col("rank", "", "r", render=lambda c: str(c["_rank"]), css=lambda c: "rank"),
        Col("trade", "Trade", "l", render=trade_cell, cls="wide"),
        Col("expiry", "Expiry", "l", render=expiry_cell, cls="nw opt"),
        Col("cash", "Credit / debit", "r", group_start=True, cls="opt",
            render=lambda c: money(c["entry_cash_usd"], signed=True)),
        Col("risk", "Max loss", "r", cls="opt", render=lambda c: money(c["max_loss_usd"])),
        Col("ev", "Expected", "r",
            render=lambda c: money(c["ev_usd"], signed=True),
            css=lambda c: tone(c["ev_usd"])),
        Col("score", "Per $100 tail risk", "r", group_start=True, emphasis=True,
            render=lambda c: money(100 * float(c["score"]), signed=True, decimals=1)
            + bar(float(c["score"]), top_score, 3.0)),
        Col("pmax", "Max loss, %", "r", group_start=True, cls="opt",
            render=lambda c: percent(c.get("p_max_loss"))),
        Col("pop", "Win, %", "r", render=lambda c: percent(c.get("pop")), cls="opt"),
    ]


TRADE_GROUPS = [("", 3), ("Per lot, $", 3), ("Score", 1), ("Odds", 2)]


def near_miss_columns(today: date) -> list[Col]:
    return [
        Col("trade", "Trade", "l",
            render=lambda c: f'<span class="tick">{escape(c["underlying"])}</span> '
                             f'{escape(shape(c))}<span class="sub">{escape(c["description"])}</span>'),
        Col("expiry", "Expiry", "l",
            render=lambda c: f'{short_date(c["expiration"])}'
                             f'<span class="sub">{days_to(c["expiration"], today)} days</span>'),
        Col("ev", "Expected, $", "r", group_start=True,
            render=lambda c: money(c["ev_usd"], signed=True),
            css=lambda c: tone(c["ev_usd"])),
        Col("score", "Per $100 tail risk", "r",
            render=lambda c: money(100 * float(c["score"]), signed=True, decimals=1)
            if finite(c.get("score")) else "–"),
        Col("why", "Why it fails", "l", group_start=True,
            render=lambda c: escape(REJECTION_LABELS.get(c.get("reject_reason"), "")),
            css=lambda c: "muted"),
    ]


def legs_table(c: dict) -> str:
    rows = [
        {"action": "Buy" if leg["side"] > 0 else "Sell",
         "option": f"{leg['strike']:g} {'call' if leg['right'] == 'C' else 'put'}",
         "bid": leg["bid"], "ask": leg["ask"], "fill": leg["fill"]}
        for leg in sorted(c["legs"], key=lambda l: (l["strike"], l["right"]))
    ]
    cols = [
        Col("action", "Action", "l"),
        Col("option", f"{c['underlying']} {short_date(c['expiration'])}", "l"),
        Col("bid", "Bid", "r", render=lambda r: money(r["bid"], decimals=2)),
        Col("ask", "Ask", "r", render=lambda r: money(r["ask"], decimals=2)),
        Col("fill", "Fill", "r", render=lambda r: money(r["fill"], decimals=2)),
    ]
    return table(cols, rows)


def sensitivity_table(c: dict, config: dict) -> str:
    scores = c.get("scores", {})
    jump = float(config.get("stress_jump", -0.10))
    p_jump = float(config.get("stress_jump_prob", 0.03))
    ratio = c.get("premium_ratio")
    rows = []
    if "IMPLIED" in scores:
        rows.append({"view": "The market's smile as priced", "ev": scores["IMPLIED"].get("ev_usd"),
                     "pop": scores["IMPLIED"].get("pop"), "key": False})
    label = ("Smile shrunk to the delivered variance" if not finite(ratio)
             else f"Smile shrunk to {float(ratio):.0%} of priced variance (the score)")
    rows.append({"view": label, "ev": c.get("ev_usd"), "pop": c.get("pop"), "key": True})
    rows.append({"view": f"Stress: {p_jump:.0%} chance of a {jump:+.0%} shock",
                 "ev": c.get("stress_ev_usd"), "pop": None, "key": False})
    return table([
        Col("view", "Priced under", "l", render=lambda r: f'<span class="{"tick" if r["key"] else ""}">'
                                                       f'{escape(r["view"])}</span>'),
        Col("ev", "Expected, $", "r", render=lambda r: money(r["ev"], signed=True),
            css=lambda r: tone(r["ev"])),
        Col("pop", "Win, %", "r", render=lambda r: percent(r["pop"])),
    ], rows)


def _exposure_line(c: dict, trades: list[dict], today: date, cap: float, lots: int) -> None:
    ex = exposure(trades, today=today)
    added = float(c["max_loss_usd"]) * max(lots, 1)
    after = ex.after(added)
    text = (f"Open risk now {usd(ex.open_risk_usd)} in {ex.open_trades} trade"
            f"{'s' if ex.open_trades != 1 else ''}; after this trade {usd(after)}")
    if cap > 0:
        text += f"; cap {usd(cap)}"
    note(text + ".", warn=cap > 0 and after > cap)


def _took_it_form(c: dict, config: dict, trades: list[dict], today: date, cap: float,
                  risk_budget: float | None, db_path, pick_id: int | None) -> None:
    key = f"took_{c['structure_key']}"
    fit = contracts_for(float(c["max_loss_usd"]), risk_budget) or 1
    per_contract = float(config.get("cost", {}).get("commission_per_contract", 2.0))
    credit = float(c["entry_cash_usd"]) > 0
    with st.expander("I took this trade"):
        with st.form(key):
            lots = st.number_input("Lots", min_value=1, value=max(1, fit), step=1)
            fill = st.number_input(
                f"Fill per share ({'credit' if credit else 'debit'})", min_value=0.0,
                value=round(limit_price(c), 2), step=0.01, format="%.2f")
            commission = st.number_input(
                "Commission, $ (all legs, all lots)", min_value=0.0,
                value=round(per_contract * len(c["legs"]) * max(1, fit), 2), step=0.5, format="%.2f")
            text = st.text_input("Note", value="")
            submitted = st.form_submit_button("Record trade")
        if submitted:
            from src.database.repository import get_connection

            conn = get_connection(db_path)
            try:
                record_trade(conn, c, lots=int(lots), fill_per_share=(fill if credit else -fill),
                             commission_usd=float(commission), taken_at=datetime.now(UTC),
                             note=text or None, pick_id=pick_id)
            finally:
                conn.close()
            st.cache_data.clear()
            st.success("Recorded. It will settle at expiry with the picks, or close it on the "
                       "Track record page.")
    _exposure_line(c, trades, today, cap, fit)


def _reprice_block(c: dict, db_path) -> None:
    key = f"reprice_{c['structure_key']}"
    if st.button("Re-price on live quotes", key=key):
        from src.database.repository import get_connection
        from src.engine.reprice import reprice
        from src.providers.thetadata import ThetaDataClient

        client = ThetaDataClient(base_url=os.environ.get("CHRISTIANIA_THETA_BASE_URL",
                                                         "http://127.0.0.1:25503/v3"),
                                 timeout_seconds=30.0)
        conn = get_connection(db_path)
        try:
            with st.spinner("Pricing on the live chain…"):
                result = reprice(c, theta_client=client, conn=conn)
        except Exception as exc:
            result = None
            note(f"Re-pricing failed: {type(exc).__name__}. Is the Theta Terminal running?",
                 warn=True)
        finally:
            conn.close()
        if result is not None:
            if result.status != "OK" or result.candidate is None:
                note(f"Cannot re-price: {result.detail or result.status.lower().replace('_', ' ')}.",
                     warn=True)
            else:
                live = result.candidate
                state = "still passes" if live.passed else \
                    f"would not pass now ({REJECTION_LABELS.get(live.reject_reason, live.reject_reason)})"
                verdict_line("good" if live.passed else "bad",
                             f"Live: {'credit' if live.is_credit else 'debit'} "
                             f"{abs(live.entry_cash_usd) / 100:.2f} per share, expected "
                             f"{usd(live.ev_usd, signed=True)}, score "
                             f"{money(100 * live.score, signed=True, decimals=1)} per $100 tail risk; "
                             f"{state}.")


def detail_panel(c: dict, config: dict, *, risk_budget: float | None, trades: list[dict],
                 today: date, cap: float, db_path, pick_id: int | None) -> None:
    left, right = st.columns([1, 1], gap="large")
    credit = float(c["entry_cash_usd"]) > 0
    with left:
        html(payoff_svg(c["legs"], float(c["entry_cash_usd"]), float(c["commission_usd"]),
                        spot=c.get("spot"), breakevens=c.get("breakevens") or [],
                        sigma_move=sigma_move(c)))
        note("Profit or loss at expiry for one lot, after costs. Dots mark the breakevens; "
             "the shaded band is one standard deviation at the delivered-variance width.")
        html(sensitivity_table(c, config))
        html(f'<div class="chr-detail"><p>{escape(why_text(c))}</p></div>')
        if c.get("event_move_pct"):
            note(f"The options price an event before expiry, about ±{c['event_move_pct']:.1f}% "
                 "extra move (likely earnings). The distribution includes it; it is still the main risk.",
                 warn=True)
    with right:
        html(f'<div class="chr-detail"><h3>{escape(c["underlying"])} {escape(shape(c))}, '
             f'{escape(short_date(c["expiration"]))}</h3></div>')
        html(legs_table(c))
        word = "credit" if credit else "debit"
        guard = "accept no less" if credit else "pay no more"
        html(f'<p class="chr-limit">Combo limit <strong>{limit_price(c):.2f} {word}</strong> '
             f'per share; {guard}.</p>')
        n = contracts_for(float(c["max_loss_usd"]), risk_budget)
        sizing = ("" if n is None else
                  f" {n} lot{'s' if n != 1 else ''} fit your {usd(risk_budget)} limit."
                  if n else f" One lot exceeds your {usd(risk_budget)} limit.")
        note(f"Hold to expiry. Commission assumed {usd(c['commission_usd'], decimals=2)}."
             + sizing)
        age = c.get("quote_age_seconds")
        if age is None:
            note("Quote age unknown.", warn=True)
        else:
            note(f"Quotes were {float(age) / 60:.0f} minutes old at the scan. "
                 "Re-price before you place the order.")
        _reprice_block(c, db_path)
        note(EXIT_RULE, warn=True)
        _took_it_form(c, config, trades, today, cap, risk_budget, db_path, pick_id)


def render_trades_page(lane: str, *, risk_budget: float | None, db_path=None,
                       now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    today = now.astimezone(NY).date()
    title = "Today's trades" if lane == LANE_MAIN else "0DTE"
    db_key = _db_key(db_path)
    try:
        scan = _read_scan(lane, db_key)
    except Exception as exc:
        head(title)
        if _engine_tables_missing(exc):
            note("The trade engine is not installed on this database yet. "
                 "Deploy the release with migration 039 to create it.")
        else:
            note(f"The trade engine could not be read ({type(exc).__name__}). "
                 "Check the System page.", warn=True)
        return
    if scan is None:
        head(title, "No scan yet")
        note("The engine scans after every data-collection cycle during market hours. "
             "Trades appear here after the first one.")
        return

    config = scan.get("config", {}) or {}
    age = minutes_ago(scan.get("asof_at"), now)
    stale = age is not None and age > STALE_SCAN_MINUTES
    fresh = f"Scanned {ny_time(scan.get('asof_at'))}"
    if age is not None and age < 600:
        fresh += f", {age:.0f} min ago"
    head(title, fresh, stale=stale)

    passed = scan.get("passed", [])
    top_n = int(config.get("top_n", 5))
    scope = ("7 to 45 days to expiry" if lane == LANE_MAIN
             else "same-day and next-day SPY and QQQ, scanned 09:45 to 15:45 New York")
    lede(f"{scan.get('passed_count', 0)} of {scan.get('structures_scored', 0):,} priced credit trades "
         f"pass across {scan.get('chains_scanned', 0)} underlyings ({scope}). Expected profit is "
         "priced under the market's own smile, shrunk to the share of priced variance each name has "
         "delivered; the score is expected profit per $100 of expected loss in the worst 5% of "
         "outcomes, after costs.")
    if scan.get("status") == "FAILED":
        note(f"The last scan failed: {scan.get('error_message')}", warn=True)
    elif stale:
        note("This scan is old and prices have moved. Use it as a watch-list and re-price "
             "before trading.", warn=True)
    missing = scan.get("chains_without_history") or []
    if missing:
        note(f"Less than a year of implied/realised history for {', '.join(missing[:12])}"
             + ("…" if len(missing) > 12 else "") + "; these cannot pass until it is in.")
    blocked = scan.get("chains_blocked") or {}
    if blocked:
        note(f"Skipped: {', '.join(f'{k} ({REJECTION_LABELS.get(v, v)})' for k, v in list(blocked.items())[:10])}"
             + ("…" if len(blocked) > 10 else "") + ".")
    premiums = scan.get("premiums") or {}
    if premiums:
        shown = sorted(premiums.items(), key=lambda kv: kv[1].get("ratio", 1.0))[:12]
        note("Delivered share of priced variance: " + ", ".join(
            f"{k} {float(v['ratio']):.0%}" for k, v in shown) + ("…" if len(premiums) > 12 else "") + ".")

    trades = read_trades_safe(db_path)
    session = str(scan.get("session_date") or today.isoformat())
    try:
        frozen = _read_session_picks(lane, session, db_key)
    except Exception:
        frozen = []
    frozen_by_key = {p["structure_key"]: int(p["id"]) for p in frozen}
    decision_time = str(config.get("decision_time", "10:00"))
    if frozen:
        note(f"Today's frozen picks ({decision_time} NY decision scan): "
             + ", ".join(sorted({p['underlying'] for p in frozen})) + ". Later scans update this "
             "screen, not the track record.")
    elif scan.get("decision") == 0:
        note(f"Picks are frozen by the first scan at or after {decision_time} NY; this scan is a preview.")

    cap = float(st.session_state.get("open_risk_cap", open_risk_cap()) or 0)
    if not passed:
        rej = sorted(scan.get("rejections", {}).items(), key=lambda kv: -kv[1])[:3]
        verdict_line("wait", "No trade clears the bar right now. Doing nothing is a valid result.")
        if rej:
            note("Most common reasons: " + "; ".join(
                f"{REJECTION_LABELS.get(k, k)} ({v:,})" for k, v in rej) + ".")
        if scan.get("near_misses"):
            h2("Closest candidates")
            html(table(near_miss_columns(today), scan["near_misses"]))
        return

    # Best structure per underlying first (what the picks are), then the rest.
    seen: set[str] = set()
    best, rest = [], []
    for c in passed:
        (rest if c["underlying"] in seen else best).append(c)
        seen.add(c["underlying"])
    ordered = best + rest
    show_all = len(ordered) > top_n and st.toggle(
        f"Show all {len(ordered)} stored passing trades", key=f"all_{lane}")
    rows = [{**c, "_rank": i} for i, c in enumerate(ordered if show_all else ordered[:top_n], 1)]
    top_score = max(float(r["score"]) for r in rows)

    table_slot = st.container()
    options = [f"{r['_rank']}  {r['underlying']}" for r in rows]
    choice = st.segmented_control("Details for", options, default=options[0],
                                  key=f"sel_{lane}_{show_all}")
    selected = options.index(choice) if choice in options else 0
    with table_slot:
        html(table(trade_columns(today, top_score), rows, groups=TRADE_GROUPS, selected=selected))
        note("Max loss, %: chance of losing (nearly) the full amount at risk. Win, %: chance of "
             "any profit. Both under the shrunk smile.")
    chosen = rows[selected]
    detail_panel(chosen, config, risk_budget=risk_budget, trades=trades, today=today, cap=cap,
                 db_path=db_path, pick_id=frozen_by_key.get(chosen["structure_key"]))


# ----------------------------------------------------------------- track record
def _close_trade_form(open_trades: list[dict], db_path) -> None:
    if not open_trades:
        return
    with st.expander("Close a trade by hand"):
        labels = {f"#{t['id']} {t['underlying']} {shape(t['record'])} {short_date(t['expiration'])} "
                  f"× {t['lots']}": int(t["id"]) for t in open_trades}
        with st.form("close_trade"):
            which = st.selectbox("Trade", list(labels))
            cash = st.number_input("Cash per share to close (received +, paid −)", value=0.0,
                                   step=0.01, format="%.2f")
            commission = st.number_input("Commission, $", min_value=0.0, value=0.0, step=0.5,
                                         format="%.2f")
            price = st.number_input("Underlying price (optional)", min_value=0.0, value=0.0,
                                    step=0.01, format="%.2f")
            submitted = st.form_submit_button("Record close")
        if submitted:
            from src.database.repository import get_connection

            conn = get_connection(db_path)
            try:
                pnl = close_trade(conn, labels[which], cash_per_share=float(cash),
                                  commission_usd=float(commission), closed_at=datetime.now(UTC),
                                  underlying_price=float(price) or None)
            finally:
                conn.close()
            st.cache_data.clear()
            st.success(f"Closed: {usd(pnl, signed=True)}.")


def _trades_section(trades: list[dict], today: date, db_path) -> None:
    h2("Your trades")
    if not trades:
        note("No trades recorded. Use \"I took this trade\" on a card; real fills are the only "
             "way to check the fill and commission assumptions.")
        return
    ex = exposure(trades, today=today)
    groups = ", ".join(f"{k} {usd(v)}" for k, v in sorted(ex.by_group.items(), key=lambda kv: -kv[1]))
    note(f"Open risk {usd(ex.open_risk_usd)} in {ex.open_trades} trade"
         f"{'s' if ex.open_trades != 1 else ''}" + (f" ({groups})" if groups else "")
         + f". Realised {usd(ex.realised_pnl_usd, signed=True)} on closed trades.")
    rows = []
    for t in trades:
        r = t["record"]
        modelled = abs(float(r["entry_cash_usd"])) / 100
        real = abs(float(t["fill_per_share"]))
        rows.append({**t, "_modelled": modelled, "_real": real,
                     "_status": "Open" if t.get("pnl_usd") is None else
                     ("Settled" if t.get("close_kind") == "EXPIRY" else "Closed")})
    html(table([
        Col("taken", "Taken", "l", render=lambda t: escape(ny_time(t["taken_at"], "%d %b"))),
        Col("trade", "Trade", "l",
            render=lambda t: f'<span class="tick">{escape(t["underlying"])}</span> '
                             f'{escape(shape(t["record"]))}'
                             f'<span class="sub">{escape(t["record"].get("description", ""))}</span>'),
        Col("exp", "Expiry", "l", render=lambda t: short_date(t["expiration"])),
        Col("lots", "Lots", "r", render=lambda t: str(t["lots"])),
        Col("fill", "Fill", "r", group_start=True, render=lambda t: money(t["_real"], decimals=2)),
        Col("mod", "Modelled", "r", render=lambda t: money(t["_modelled"], decimals=2)),
        Col("risk", "Max loss", "r", group_start=True, render=lambda t: money(t["max_loss_usd"])),
        Col("pnl", "P&L", "r", render=lambda t: "–" if t.get("pnl_usd") is None
            else money(t["pnl_usd"], signed=True), css=lambda t: tone(t.get("pnl_usd"))),
        Col("status", "Status", "l", render=lambda t: t["_status"],
            css=lambda t: "muted" if t["_status"] == "Open" else ""),
    ], rows, groups=[("", 4), ("Per share, $", 2), ("Total, $", 3)]))
    _close_trade_form([t for t in trades if t.get("pnl_usd") is None], db_path)


def _backtest_section() -> None:
    summary = load_backtest_summary(os.environ.get("CHRISTIANIA_BACKTEST_SUMMARY"))
    h2("Backtest")
    if not summary:
        note("No backtest summary found. Run run_engine_backtest.py on a machine with the Theta "
             "Terminal and point CHRISTIANIA_BACKTEST_SUMMARY at its summary.json. Without it, "
             "the live record cannot say how the engine behaves in a volatility shock.", warn=True)
        return
    period = summary.get("period", {})
    crit = summary.get("criteria") or {}
    if crit:
        kind = {"PASS": "good", "FAIL": "bad"}.get(crit.get("verdict"), "wait")
        verdict_line(kind, f"Out-of-sample verdict: {crit.get('verdict')}. {crit.get('statement', '')}")
    oos = (summary.get("assumptions") or {}).get("oos_start")

    def row(label: str, b: dict) -> dict:
        return {"label": label, "settled": b.get("settled"), "days": b.get("expiry_days"),
                "pnl": b.get("total_pnl_usd"), "pred": b.get("predicted_ev_usd"),
                "dd": b.get("max_drawdown_usd"), "worst": b.get("worst_day_usd"), "wm": b.get("worst_month"),
                "hit": b.get("hit_rate"), "phit": b.get("predicted_hit_rate"),
                "mlr": b.get("max_loss_rate"), "pmlr": b.get("predicted_max_loss_rate"),
                "ci": b.get("avg_pnl_ci95_usd")}

    rows = [row(f"All picks, {period.get('start', '?')} to {period.get('end', '?')}", summary)]
    if summary.get("calibration"):
        rows.append(row(f"Calibration, before {oos}", summary["calibration"]))
    if summary.get("out_of_sample"):
        rows.append(row(f"Out of sample, from {oos}", summary["out_of_sample"]))
    single = (summary.get("single_slot") or {}).get("out_of_sample")
    if single:
        rows.append(row("One position at a time, out of sample", single))
    html(table([
        Col("label", "Window", "l", render=lambda r: escape(str(r["label"]))
            + f'<span class="sub">{r["settled"]} settled picks, {r["days"]} expiry days</span>'),
        Col("pnl", "P&L", "r", group_start=True, emphasis=True,
            render=lambda r: money(r["pnl"], signed=True) + (
                "" if not r["ci"] else
                f'<span class="sub">average {money(r["ci"][0], signed=True)} to '
                f'{money(r["ci"][1], signed=True)}</span>')),
        Col("pred", "Model predicted", "r", render=lambda r: money(r["pred"], signed=True)),
        Col("dd", "Max drawdown", "r", render=lambda r: money(r["dd"], signed=True),
            css=lambda r: tone(r["dd"])),
        Col("worst", "Worst day", "r", render=lambda r: money(r["worst"], signed=True)
            + (f'<span class="sub">worst month {escape(str(r["wm"][0]))} '
               f'{money(r["wm"][1], signed=True)}</span>' if r["wm"] else "")),
        Col("hit", "Hit rate, %", "r", group_start=True,
            render=lambda r: percent(r["hit"]) + (
                "" if r["phit"] is None else f'<span class="sub">model said {percent(r["phit"])}</span>')),
        Col("mlr", "Full loss, %", "r",
            render=lambda r: percent(r["mlr"]) + (
                "" if r["pmlr"] is None else f'<span class="sub">model said {percent(r["pmlr"])}</span>')),
    ], rows, groups=[("", 1), ("One lot per pick, $", 4), ("", 2)]))


def render_track_record_page(*, db_path=None, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    today = now.astimezone(NY).date()
    db_key = _db_key(db_path)
    try:
        picks = _read_picks(db_key)
    except Exception as exc:
        head("Track record")
        note("The trade engine is not installed on this database yet."
             if _engine_tables_missing(exc)
             else f"The track record could not be read ({type(exc).__name__}).",
             warn=not _engine_tables_missing(exc))
        return
    first = min((p["first_seen_at"] for p in picks), default=None)
    head("Track record", f"Since {ny_time(first, '%d %b %Y')}" if first else "")
    lede("One frozen pick per underlying per session, settled at expiry, one lot each. This is "
         "the engine's record, scored by expiry day. Your own trades are below it.")
    lane = st.segmented_control("Lane", ["All", "Main", "0DTE"], default="All",
                                label_visibility="collapsed", key="record_lane")
    if lane == "Main":
        picks = [p for p in picks if p["lane"] == LANE_MAIN]
    elif lane == "0DTE":
        picks = [p for p in picks if p["lane"] == LANE_ZERO_DTE]

    if not picks:
        note("No frozen picks yet. They appear after the first decision scan of a session.")
    else:
        card = scorecard(picks)
        kind, text = verdict(card)
        verdict_line(kind, text)
        summary = [{
            "picks": card.picks, "settled": card.settled, "open": card.open,
            "days": card.expiry_days, "pnl": card.total_pnl_usd, "ror": card.return_on_risk,
            "pred": card.predicted_ev_usd, "hit": card.hit_rate, "phit": card.predicted_hit_rate,
            "mlr": card.max_loss_rate, "pmlr": card.predicted_max_loss_rate,
            "avg": card.avg_pnl_usd, "ci": card.pnl_ci95_usd, "dd": card.max_drawdown_usd,
            "worst": card.worst_day_usd, "pin": card.near_strike_settlements,
        }]
        html(table([
            Col("picks", "Picks", "r",
                render=lambda r: f'{r["picks"]}<span class="sub">{r["settled"]} settled, '
                                 f'{r["open"]} open, {r["days"]} expiry days</span>'),
            Col("pnl", "Settled P&L", "r", group_start=True, emphasis=True,
                render=lambda r: money(r["pnl"], signed=True)),
            Col("pred", "Model predicted", "r", render=lambda r: money(r["pred"], signed=True)),
            Col("avg", "Average trade", "r",
                render=lambda r: money(r["avg"], signed=True) + (
                    "" if not r["ci"] else
                    f'<span class="sub">bootstrap by expiry day {money(r["ci"][0], signed=True)} to '
                    f'{money(r["ci"][1], signed=True)}</span>')),
            Col("dd", "Max drawdown", "r", render=lambda r: money(r["dd"], signed=True),
                css=lambda r: tone(r["dd"])),
            Col("worst", "Worst day", "r", render=lambda r: money(r["worst"], signed=True)),
            Col("ror", "Return on risk, %", "r", group_start=True,
                render=lambda r: percent(r["ror"], 1)),
            Col("hit", "Hit rate, %", "r",
                render=lambda r: percent(r["hit"]) + (
                    "" if r["phit"] is None else
                    f'<span class="sub">model said {percent(r["phit"])}</span>')),
            Col("mlr", "Full loss, %", "r",
                render=lambda r: percent(r["mlr"]) + (
                    "" if r["pmlr"] is None else
                    f'<span class="sub">model said {percent(r["pmlr"])}</span>')),
        ], summary, groups=[("", 1), ("Money, $", 5), ("Accuracy", 3)]))
        if card.near_strike_settlements:
            note(f"{card.near_strike_settlements} settlement(s) landed within 0.1% of a short strike; "
                 "check them against your broker statement (pin risk).", warn=True)

        settled = sorted((p for p in picks if p.get("pnl_usd") is not None),
                         key=lambda p: p["settlement_date"])
        if settled:
            by_day: dict[str, float] = defaultdict(float)
            for p in settled:
                by_day[p["settlement_date"]] += float(p["pnl_usd"])
            running, points = 0.0, []
            for d in sorted(by_day):
                running += by_day[d]
                points.append((short_date(d), running))
            h2("Cumulative settled P&L, $")
            html(line_svg(points))

            groups: dict[str, list[dict]] = defaultdict(list)
            for p in settled:
                groups[FAMILY_LABELS.get(p["family"], p["family"])].append(p)
            fam_rows = [{
                "type": k, "n": len(v), "pnl": sum(float(p["pnl_usd"]) for p in v),
                "pred": sum(float(p["ev_usd"]) for p in v),
                "hit": sum(float(p["pnl_usd"]) > 0 for p in v) / len(v),
            } for k, v in sorted(groups.items())]
            h2("By trade type")
            html(table([
                Col("type", "Trade type", "l"),
                Col("n", "Settled", "r", render=lambda r: str(r["n"])),
                Col("pnl", "P&L, $", "r", group_start=True,
                    render=lambda r: money(r["pnl"], signed=True), css=lambda r: tone(r["pnl"])),
                Col("pred", "Predicted, $", "r", render=lambda r: money(r["pred"], signed=True)),
                Col("hit", "Hit rate, %", "r", group_start=True, render=lambda r: percent(r["hit"])),
            ], fam_rows))

        h2("Every pick")
        ordered = sorted(picks, key=lambda p: (p.get("pnl_usd") is not None, p["expiration"]))
        html(table([
            Col("seen", "Frozen", "l", render=lambda p: escape(ny_time(p["first_seen_at"], "%d %b"))),
            Col("trade", "Trade", "l",
                render=lambda p: f'<span class="tick">{escape(p["underlying"])}</span> '
                                 f'{escape(shape(p))}{" (0DTE)" if p["lane"] == LANE_ZERO_DTE else ""}'
                                 f'<span class="sub">{escape(p["record"].get("description", ""))}</span>'),
            Col("exp", "Expiry", "l", render=lambda p: short_date(p["expiration"])),
            Col("risk", "Max loss", "r", group_start=True, render=lambda p: money(p["max_loss_usd"])),
            Col("pred", "Expected", "r", render=lambda p: money(p["ev_usd"], signed=True)),
            Col("res", "Result", "r",
                render=lambda p: "–" if p.get("pnl_usd") is None else money(p["pnl_usd"], signed=True),
                css=lambda p: tone(p.get("pnl_usd"))),
            Col("status", "Status", "l", group_start=True,
                render=lambda p: "Open" if p.get("pnl_usd") is None
                else f"Settled at {float(p['settlement_price']):,.2f}"
                + (" (pin)" if p.get("near_strike") else ""),
                css=lambda p: "muted" if p.get("pnl_usd") is None else ""),
        ], ordered, groups=[("", 3), ("Per lot, $", 3), ("", 1)]))

    _trades_section(read_trades_safe(db_path), today, db_path)
    _backtest_section()


# ----------------------------------------------------------------------- system
def render_system(rows: list[tuple[str, bool | None, str]], *, next_collection: str,
                  collecting: bool) -> None:
    bad = [label for label, ok, _ in rows if ok is False]
    unknown = [label for label, ok, _ in rows if ok is None]
    head("System", "Collecting now" if collecting else f"Next collection {next_collection}")
    if bad:
        verdict_line("bad", "Needs attention: " + ", ".join(bad) + ".")
    elif unknown:
        verdict_line("wait", "Running. Not checked: " + ", ".join(unknown) + ".")
    else:
        verdict_line("good", "Everything is running.")

    def status(r: dict) -> str:
        cls, word = {True: ("ok", "OK"), False: ("bad", "Problem"), None: ("unk", "Unknown")}[r["ok"]]
        return f'<span class="dot {cls}"></span>{word}'

    html(table([
        Col("label", "Check", "l", render=lambda r: f'<span class="tick">{escape(r["label"])}</span>'),
        Col("ok", "Status", "l", render=status),
        Col("text", "Detail", "l", css=lambda r: "muted"),
    ], [{"label": l, "ok": ok, "text": t} for l, ok, t in rows]))


def engine_checks(now: datetime, db_key: str | None = None) -> list[tuple[str, bool | None, str]]:
    out = []
    for lane, label in ((LANE_MAIN, "Trade engine"), (LANE_ZERO_DTE, "0DTE engine")):
        try:
            scan = _read_scan(lane, db_key)
        except Exception as exc:
            out.append((label, None, f"Unavailable ({type(exc).__name__})."))
            continue
        if scan is None:
            out.append((label, None, "No scan yet."))
            continue
        ok = scan["status"] == "COMPLETED"
        out.append((label, ok,
                    f"Last scan {ny_time(scan['asof_at'])}: {scan['structures_scored']:,} trades "
                    f"priced, {scan['passed_count']} passed."
                    if ok else f"Last scan failed: {scan.get('error_message')}"))
    out.extend(_data_checks(now, db_key))
    summary = load_backtest_summary(os.environ.get("CHRISTIANIA_BACKTEST_SUMMARY"))
    if summary:
        p = summary.get("period", {})
        out.append(("Backtest", True, f"Summary from {p.get('start')} to {p.get('end')}, "
                    f"{summary.get('settled')} settled picks."))
    else:
        out.append(("Backtest", None, "No summary file. Run run_engine_backtest.py before trusting "
                    "the engine."))
    return out


def _data_checks(now: datetime, db_key: str | None) -> list[tuple[str, bool | None, str]]:
    from src.engine.history import history_status
    from src.operations.sqlite_runtime import open_readonly_connection

    try:
        conn = open_readonly_connection(db_key)
    except Exception as exc:
        return [("Price history", None, f"Unavailable ({type(exc).__name__}).")]
    try:
        floor = (now - timedelta(days=14)).astimezone(UTC).isoformat().replace("+00:00", "Z")
        symbols = {str(r[0]) for r in conn.execute(
            "SELECT DISTINCT underlying FROM market_snapshots WHERE captured_at >= ?", (floor,))}
        zero = [s.strip().upper() for s in os.environ.get("CHRISTIANIA_ZERO_DTE_SYMBOLS", "SPY,QQQ").split(",") if s.strip()]
        symbols |= set(zero)
        out: list[tuple[str, bool | None, str]] = []
        try:
            hs = history_status(conn, symbols, now=now)
            out.append(("Price history", hs.ok, hs.sentence()))
        except Exception as exc:
            out.append(("Price history", None, f"Unavailable ({type(exc).__name__})."))
        try:
            from src.engine.premium import iv_history_counts, sessions_needed

            counts = iv_history_counts(conn, symbols)
            need = sessions_needed()
            ready = sorted(s for s, n in counts.items() if n >= need)
            short = sorted(s for s, n in counts.items() if n < need)
            if not counts:
                out.append(("Risk-premium history", None, "No symbols to check yet."))
            else:
                text = f"{len(ready)} of {len(counts)} symbols have the {need} sessions of implied vol needed"
                if short:
                    text += "; still filling: " + ", ".join(
                        f"{s} {counts[s]}" for s in short[:10]) + ("…" if len(short) > 10 else "")
                out.append(("Risk-premium history", not short, text + "."))
        except Exception as exc:
            out.append(("Risk-premium history", None, f"Unavailable ({type(exc).__name__})."))
        return out
    finally:
        conn.close()
