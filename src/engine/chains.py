"""Option chains for the engine: loading, forward, implied vol and delta.

The engine prices from the snapshot's own quotes. The forward comes from
put-call parity on near-the-money strikes, implied volatility and delta are
solved with Black-76 against that forward. Nothing is borrowed from another
snapshot or another provider, so every number is internally consistent.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

from scipy.optimize import brentq

NY = ZoneInfo("America/New_York")
RISK_FREE_RATE = 0.04
EXPIRY_CLOSE = time(16, 0)


@dataclass(frozen=True)
class Quote:
    right: str
    strike: float
    expiration: str
    bid: float | None
    ask: float | None
    quote_at: str | None = None
    open_interest: int | None = None
    iv: float | None = None
    delta: float | None = None

    @property
    def two_sided(self) -> bool:
        return (
            self.bid is not None and self.ask is not None
            and self.bid > 0 and self.ask >= self.bid
        )

    @property
    def mid(self) -> float | None:
        return 0.5 * (self.bid + self.ask) if self.two_sided else None

    @property
    def relative_spread(self) -> float | None:
        m = self.mid
        return (self.ask - self.bid) / m if m else None


@dataclass(frozen=True)
class Expiry:
    expiration: str
    calendar_years: float
    forward: float | None
    atm_iv: float | None
    quotes: tuple[Quote, ...] = field(repr=False)


@dataclass(frozen=True)
class Chain:
    underlying: str
    captured_at: datetime
    snapshot_id: int | None
    spot: float | None
    expiries: tuple[Expiry, ...]
    source: str


def parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC)


def calendar_years_to_expiry(asof: datetime, expiration: str) -> float:
    expiry = datetime.combine(date.fromisoformat(expiration), EXPIRY_CLOSE, NY)
    seconds = (expiry.astimezone(UTC) - asof.astimezone(UTC)).total_seconds()
    return max(seconds, 0.0) / (365.0 * 86400.0)


# --------------------------------------------------------------------- Black-76
def _ncdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def black76_price(right: str, forward: float, strike: float, years: float,
                  vol: float, rate: float = RISK_FREE_RATE) -> float:
    df = math.exp(-rate * years)
    if years <= 0 or vol <= 0:
        intrinsic = max(0.0, forward - strike) if right == "C" else max(0.0, strike - forward)
        return df * intrinsic
    sd = vol * math.sqrt(years)
    d1 = (math.log(forward / strike) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if right == "C":
        return df * (forward * _ncdf(d1) - strike * _ncdf(d2))
    return df * (strike * _ncdf(-d2) - forward * _ncdf(-d1))


def black76_delta(right: str, forward: float, strike: float, years: float,
                  vol: float, rate: float = RISK_FREE_RATE) -> float:
    sd = vol * math.sqrt(years)
    d1 = (math.log(forward / strike) + 0.5 * sd * sd) / sd
    df = math.exp(-rate * years)
    return df * _ncdf(d1) if right == "C" else -df * _ncdf(-d1)


def implied_vol(right: str, price: float, forward: float, strike: float,
                years: float, rate: float = RISK_FREE_RATE) -> float | None:
    if years <= 0 or price <= 0 or forward <= 0 or strike <= 0:
        return None
    df = math.exp(-rate * years)
    intrinsic = df * (max(0.0, forward - strike) if right == "C" else max(0.0, strike - forward))
    if price <= intrinsic + 1e-9 or price >= df * (forward if right == "C" else strike):
        return None
    f = lambda v: black76_price(right, forward, strike, years, v, rate) - price
    try:
        return float(brentq(f, 1e-4, 8.0, xtol=1e-7, maxiter=100))
    except (ValueError, RuntimeError):
        return None


def parity_forward(quotes: Sequence[Quote], years: float,
                   rate: float = RISK_FREE_RATE) -> float | None:
    """Median parity forward over the three strikes where |C - P| is smallest."""
    calls = {q.strike: q for q in quotes if q.right == "C" and q.two_sided}
    puts = {q.strike: q for q in quotes if q.right == "P" and q.two_sided}
    pairs = sorted(
        (abs(calls[k].mid - puts[k].mid), k) for k in calls.keys() & puts.keys()
    )
    if not pairs:
        return None
    growth = math.exp(rate * years)
    estimates = sorted(k + (calls[k].mid - puts[k].mid) * growth for _, k in pairs[:3])
    f = estimates[len(estimates) // 2]
    return f if f > 0 else None


def enrich_expiry(expiration: str, quotes: Sequence[Quote], asof: datetime) -> Expiry:
    """Forward, per-contract IV/delta (OTM side) and ATM IV for one expiry."""
    years = calendar_years_to_expiry(asof, expiration)
    forward = parity_forward(quotes, years) if years > 0 else None
    if forward is None:
        return Expiry(expiration, years, None, None, tuple(quotes))
    enriched: list[Quote] = []
    for q in quotes:
        iv = delta = None
        if q.two_sided:
            iv = implied_vol(q.right, q.mid, forward, q.strike, years)
            if iv is not None:
                delta = black76_delta(q.right, forward, q.strike, years, iv)
        enriched.append(replace(q, iv=iv, delta=delta))
    # ATM IV: average of call and put IV at the strike nearest the forward.
    by_strike: dict[float, list[float]] = {}
    for q in enriched:
        if q.iv is not None:
            by_strike.setdefault(q.strike, []).append(q.iv)
    atm_iv = None
    if by_strike:
        k = min(by_strike, key=lambda s: abs(s - forward))
        if abs(k - forward) / forward < 0.05:
            atm_iv = sum(by_strike[k]) / len(by_strike[k])
    return Expiry(expiration, years, forward, atm_iv, tuple(enriched))


def atm_implied_vol(quotes: Sequence[Quote], years: float,
                    rate: float = RISK_FREE_RATE) -> float | None:
    """ATM implied vol of one expiry without enriching every contract.

    Same definition as ``enrich_expiry``: the forward from put-call parity, then
    the average of the call and put IVs at the strike nearest the forward (within
    5 % of it). Two to four solves instead of one per contract.
    """
    if years <= 0:
        return None
    forward = parity_forward(quotes, years, rate)
    if forward is None:
        return None
    by_strike: dict[float, list[Quote]] = {}
    for q in quotes:
        if q.two_sided:
            by_strike.setdefault(q.strike, []).append(q)
    for k in sorted(by_strike, key=lambda s: abs(s - forward)):
        if abs(k - forward) / forward >= 0.05:
            return None
        ivs = [iv for iv in (implied_vol(q.right, q.mid, forward, k, years, rate)
                             for q in by_strike[k]) if iv is not None]
        if ivs:
            return sum(ivs) / len(ivs)
    return None


def constant_maturity_point(quotes: Iterable[Quote], asof: datetime, *,
                            min_dte: int, max_dte: int) -> float | None:
    """30-day constant-maturity implied vol of a chain at ``asof`` (None when the
    chain cannot support it). Used to build the implied-variance history."""
    from src.engine.models import constant_maturity_iv

    session_day = asof.astimezone(NY).date()
    grouped: dict[str, list[Quote]] = {}
    for q in quotes:
        dte = (date.fromisoformat(q.expiration) - session_day).days
        if min_dte <= dte <= max_dte:
            grouped.setdefault(q.expiration, []).append(q)
    points = []
    for exp, qs in grouped.items():
        years = calendar_years_to_expiry(asof, exp)
        iv = atm_implied_vol(qs, years)
        if iv is not None:
            points.append((years, iv))
    return constant_maturity_iv(points)


def build_chain(underlying: str, captured_at: datetime, quotes: Iterable[Quote], *,
                snapshot_id: int | None, spot: float | None, source: str,
                min_dte: int, max_dte: int) -> Chain:
    session_day = captured_at.astimezone(NY).date()
    grouped: dict[str, list[Quote]] = {}
    for q in quotes:
        dte = (date.fromisoformat(q.expiration) - session_day).days
        if min_dte <= dte <= max_dte:
            grouped.setdefault(q.expiration, []).append(q)
    expiries = tuple(
        enrich_expiry(exp, grouped[exp], captured_at) for exp in sorted(grouped)
    )
    if spot is None:
        fwd = next((e for e in expiries if e.forward), None)
        if fwd is not None:
            spot = fwd.forward * math.exp(-RISK_FREE_RATE * fwd.calendar_years)
    return Chain(underlying.upper(), captured_at, snapshot_id, spot, expiries, source)


# ------------------------------------------------------------------ DB loading
def load_snapshot_quotes(conn: sqlite3.Connection, snapshot_id: int) -> list[Quote]:
    rows = conn.execute(
        """SELECT right, strike, expiration, bid, ask, quote_at, open_interest
           FROM option_quotes WHERE snapshot_id=?""",
        (snapshot_id,),
    ).fetchall()
    return [
        Quote(str(r["right"]), float(r["strike"]), str(r["expiration"]),
              r["bid"], r["ask"], _theta_timestamp_utc(r["quote_at"]),
              r["open_interest"])
        for r in rows
    ]


def latest_snapshots(conn: sqlite3.Connection, *, asof: datetime,
                     max_age: timedelta) -> list[sqlite3.Row]:
    """Newest ThetaData snapshot per underlying captured within ``max_age``."""
    floor = (asof - max_age).astimezone(UTC).isoformat().replace("+00:00", "Z")
    return conn.execute(
        """SELECT s.id, s.underlying, s.captured_at, s.underlying_price
           FROM market_snapshots s
           JOIN (SELECT underlying, MAX(id) AS id FROM market_snapshots
                 WHERE provider='THETADATA' AND captured_at>=?
                 GROUP BY underlying) latest ON latest.id = s.id
           ORDER BY s.underlying""",
        (floor,),
    ).fetchall()


def load_main_chains(conn: sqlite3.Connection, *, asof: datetime, max_age: timedelta,
                     min_dte: int, max_dte: int) -> list[Chain]:
    chains: list[Chain] = []
    for row in latest_snapshots(conn, asof=asof, max_age=max_age):
        captured = parse_utc(row["captured_at"])
        if captured is None:
            continue
        chains.append(build_chain(
            str(row["underlying"]), captured,
            load_snapshot_quotes(conn, int(row["id"])),
            snapshot_id=int(row["id"]), spot=row["underlying_price"],
            source="THETADATA_SNAPSHOT", min_dte=min_dte, max_dte=max_dte,
        ))
    return chains


# ------------------------------------------------------------- live (0DTE)
def _theta_timestamp_utc(raw: Any) -> str | None:
    """ThetaData v3 timestamps are naive America/New_York."""
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=NY)
    return stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def quotes_from_theta_rows(rows: Iterable[dict[str, Any]]) -> list[Quote]:
    out: list[Quote] = []
    for r in rows:
        bid, ask = r.get("bid"), r.get("ask")
        try:
            bid = None if bid is None else float(bid)
            ask = None if ask is None else float(ask)
        except (TypeError, ValueError):
            bid = ask = None
        out.append(Quote(
            str(r["right"]), float(r["strike"]), str(r["expiration"]),
            bid, ask, _theta_timestamp_utc(r.get("raw_timestamp")),
        ))
    return out


def fetch_live_chain(theta_client, symbol: str, *, asof: datetime,
                     min_dte: int, max_dte: int) -> Chain:
    from src.research.thetadata_live_adapter import fetch_live_quote_rows

    rows = fetch_live_quote_rows(theta_client, symbol)
    return build_chain(symbol, asof, quotes_from_theta_rows(rows), snapshot_id=None,
                       spot=None, source="THETADATA_LIVE", min_dte=min_dte, max_dte=max_dte)
