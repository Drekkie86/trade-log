"""Christiania screens: Today's trades, 0DTE, Track record and System.

Everything shown comes from the engine's frozen scans and picks. The UI reads
and explains; it never computes or changes a recommendation.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, date, datetime
from html import escape
from typing import Any

import streamlit as st

from src.engine.chains import NY, parse_utc
from src.engine.ledger import conservative_pop, latest_scan, picks_with_outcomes, scorecard
from src.engine.pipeline import LANE_MAIN, LANE_ZERO_DTE
from src.engine.structures import FAMILY_LABELS
from src.ui.design import (
    Col, bar, finite, html, line_svg, money, payoff_svg, percent, table, tone, usd,
)

REJECTION_LABELS = {
    "MODELS_DISAGREE": "the two forecast models disagree",
    "EV_TOO_SMALL": "expected profit too small after costs",
    "RETURN_ON_RISK_TOO_LOW": "return on risk too low",
    "WIDE_SPREAD": "bid/ask spread too wide",
    "ONE_SIDED_QUOTE": "a leg has no two-sided quote",
    "LOW_OPEN_INTEREST": "too little open interest",
    "STALE_QUOTE": "quotes too old",
    "MODEL_UNAVAILABLE": "not enough price history",
    "NO_USABLE_EXPIRY": "no usable expiry",
    "NO_RISK_ARBITRAGE_SUSPECT": "suspect quotes",
    "EXPIRED": "expired",
}
SHAPE_LABELS = {
    "PUT_CREDIT_SPREAD": "Put credit spread",
    "CALL_CREDIT_SPREAD": "Call credit spread",
    "CALL_DEBIT_SPREAD": "Call debit spread",
    "PUT_DEBIT_SPREAD": "Put debit spread",
    "IRON_CONDOR": "Iron condor",
    "IRON_FLY": "Iron fly",
}
STALE_SCAN_MINUTES = 30


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
    scores = c.get("scores", {})
    vol = scores.get("VOL_FORECAST", {}).get("ev_usd")
    emp = scores.get("EMPIRICAL", {}).get("ev_usd")
    imp = scores.get("IMPLIED", {}).get("ev_usd")
    parts = []
    if c.get("atm_iv") and c.get("forecast_vol"):
        rich = c["atm_iv"] > c["forecast_vol"]
        parts.append(
            f"The options price {percent(c['atm_iv'])}% volatility; the stock's own forecast is "
            f"{percent(c['forecast_vol'])}%, so options look {'expensive' if rich else 'cheap'}."
        )
    parts.append(
        f"The volatility model expects {usd(vol, signed=True)} and the price-history model "
        f"{usd(emp, signed=True)}; the score uses the lower."
    )
    if imp is not None:
        parts.append(
            f"At the market's own volatility the trade is worth {usd(imp, signed=True)}, "
            "roughly minus the costs: the edge exists only if the forecast is right."
        )
    return " ".join(parts)


def sigma_move(c: dict) -> float | None:
    vol, days = c.get("forecast_vol"), c.get("trading_days")
    if not (finite(vol) and finite(days)) or days <= 0:
        return None
    return float(vol) * math.sqrt(float(days) / 252.0)


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


# ------------------------------------------------------------------------ reads
@st.cache_data(ttl=60, show_spinner=False)
def _read_scan(lane: str, db_key: str | None) -> dict | None:
    from src.operations.sqlite_runtime import open_readonly_connection

    conn = open_readonly_connection(db_key)
    try:
        return latest_scan(conn, lane)
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


def _engine_tables_missing(exc: Exception) -> bool:
    return "no such table" in str(exc).lower()


# ------------------------------------------------------------------ trade table
def trade_columns(today: date, risk_budget: float | None, top_edge: float) -> list[Col]:
    def trade_cell(c: dict) -> str:
        return (f'<span class="tick">{escape(c["underlying"])}</span> {escape(shape(c))}'
                f'<span class="sub">{escape(c["description"])}</span>')

    def expiry_cell(c: dict) -> str:
        d = days_to(c["expiration"], today)
        when = "today" if d == 0 else "tomorrow" if d == 1 else f"{d} days"
        return f'{short_date(c["expiration"])}<span class="sub">{when}</span>'

    def size_cell(c: dict) -> str:
        n = contracts_for(float(c["max_loss_usd"]), risk_budget)
        return "–" if n is None else str(n)

    return [
        Col("rank", "", "r", render=lambda c: str(c["_rank"]), css=lambda c: "rank"),
        Col("trade", "Trade", "l", render=trade_cell, cls="wide"),
        Col("expiry", "Expiry", "l", render=expiry_cell, cls="nw opt"),
        Col("cash", "Credit / debit", "r", group_start=True, cls="opt",
            render=lambda c: money(c["entry_cash_usd"], signed=True)),
        Col("risk", "Max loss", "r", cls="opt", render=lambda c: money(c["max_loss_usd"])),
        Col("ev", "Expected", "r",
            render=lambda c: money(c["conservative_ev_usd"], signed=True),
            css=lambda c: tone(c["conservative_ev_usd"])),
        Col("edge", "Per $100 risk", "r", group_start=True, emphasis=True,
            render=lambda c: money(100 * c["ev_per_risk"], signed=True, decimals=1)
            + bar(c["ev_per_risk"], top_edge, 3.0)),
        Col("pop", "Win, %", "r", render=lambda c: percent(conservative_pop(c)), cls="opt"),
        Col("size", "Lots", "r", group_start=True, render=size_cell, cls="opt"),
    ]


TRADE_GROUPS = [("", 3), ("Per lot, $", 3), ("Edge", 2), ("Size", 1)]


def near_miss_columns(today: date) -> list[Col]:
    return [
        Col("trade", "Trade", "l",
            render=lambda c: f'<span class="tick">{escape(c["underlying"])}</span> '
                             f'{escape(shape(c))}<span class="sub">{escape(c["description"])}</span>'),
        Col("expiry", "Expiry", "l",
            render=lambda c: f'{short_date(c["expiration"])}'
                             f'<span class="sub">{days_to(c["expiration"], today)} days</span>'),
        Col("ev", "Expected profit, $", "r", group_start=True,
            render=lambda c: money(c["conservative_ev_usd"], signed=True),
            css=lambda c: tone(c["conservative_ev_usd"])),
        Col("edge", "Per $100 at risk", "r",
            render=lambda c: money(100 * c["ev_per_risk"], signed=True, decimals=1)),
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


def detail_panel(c: dict, risk_budget: float | None) -> None:
    left, right = st.columns([1, 1], gap="large")
    credit = float(c["entry_cash_usd"]) > 0
    with left:
        html(payoff_svg(c["legs"], float(c["entry_cash_usd"]), float(c["commission_usd"]),
                        spot=c.get("spot"), breakevens=c.get("breakevens") or [],
                        sigma_move=sigma_move(c)))
        note("Profit or loss at expiry for one lot, after costs. Dots mark the breakevens; "
             "the shaded band is the forecast's one-standard-deviation range.")
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
        if c.get("quote_age_seconds") is not None:
            note(f"Quotes were {float(c['quote_age_seconds']) / 60:.0f} minutes old at the scan. "
                 "Re-quote in your broker first.")
        html(f'<div class="chr-detail"><p>{escape(why_text(c))}</p></div>')
        if c.get("event_move_pct"):
            note(f"The options price an event before expiry, about ±{c['event_move_pct']:.1f}% "
                 "extra move (likely earnings). The models include it; it is still the main risk.",
                 warn=True)


def render_trades_page(lane: str, *, risk_budget: float | None, db_path=None,
                       now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    today = now.astimezone(NY).date()
    title = "Today's trades" if lane == LANE_MAIN else "0DTE"
    db_key = None if db_path is None else str(db_path)
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

    age = minutes_ago(scan.get("asof_at"), now)
    stale = age is not None and age > STALE_SCAN_MINUTES
    fresh = f"Scanned {ny_time(scan.get('asof_at'))}"
    if age is not None and age < 600:
        fresh += f", {age:.0f} min ago"
    head(title, fresh, stale=stale)

    passed = scan.get("passed", [])
    top_n = int(scan.get("config", {}).get("top_n", 5))
    scope = ("7 to 45 days to expiry" if lane == LANE_MAIN
             else "same-day and next-day SPY and QQQ, scanned 09:45 to 15:45 New York")
    lede(f"{scan.get('passed_count', 0)} of {scan.get('structures_scored', 0):,} priced trades "
         f"pass across {scan.get('chains_scanned', 0)} underlyings ({scope}). "
         "Ranked by expected profit per $100 at risk, after slippage and commission.")
    if scan.get("status") == "FAILED":
        note(f"The last scan failed: {scan.get('error_message')}", warn=True)
    elif stale:
        note("This scan is old and prices have moved. Use it as a watch-list and re-quote "
             "everything before trading.", warn=True)
    missing = scan.get("chains_without_history") or []
    if missing:
        note(f"No price history yet for {', '.join(missing[:12])}"
             + ("…" if len(missing) > 12 else "") + "; these cannot pass until it arrives.")

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

    show_all = len(passed) > top_n and st.toggle(
        f"Show all {len(passed)} passing trades", key=f"all_{lane}")
    rows = [{**c, "_rank": i} for i, c in enumerate(passed if show_all else passed[:top_n], 1)]
    top_edge = max(float(r["ev_per_risk"]) for r in rows)

    table_slot = st.container()
    options = [f"{r['_rank']}  {r['underlying']}" for r in rows]
    choice = st.segmented_control("Details for", options, default=options[0],
                                  key=f"sel_{lane}_{show_all}")
    selected = options.index(choice) if choice in options else 0
    with table_slot:
        html(table(trade_columns(today, risk_budget, top_edge), rows,
                   groups=TRADE_GROUPS, selected=selected))
    detail_panel(rows[selected], risk_budget)


# ----------------------------------------------------------------- track record
def verdict(card) -> tuple[str, str]:
    if card.settled < 30:
        return ("wait", f"Too early to judge: {card.settled} settled trade"
                f"{'s' if card.settled != 1 else ''}. Results start to mean something around 30.")
    lo, hi = card.pnl_ci95_usd
    if lo > 0:
        return ("good", "Making money: the average trade is profitable with 95% confidence.")
    if hi < 0:
        return ("bad", "Losing money: the average trade loses with 95% confidence. "
                "The models' edge is not showing up in real outcomes.")
    return ("wait", "Not distinguishable from zero yet. Keep collecting before adding risk.")


def render_track_record_page(*, db_path=None) -> None:
    db_key = None if db_path is None else str(db_path)
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
    lede("Every trade the engine recommended, settled at expiry, one lot each. "
         "This decides whether the engine makes money, not the model.")
    lane = st.segmented_control("Lane", ["All", "Main", "0DTE"], default="All",
                                label_visibility="collapsed", key="record_lane")
    if lane == "Main":
        picks = [p for p in picks if p["lane"] == LANE_MAIN]
    elif lane == "0DTE":
        picks = [p for p in picks if p["lane"] == LANE_ZERO_DTE]
    if not picks:
        note("No recommended trades yet. They appear here as soon as the engine surfaces one.")
        return

    card = scorecard(picks)
    kind, text = verdict(card)
    verdict_line(kind, text)
    summary = [{
        "picks": card.picks, "settled": card.settled, "open": card.open,
        "pnl": card.total_pnl_usd, "ror": card.return_on_risk, "pred": card.predicted_ev_usd,
        "hit": card.hit_rate, "phit": card.predicted_hit_rate,
        "avg": card.avg_pnl_usd, "ci": card.pnl_ci95_usd,
    }]
    cols = [
        Col("picks", "Recommended", "r",
            render=lambda r: f'{r["picks"]}<span class="sub">{r["settled"]} settled, '
                             f'{r["open"]} open</span>'),
        Col("pnl", "Settled P&L", "r", group_start=True, emphasis=True,
            render=lambda r: money(r["pnl"], signed=True)),
        Col("pred", "Model predicted", "r", render=lambda r: money(r["pred"], signed=True)),
        Col("avg", "Average trade", "r",
            render=lambda r: money(r["avg"], signed=True) + (
                "" if not r["ci"] else
                f'<span class="sub">95% range {money(r["ci"][0], signed=True)} to '
                f'{money(r["ci"][1], signed=True)}</span>')),
        Col("ror", "Return on risk, %", "r", group_start=True,
            render=lambda r: percent(r["ror"], 1)),
        Col("hit", "Hit rate, %", "r",
            render=lambda r: percent(r["hit"]) + (
                "" if r["phit"] is None else
                f'<span class="sub">model said {percent(r["phit"])}</span>')),
    ]
    html(table(cols, summary, groups=[("", 1), ("Money, $", 3), ("Accuracy", 2)]))

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
            "pred": sum(float(p["conservative_ev_usd"]) for p in v),
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

    h2("Every recommendation")
    ordered = sorted(picks, key=lambda p: (p.get("pnl_usd") is not None, p["expiration"]))
    html(table([
        Col("seen", "Recommended", "l", render=lambda p: escape(ny_time(p["first_seen_at"], "%d %b"))),
        Col("trade", "Trade", "l",
            render=lambda p: f'<span class="tick">{escape(p["underlying"])}</span> '
                             f'{escape(shape(p))}{" (0DTE)" if p["lane"] == LANE_ZERO_DTE else ""}'
                             f'<span class="sub">{escape(p["record"].get("description", ""))}</span>'),
        Col("exp", "Expiry", "l", render=lambda p: short_date(p["expiration"])),
        Col("risk", "Max loss", "r", group_start=True, render=lambda p: money(p["max_loss_usd"])),
        Col("pred", "Predicted", "r", render=lambda p: money(p["conservative_ev_usd"], signed=True)),
        Col("res", "Result", "r", emphasis=False,
            render=lambda p: "–" if p.get("pnl_usd") is None else money(p["pnl_usd"], signed=True),
            css=lambda p: tone(p.get("pnl_usd"))),
        Col("status", "Status", "l", group_start=True,
            render=lambda p: "Open" if p.get("pnl_usd") is None
            else f"Settled at {float(p['settlement_price']):,.2f}",
            css=lambda p: "muted" if p.get("pnl_usd") is None else ""),
    ], ordered, groups=[("", 3), ("Per lot, $", 3), ("", 1)]))


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
    return out
