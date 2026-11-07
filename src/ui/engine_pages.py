"""Christiania trade screens: Today's trades, 0DTE and Track record.

Everything shown here comes from the engine's frozen scans and picks. The UI
never computes or alters a recommendation; it only reads and explains.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import streamlit as st

from src.engine.chains import NY, parse_utc
from src.engine.ledger import conservative_pop, latest_scan, picks_with_outcomes, scorecard
from src.engine.pipeline import LANE_MAIN, LANE_ZERO_DTE
from src.engine.structures import FAMILY_LABELS
from src.ui.components import section_heading

REJECTION_LABELS = {
    "MODELS_DISAGREE": "the two forecast models disagree on profit",
    "EV_TOO_SMALL": "expected profit too small after costs",
    "RETURN_ON_RISK_TOO_LOW": "return on risk too low",
    "WIDE_SPREAD": "bid/ask spread too wide",
    "ONE_SIDED_QUOTE": "no two-sided quote on a leg",
    "LOW_OPEN_INTEREST": "too little open interest",
    "STALE_QUOTE": "quote too old",
    "MODEL_UNAVAILABLE": "not enough price history for the models",
    "NO_USABLE_EXPIRY": "no usable expiry in the chain",
    "NO_RISK_ARBITRAGE_SUSPECT": "suspect quotes (risk-free payoff)",
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


# ------------------------------------------------------------------ helpers
def md(text: str) -> str:
    """Escape dollar signs so Streamlit markdown does not render them as LaTeX."""
    return str(text).replace("$", "\\$")


def usd(value: Any, *, signed: bool = False) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    v = float(value)
    text = f"${abs(v):,.0f}"
    if v < 0:
        return f"−{text}"
    return f"+{text}" if signed and v > 0 else text


def pct(value: Any, digits: int = 0) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    return f"{float(value) * 100:.{digits}f}%"


def ny_time(value: Any) -> str:
    stamp = parse_utc(value)
    if stamp is None:
        return "—"
    local = stamp.astimezone(NY)
    return local.strftime("%a %d %b %H:%M") + " NY"


def minutes_ago(value: Any, now: datetime) -> float | None:
    stamp = parse_utc(value)
    return None if stamp is None else (now - stamp).total_seconds() / 60.0


def expiry_label(expiration: str, today: date) -> str:
    d = date.fromisoformat(expiration)
    days = (d - today).days
    when = "today" if days == 0 else "tomorrow" if days == 1 else f"{days} days"
    return f"{d.strftime('%d %b')} ({when})"


def contracts_for(max_loss: float, risk_budget: float | None) -> int | None:
    if not risk_budget or max_loss <= 0:
        return None
    return int(risk_budget // max_loss)


def limit_price(record: dict) -> float:
    """Net limit per share: the modelled fill, i.e. the worst price to accept."""
    return abs(float(record["entry_cash_usd"])) / 100.0


def why_text(c: dict) -> str:
    scores = c.get("scores", {})
    vol = scores.get("VOL_FORECAST", {}).get("ev_usd")
    emp = scores.get("EMPIRICAL", {}).get("ev_usd")
    imp = scores.get("IMPLIED", {}).get("ev_usd")
    parts = []
    if c.get("atm_iv") and c.get("forecast_vol"):
        rich = c["atm_iv"] > c["forecast_vol"]
        parts.append(
            f"Options price {pct(c['atm_iv'])} volatility; the stock's own forecast is "
            f"{pct(c['forecast_vol'])} — options look {'expensive' if rich else 'cheap'}."
        )
    parts.append(
        f"Volatility model expects {usd(vol, signed=True)}, price-history model "
        f"{usd(emp, signed=True)}. The score uses the worse of the two."
    )
    if imp is not None:
        parts.append(
            f"Priced at the market's own volatility the trade is worth {usd(imp, signed=True)} "
            "(about minus the costs) — the edge only exists if the forecast is right."
        )
    return " ".join(parts)


# -------------------------------------------------------------------- reads
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


# ------------------------------------------------------------- trade pages
def _scan_status(scan: dict, now: datetime, lane: str) -> None:
    age = minutes_ago(scan.get("asof_at"), now)
    line = (
        f"Last scan {ny_time(scan.get('asof_at'))}"
        + (f" ({age:.0f} min ago)" if age is not None and age < 600 else "")
        + f" · {scan.get('chains_scanned', 0)} underlyings · "
        f"{scan.get('structures_scored', 0):,} trades priced · "
        f"{scan.get('passed_count', 0)} pass"
    )
    st.caption(md(line))
    if scan.get("status") == "FAILED":
        st.error(f"The last scan failed: {scan.get('error_message')}")
    elif age is not None and age > STALE_SCAN_MINUTES:
        st.warning(
            "This scan is not fresh — prices have moved since. Treat these as a watch-list "
            "and re-quote everything before trading."
        )
    missing = scan.get("chains_without_history") or []
    if missing:
        st.caption(
            f"No price history yet for {', '.join(missing[:12])}"
            + ("…" if len(missing) > 12 else "") + " — these cannot pass until it arrives."
        )
    if lane == LANE_ZERO_DTE:
        st.caption("Scans run 09:45–15:45 NY on SPY/QQQ same-day and next-day expiries.")


def _trade_card(rank: int, c: dict, today: date, risk_budget: float | None) -> None:
    with st.container(border=True):
        shape = SHAPE_LABELS.get(c.get("shape"), c.get("family"))
        st.markdown(
            f"#### #{rank} · {c['underlying']} · {shape} · {expiry_label(c['expiration'], today)}"
        )
        st.markdown(f"**{c['description']}**")
        credit = float(c["entry_cash_usd"]) > 0
        pop = conservative_pop(c)
        m = st.columns(5)
        m[0].metric("You receive" if credit else "You pay", usd(abs(float(c["entry_cash_usd"]))))
        m[1].metric("Max loss", usd(c["max_loss_usd"]))
        m[2].metric("Expected profit", usd(c["conservative_ev_usd"], signed=True),
                    help="Worse of the two forecast models, after slippage and commission.")
        m[3].metric("Return on risk", pct(c["ev_per_risk"], 1))
        m[4].metric("Win chance", pct(pop),
                    help="Lower of the two forecast models' probability of any profit.")
        st.markdown(md(why_text(c)))
        notes = []
        if c.get("breakevens"):
            notes.append("Breakeven " + " / ".join(f"{b:g}" for b in c["breakevens"]))
        if c.get("spot"):
            notes.append(f"Underlying ≈ {float(c['spot']):,.2f}")
        n = contracts_for(float(c["max_loss_usd"]), risk_budget)
        if n is not None:
            notes.append(
                f"{n} contract{'s' if n != 1 else ''} fit your {usd(risk_budget)} risk limit"
                if n else f"Max loss exceeds your {usd(risk_budget)} risk limit"
            )
        if c.get("quote_age_seconds") is not None:
            notes.append(f"Quotes {float(c['quote_age_seconds']) / 60:.0f} min old")
        st.caption(md(" · ".join(notes)))
        if c.get("event_move_pct"):
            st.warning(
                f"The options price an event before expiry (≈ ±{c['event_move_pct']:.1f}% extra "
                "move, likely earnings). The models include it, but it is the main risk."
            )
        with st.expander("Order ticket"):
            legs = pd.DataFrame([
                {"Action": "Buy" if leg["side"] > 0 else "Sell",
                 "Option": f"{c['underlying']} {c['expiration']} {leg['strike']:g} "
                           f"{'Call' if leg['right'] == 'C' else 'Put'}",
                 "Bid": leg["bid"], "Ask": leg["ask"], "Assumed fill": leg["fill"]}
                for leg in c["legs"]
            ])
            st.dataframe(legs, hide_index=True, width="stretch")
            word = "credit" if credit else "debit"
            st.markdown(md(
                f"Enter as one combo order, limit **{limit_price(c):.2f} {word}** per share "
                f"({'do not accept less' if credit else 'do not pay more'}). Hold to expiry. "
                f"Commission assumed {usd(c['commission_usd'])}."
            ))


def _near_miss_table(items: list[dict], today: date) -> None:
    rows = [
        {"Underlying": c["underlying"],
         "Trade": f"{SHAPE_LABELS.get(c['shape'], c['family'])}: {c['description']}",
         "Expiry": expiry_label(c["expiration"], today),
         "Expected profit": usd(c["conservative_ev_usd"], signed=True),
         "Return on risk": pct(c["ev_per_risk"], 1),
         "Why not": REJECTION_LABELS.get(c.get("reject_reason"), c.get("reject_reason"))}
        for c in items
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_trades_page(lane: str, *, risk_budget: float | None, db_path=None,
                       now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    today = now.astimezone(NY).date()
    if lane == LANE_MAIN:
        section_heading(
            "Today's trades",
            "Defined-risk option trades ranked by expected profit per dollar at risk, after "
            "costs. Every trade shown here is logged and scored at expiry.",
        )
    else:
        section_heading(
            "0DTE",
            "Same-day and next-day expiries. Big swings, small edges: size this separately "
            "from the main trades.",
        )
    db_key = None if db_path is None else str(db_path)
    try:
        scan = _read_scan(lane, db_key)
    except Exception as exc:
        if _engine_tables_missing(exc):
            st.info("The trade engine has not been installed on this database yet "
                    "(schema v39 migration pending).")
            return
        st.error(f"Cannot read the trade engine: {type(exc).__name__}.")
        return
    if scan is None:
        st.info("No scan yet. The engine runs after every data-collection cycle during "
                "market hours.")
        return
    _scan_status(scan, now, lane)

    passed = scan.get("passed", [])
    top_n = int(scan.get("config", {}).get("top_n", 5))
    if not passed:
        st.markdown("### No trade clears the bar right now")
        rej = sorted(scan.get("rejections", {}).items(), key=lambda kv: -kv[1])[:4]
        if rej:
            st.write("Most common reasons: " + "; ".join(
                f"{REJECTION_LABELS.get(k, k)} ({v:,})" for k, v in rej) + ".")
        st.write("Doing nothing is a valid result. Closest candidates:")
        if scan.get("near_misses"):
            _near_miss_table(scan["near_misses"], today)
        return

    for i, c in enumerate(passed[:top_n], start=1):
        _trade_card(i, c, today, risk_budget)
    if len(passed) > top_n:
        with st.expander(f"{len(passed) - top_n} more trades that pass"):
            _near_miss_table(
                [{**c, "reject_reason": None} for c in passed[top_n:]], today
            )


# ------------------------------------------------------------ track record
def verdict(card) -> tuple[str, str]:
    if card.settled < 30:
        return ("info", f"Too early to judge: {card.settled} settled trade"
                f"{'s' if card.settled != 1 else ''}. Results mean little before about 30.")
    lo, hi = card.pnl_ci95_usd
    if lo > 0:
        return ("success", "Making money: the average trade is profitable with 95% confidence.")
    if hi < 0:
        return ("error", "Losing money: the average trade loses with 95% confidence. "
                "The models' edge is not showing up in real outcomes.")
    return ("warning", "Not distinguishable from zero yet. Keep collecting before risking more.")


def render_track_record_page(*, db_path=None) -> None:
    section_heading(
        "Track record",
        "Every trade the engine recommended, settled at expiry. This — not the model — "
        "decides whether the engine makes money.",
    )
    db_key = None if db_path is None else str(db_path)
    try:
        picks = _read_picks(db_key)
    except Exception as exc:
        if _engine_tables_missing(exc):
            st.info("The trade engine has not been installed on this database yet.")
            return
        st.error(f"Cannot read the track record: {type(exc).__name__}.")
        return
    lane = st.segmented_control("Lane", ["All", "Main", "0DTE"], default="All",
                                label_visibility="collapsed")
    if lane == "Main":
        picks = [p for p in picks if p["lane"] == LANE_MAIN]
    elif lane == "0DTE":
        picks = [p for p in picks if p["lane"] == LANE_ZERO_DTE]
    if not picks:
        st.info("No recommended trades yet.")
        return

    card = scorecard(picks)
    kind, text = verdict(card)
    getattr(st, kind)(text)
    m = st.columns(5)
    m[0].metric("Recommended", card.picks, help=f"{card.open} still open")
    m[1].metric("Settled P&L", usd(card.total_pnl_usd, signed=True))
    m[2].metric("Return on risk", pct(card.return_on_risk, 1))
    m[3].metric("Hit rate", pct(card.hit_rate),
                delta=None if card.predicted_hit_rate is None
                else f"predicted {pct(card.predicted_hit_rate)}", delta_color="off")
    m[4].metric("Model predicted", usd(card.predicted_ev_usd, signed=True),
                help="What the engine expected the settled trades to earn in total. "
                     "Compare with Settled P&L: a big gap means the models are miscalibrated.")
    if card.pnl_ci95_usd:
        lo, hi = card.pnl_ci95_usd
        st.caption(md(f"Average settled trade {usd(card.avg_pnl_usd, signed=True)} "
                      f"(95% range {usd(lo, signed=True)} to {usd(hi, signed=True)}). "
                      "One lot per trade; your actual sizing will differ."))

    settled = [p for p in picks if p.get("pnl_usd") is not None]
    if settled:
        frame = pd.DataFrame(
            {"date": [p["settlement_date"] for p in settled],
             "pnl": [float(p["pnl_usd"]) for p in settled]}
        ).groupby("date", as_index=True)["pnl"].sum().sort_index().cumsum()
        st.markdown("**Cumulative settled P&L (one lot per trade)**")
        st.line_chart(frame.rename("Cumulative P&L ($)"))

        by_family = pd.DataFrame([
            {"Family": FAMILY_LABELS.get(p["family"], p["family"]),
             "pnl": float(p["pnl_usd"]), "win": float(p["pnl_usd"]) > 0,
             "pred": float(p["conservative_ev_usd"])}
            for p in settled
        ]).groupby("Family").agg(Trades=("pnl", "size"), PnL=("pnl", "sum"),
                                 HitRate=("win", "mean"), Predicted=("pred", "sum"))
        by_family["PnL"] = by_family["PnL"].map(lambda v: usd(v, signed=True))
        by_family["Predicted"] = by_family["Predicted"].map(lambda v: usd(v, signed=True))
        by_family["HitRate"] = by_family["HitRate"].map(pct)
        st.markdown("**By trade type**")
        st.dataframe(by_family.rename(columns={"HitRate": "Hit rate"}), width="stretch")

    st.markdown("**All recommended trades**")
    rows = []
    for p in picks:
        r = p["record"]
        status = ("Open" if p.get("pnl_usd") is None
                  else f"Settled {p['settlement_price']:,.2f}")
        rows.append({
            "Recommended": ny_time(p["first_seen_at"]),
            "Lane": "0DTE" if p["lane"] == LANE_ZERO_DTE else "Main",
            "Underlying": p["underlying"],
            "Trade": f"{SHAPE_LABELS.get(p['shape'], p['family'])}: {r.get('description', '')}",
            "Expiry": p["expiration"],
            "Max loss": usd(p["max_loss_usd"]),
            "Predicted": usd(p["conservative_ev_usd"], signed=True),
            "Result": usd(p.get("pnl_usd"), signed=True) if p.get("pnl_usd") is not None else "—",
            "Status": status,
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
