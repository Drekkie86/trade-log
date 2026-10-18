"""As-of quote-IV variation proxy for opportunity ranking.

Uses only earlier, distinct quote timestamps for the SAME contract and US
session. Adjacent nonoverlapping pairs bound historical IV instability before
the signal. This is a conservative proxy, NOT a direct observation of latent
NBBO midpoint measurement error or independent vendor corroboration.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime
from statistics import stdev
from typing import Mapping

from scipy.stats import chi2

MIN_PAIRS = 6
MAX_HISTORY_ROWS = 80
MAX_QUOTE_AGE_SECONDS = 180
MIN_INDEPENDENT_GAP_SECONDS = 300
MAX_PAIR_GAP_SECONDS = 2100
MAX_SPOT_PAIR_MOVE_FRACTION = 0.005


def _instant(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _estimate(rows: list[tuple[datetime, float, float]], *, asof: datetime) -> tuple[float, int] | None:
    """Estimate an upper 95% bound under an explicit normal-difference proxy.

    Oldest-to-newest nonoverlapping pairs do not reuse the same quote.
    Distinct quote timestamps and stable underlying limit stale/spot effects.
    Real IV changes may inflate this estimate; serial/structural bias is not
    independently measured, so this remains a quote-instability proxy.
    """
    unique: list[tuple[datetime, float, float]] = []
    seen: set[datetime] = set()
    for t, iv, spot in sorted(rows):
        if not (t < asof and 0.02 <= iv <= 5 and spot > 0):
            continue
        if t in seen or (unique and (t - unique[-1][0]).total_seconds() < MIN_INDEPENDENT_GAP_SECONDS):
            continue
        seen.add(t)
        unique.append((t, iv, spot))

    differences: list[float] = []
    for i in range(0, len(unique) - 1, 2):
        older, newer = unique[i], unique[i + 1]
        gap = (newer[0] - older[0]).total_seconds()
        spot_move = abs(newer[2] / older[2] - 1)
        if gap <= MAX_PAIR_GAP_SECONDS and spot_move <= MAX_SPOT_PAIR_MOVE_FRACTION:
            differences.append(newer[1] - older[1])

    n = len(differences)
    if n < MIN_PAIRS:
        return None
    # Upper confidence limit on one-quote sigma, assuming paired Gaussian
    # differences have variance 2*sigma^2; never call this an alpha p-value.
    q = float(chi2.ppf(0.05, n - 1))
    if not math.isfinite(q) or q <= 0:
        return None
    sigma = (stdev(differences) / math.sqrt(2)) * math.sqrt((n - 1) / q)
    if not math.isfinite(sigma) or sigma < 0:
        return None
    return sigma, n


def prior_iv_variation_for_leg(
    conn: sqlite3.Connection, option_quote_id: int
) -> tuple[float, int] | None:
    current = conn.execute(
        """SELECT oq.option_symbol, oq.expiration, oq.right, oq.strike,
                  oq.quote_at, ms.captured_at, ms.us_session_date, ms.id AS snapshot_id
           FROM option_quotes oq JOIN market_snapshots ms ON ms.id=oq.snapshot_id
           WHERE oq.id=?""",
        (option_quote_id,),
    ).fetchone()
    if current is None or not current["option_symbol"]:
        return None
    asof = _instant(current["captured_at"])
    quote_at = _instant(current["quote_at"])
    if asof is None or quote_at is None or quote_at > asof or (asof - quote_at).total_seconds() > MAX_QUOTE_AGE_SECONDS:
        return None

    rows = conn.execute(
        """SELECT oq.quote_at, ms.captured_at, ms.underlying_price AS spot,
                  pmo.implied_volatility AS iv, oq.bid, oq.ask
           FROM option_quotes oq
           JOIN market_snapshots ms ON ms.id=oq.snapshot_id
           JOIN provider_model_observations pmo ON pmo.option_quote_id=oq.id
           WHERE oq.option_symbol=?
             AND ms.us_session_date=?
             AND ms.id < ?
             AND oq.expiration=? AND oq.right=? AND oq.strike=?
             AND pmo.provider='THETADATA'
             AND pmo.id=(SELECT MAX(p2.id) FROM provider_model_observations p2
                         WHERE p2.option_quote_id=oq.id AND p2.provider='THETADATA')
           ORDER BY oq.id DESC LIMIT ?""",
        (current["option_symbol"], current["us_session_date"],
         current["snapshot_id"], current["expiration"], current["right"],
         current["strike"], MAX_HISTORY_ROWS),
    ).fetchall()
    usable: list[tuple[datetime, float, float]] = []
    for row in rows:
        ts = _instant(row["quote_at"])
        capture = _instant(row["captured_at"])
        if ts is None or capture is None or ts > capture or capture >= asof:
            continue
        if (capture - ts).total_seconds() > MAX_QUOTE_AGE_SECONDS:
            continue
        if row["bid"] is None or row["ask"] is None:
            continue
        bid, ask = float(row["bid"]), float(row["ask"])
        if bid < 0 or ask < bid or ask == 0:
            continue
        try:
            usable.append((ts, float(row["iv"]), float(row["spot"])))
        except (TypeError, ValueError):
            continue
    return _estimate(usable, asof=asof)


def historical_quote_variation(
    conn: sqlite3.Connection, option_quote_ids: list[int]
) -> tuple[dict[int, float], dict[int, int]]:
    sigmas: dict[int, float] = {}
    sample_sizes: dict[int, int] = {}
    for qid in dict.fromkeys(option_quote_ids):
        estimate = prior_iv_variation_for_leg(conn, qid)
        if estimate is None:
            continue
        sigmas[qid], sample_sizes[qid] = estimate
    return sigmas, sample_sizes
