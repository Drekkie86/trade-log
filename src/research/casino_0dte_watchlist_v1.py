"""Bounded, read-only speculative 0DTE watchlist from immutable market quotes.

These are observed contracts with a hypothetical stock-move payoff, NOT
strategy signals, positive-EV forecasts, executable prices or trade approval.
Never place orders, alter Main Engine ranking, or write Shadow outcomes here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo
import math
import sqlite3

from src.database.repository import resolve_db_path
from src.operations.sqlite_runtime import open_readonly_connection
from src.research.massive_underlying_observation_v1 import STOCK_PRICE_SOURCE
from src.research.strategy_competition_v1 import _fx_asof, _quote_time_asof
from src.research.shadow_intrinsic_admission_v1 import USD_COST_PER_CONTRACT_SIDE_MINOR

MAX_SNAPSHOT_SCAN = 80
MAX_UNDERLYINGS = 12
MAX_QUOTES_PER_SNAPSHOT = 2500
MAX_CANDIDATES = 10
MAX_CAPTURE_AGE_SECONDS = 600
MAX_QUOTE_SKEW_SECONDS = 15
MAX_STOCK_AGE_SECONDS = 600
MAX_FX_AGE_SECONDS = 172800
CASINO_BANKROLL_EUR = 500.0
CASINO_SINGLE_LOSS_CAP_EUR = 25.0
HYPOTHETICAL_MOVE_FRACTION = 0.05


@dataclass(frozen=True)
class CasinoWatchCandidate:
    underlying: str
    right: str
    expiration: str
    strike: float
    option_quote_id: int
    snapshot_id: int
    captured_at: str
    quote_at: str
    stock_source: str
    stock_price: float
    option_ask_usd: float
    multiplier: float
    spread_fraction: float
    indicative_max_loss_eur: float
    hypothetical_five_percent_pnl_usd: float
    hypothetical_return_multiple: float
    evidence_state: str = "WATCH_ONLY_NO_PREDICTIVE_EDGE_OR_BROKER_QUOTE"

    def display_row(self) -> dict[str, object]:
        return {
            "Symbol": self.underlying,
            "Contract": f"{self.expiration} {'Call' if self.right == 'C' else 'Put'} {self.strike:g}",
            "Indicative loss (€)": round(self.indicative_max_loss_eur, 2),
            "±5% move: hypothetical P&L ($)": round(self.hypothetical_five_percent_pnl_usd, 2),
            "±5% move: return on cost": f"{self.hypothetical_return_multiple:.1f}×",
            "Bid/ask width": f"{self.spread_fraction:.0%}",
            "Snapshot": self.captured_at,
            "Quote ID": self.option_quote_id,
        }


def _instant(raw: object) -> datetime:
    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("NAIVE_SOURCE_TIMESTAMP")
    return parsed.astimezone(UTC)


def _fresh_sourced_spot(row: sqlite3.Row, now: datetime) -> float | None:
    if str(row["underlying_source"]) != "FETCHED":
        return None
    if f"stock price source={STOCK_PRICE_SOURCE};" not in str(row["notes"] or ""):
        return None
    try:
        captured = _instant(row["captured_at"])
        stock_at = _instant(row["underlying_at"])
        age = (now - captured).total_seconds()
        stock_age = (captured - stock_at).total_seconds()
        value = float(row["underlying_price"])
    except (TypeError, ValueError, OverflowError):
        return None
    if not (0 <= age <= MAX_CAPTURE_AGE_SECONDS and
            0 <= stock_age <= MAX_STOCK_AGE_SECONDS and
            math.isfinite(value) and value > 0):
        return None
    if captured.astimezone(ZoneInfo("America/New_York")).date() != now.astimezone(
        ZoneInfo("America/New_York")
    ).date():
        return None
    return value


def load_casino_0dte_watchlist(
    db_path: str | Path | None = None, *, now: datetime | None = None
) -> tuple[CasinoWatchCandidate, ...]:
    """Return *research* candidates only from today's evidenced 0DTE quotes.

    Source timestamps, bid/ask, explicitly evidenced multiplier and timely FX
    are mandatory. A 5% spot move is a stress illustration, NOT a probability,
    expected return or execution recommendation. Missing data fails closed.
    """
    observed = datetime.now(UTC) if now is None else now
    if observed.tzinfo is None:
        raise ValueError("now must be timezone aware")
    observed = observed.astimezone(UTC)
    ny_now = observed.astimezone(ZoneInfo("America/New_York"))
    # Never surface expired contracts as a current-day watchlist.
    if (ny_now.weekday() >= 5 or not
            clock_time(9, 30) <= ny_now.time().replace(tzinfo=None) < clock_time(15, 55)):
        return ()
    ny_day = ny_now.date().isoformat()
    path = resolve_db_path(db_path)
    if not path.exists():
        return ()
    conn = open_readonly_connection(path)
    found: list[CasinoWatchCandidate] = []
    try:
        snapshots = conn.execute(
            """SELECT id,underlying,us_session_date,captured_at,underlying_at,
                      underlying_source,underlying_price,notes,research_run_id
               FROM market_snapshots WHERE us_session_date=?
               ORDER BY id DESC LIMIT ?""",
            (ny_day, MAX_SNAPSHOT_SCAN),
        ).fetchall()
        visited: set[str] = set()
        for snap in snapshots:
            symbol = str(snap["underlying"])
            if symbol in visited:
                continue
            visited.add(symbol)
            if len(visited) > MAX_UNDERLYINGS:
                break
            spot = _fresh_sourced_spot(snap, observed)
            if spot is None:
                continue
            fx, fx_at, _fx_source = _fx_asof(conn, str(snap["captured_at"]))
            try:
                fx_age = (_instant(snap["captured_at"]) - _instant(fx_at)).total_seconds()
            except (ValueError, TypeError):
                continue
            if (fx is None or not math.isfinite(fx) or fx <= 0 or
                    not 0 <= fx_age <= MAX_FX_AGE_SECONDS):
                continue
            quotes = conn.execute(
                """SELECT oq.id,oq.right,oq.strike,oq.bid,oq.ask,oq.quote_at,
                          oq.shares_per_contract AS quote_multiplier,
                          (SELECT CASE WHEN COUNT(*)=1 THEN MAX(lrc.shares_per_contract)
                                       ELSE NULL END
                           FROM listing_reference_contracts AS lrc
                           WHERE lrc.research_run_id=? AND lrc.provider='MASSIVE'
                             AND lrc.underlying=? AND lrc.expiration=oq.expiration
                             AND lrc.strike=oq.strike AND lrc.right=oq.right
                          ) AS reference_multiplier
                   FROM option_quotes AS oq
                   WHERE oq.snapshot_id=? AND oq.expiration=?
                   ORDER BY oq.id LIMIT ?""",
                (snap["research_run_id"], symbol, snap["id"], ny_day,
                 MAX_QUOTES_PER_SNAPSHOT + 1),
            ).fetchall()
            if len(quotes) > MAX_QUOTES_PER_SNAPSHOT:
                continue
            for quote in quotes:
                try:
                    right = str(quote["right"])
                    strike = float(quote["strike"])
                    bid, ask = float(quote["bid"]), float(quote["ask"])
                    if right not in {"C", "P"} or not all(math.isfinite(x) for x in
                                                              (strike, bid, ask)):
                        continue
                    if strike <= 0 or bid < 0 or not (0.05 <= ask and ask >= bid):
                        continue
                    if not (spot * 0.97 <= strike <= spot * 1.03):
                        continue
                    spread = (ask - bid) / ask
                    if spread > 0.25:
                        continue
                    raw_q, raw_ref = quote["quote_multiplier"], quote["reference_multiplier"]
                    if raw_q is None and raw_ref is None:
                        continue
                    if raw_q is not None and raw_ref is not None and float(raw_q) != float(raw_ref):
                        continue
                    multiplier = float(raw_q if raw_q is not None else raw_ref)
                    if not math.isfinite(multiplier) or multiplier <= 0:
                        continue
                    quote_instant = _instant(_quote_time_asof(quote["quote_at"]))
                    captured = _instant(snap["captured_at"])
                    if not 0 <= (captured - quote_instant).total_seconds() <= MAX_QUOTE_SKEW_SECONDS:
                        continue
                    # Assumed one-contract, two-side fees are a screening floor.
                    # Actual slippage, taxes, broker fills and exercise risks
                    # are unknown; do not mark this trade affordable or approved.
                    assumed_fees = 2.0 * USD_COST_PER_CONTRACT_SIDE_MINOR / 100.0
                    indicative_cost_usd = ask * multiplier + assumed_fees
                    loss_eur = indicative_cost_usd / fx
                    if not 0 < loss_eur <= min(CASINO_BANKROLL_EUR, CASINO_SINGLE_LOSS_CAP_EUR):
                        continue
                    stress_spot = spot * (1.05 if right == "C" else 0.95)
                    payoff = max(0.0, stress_spot - strike) if right == "C" else max(
                        0.0, strike - stress_spot
                    )
                    stress_pnl_usd = payoff * multiplier - indicative_cost_usd
                    if stress_pnl_usd <= 0:
                        continue
                    found.append(CasinoWatchCandidate(
                        underlying=symbol, right=right, expiration=ny_day,
                        strike=strike, option_quote_id=int(quote["id"]),
                        snapshot_id=int(snap["id"]),
                        captured_at=str(snap["captured_at"]),
                        quote_at=str(quote["quote_at"]),
                        stock_source=STOCK_PRICE_SOURCE, stock_price=spot,
                        option_ask_usd=ask, multiplier=multiplier,
                        spread_fraction=spread,
                        indicative_max_loss_eur=loss_eur,
                        hypothetical_five_percent_pnl_usd=stress_pnl_usd,
                        hypothetical_return_multiple=stress_pnl_usd / indicative_cost_usd,
                    ))
                except (ValueError, TypeError, OverflowError):
                    continue
    finally:
        conn.close()
    # Stop multiple neighbouring strikes of the same symbol and direction
    # occupying the whole list; these are not independent opportunities.
    found.sort(key=lambda x: (-x.hypothetical_return_multiple,
                              x.spread_fraction, x.indicative_max_loss_eur,
                              x.option_quote_id))
    used: dict[tuple[str, str], int] = {}
    final = []
    for candidate in found:
        key = (candidate.underlying, candidate.right)
        if used.get(key, 0) >= 2:
            continue
        final.append(candidate)
        used[key] = used.get(key, 0) + 1
        if len(final) >= MAX_CANDIDATES:
            break
    return tuple(final)
