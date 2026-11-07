"""Persistence for scans, picks, outcomes and real trades, plus the read models.

Picks: once per session per lane, the first completed scan at or after the
decision time freezes its best structure per underlying (at most top_n). Later
scans update the screen, not the ledger. Picks settle at expiry at intrinsic
value from the ThetaData EOD close. The track record is computed only from
these frozen records, clustered by expiry date, so it cannot be flattered after
the fact.

Trades: what the operator actually did, recorded against a candidate with the
real fill. Closed by hand or settled at expiry like a pick.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from src.engine.chains import NY
from src.engine.history import settlement_price
from src.engine.pipeline import NO_EARNINGS_SYMBOLS, ScanResult

STORED_PASSED = 50
SETTLE_AFTER = time(16, 15)
NEAR_STRIKE_FRACTION = 0.001          # |close - short strike| < 0.1 % of the close
MIN_EXPIRY_DAYS_FOR_VERDICT = 60
BOOTSTRAP_REPS = 2000
CANDIDATE_RETENTION_DAYS = 30
ETF_GROUP = "Index/sector ETFs"


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(_clean(value), sort_keys=True, allow_nan=False, default=str)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def name_group(underlying: str) -> str:
    return ETF_GROUP if underlying.upper() in NO_EARNINGS_SYMBOLS else underlying.upper()


# ------------------------------------------------------------------- writes
def _decision_taken(conn: sqlite3.Connection, lane: str, session_date: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM engine_scans WHERE lane=? AND session_date=? AND decision=1 LIMIT 1",
        (lane, session_date),
    ).fetchone() is not None


def record_scan(conn: sqlite3.Connection, result: ScanResult, *, completed_at: datetime) -> int:
    local = result.asof.astimezone(NY)
    session_date = local.date().isoformat()
    decision = (local.time() >= result.config.decision_time
                and not _decision_taken(conn, result.lane, session_date))
    with conn:
        cur = conn.execute(
            """INSERT INTO engine_scans
               (lane, session_date, asof_at, completed_at, status, decision, engine_version,
                config_json, chains_scanned, structures_scored, passed_count, rejections_json,
                chains_without_history_json, chains_blocked_json)
               VALUES (?, ?, ?, ?, 'COMPLETED', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (result.lane, session_date, _iso(result.asof), _iso(completed_at), int(decision),
             result.engine_version, _json(result.config.as_dict()), result.chains_scanned,
             result.structures_scored, len(result.passed), _json(dict(result.rejections)),
             _json(sorted(set(result.chains_without_history))), _json(result.chains_blocked)),
        )
        scan_id = int(cur.lastrowid)
        for kind, items in (("PASSED", result.passed[:STORED_PASSED]),
                            ("NEAR_MISS", result.near_misses)):
            for rank, c in enumerate(items, start=1):
                conn.execute(
                    """INSERT INTO engine_candidates
                       (scan_id, kind, rank, underlying, expiration, family, structure_key, record_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (scan_id, kind, rank, c.underlying, c.expiration, c.family,
                     c.structure_key, _json(c.to_record())),
                )
        if decision:
            for c in result.picks:
                conn.execute(
                    """INSERT OR IGNORE INTO engine_picks
                       (lane, session_date, underlying, expiration, family, shape, structure_key,
                        first_scan_id, first_seen_at, entry_cash_usd, max_loss_usd,
                        conservative_ev_usd, record_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (c.lane, session_date, c.underlying, c.expiration, c.family, c.shape,
                     c.structure_key, scan_id, _iso(result.asof), c.entry_cash_usd,
                     c.max_loss_usd, c.conservative_ev_usd, _json(c.to_record())),
                )
    return scan_id


def record_failed_scan(conn: sqlite3.Connection, *, lane: str, asof: datetime,
                       config: dict, error: BaseException, engine_version: str) -> int:
    with conn:
        cur = conn.execute(
            """INSERT INTO engine_scans
               (lane, session_date, asof_at, completed_at, status, engine_version, config_json,
                rejections_json, chains_without_history_json, error_message)
               VALUES (?, ?, ?, ?, 'FAILED', ?, ?, '{}', '[]', ?)""",
            (lane, asof.astimezone(NY).date().isoformat(), _iso(asof), _iso(datetime.now(UTC)),
             engine_version, _json(config), f"{type(error).__name__}: {error}"[:2000]),
        )
    return int(cur.lastrowid)


def payoff_per_share(record: dict, price: float) -> float:
    payoff = 0.0
    for leg in record["legs"]:
        k = float(leg["strike"])
        intrinsic = max(0.0, price - k) if leg["right"] == "C" else max(0.0, k - price)
        payoff += int(leg["side"]) * intrinsic
    return payoff


def pick_pnl_at(record: dict, price: float) -> float:
    """Hold-to-expiry P&L of a frozen pick at one settlement price, one lot."""
    return (payoff_per_share(record, price) * 100.0 + float(record["entry_cash_usd"])
            - float(record["commission_usd"]))


def near_short_strike(record: dict, price: float) -> bool:
    shorts = [float(l["strike"]) for l in record["legs"] if int(l["side"]) < 0]
    return any(abs(price - k) < NEAR_STRIKE_FRACTION * price for k in shorts)


def settle_due_picks(conn: sqlite3.Connection, *, now: datetime) -> int:
    local = now.astimezone(NY)
    rows = conn.execute(
        """SELECT p.id, p.underlying, p.expiration, p.record_json FROM engine_picks p
           LEFT JOIN engine_pick_outcomes o ON o.pick_id = p.id
           WHERE o.pick_id IS NULL AND p.expiration <= ?""",
        (local.date().isoformat(),),
    ).fetchall()
    settled = 0
    for r in rows:
        expiration = str(r["expiration"])
        if expiration == local.date().isoformat() and local.time() < SETTLE_AFTER:
            continue
        found = settlement_price(conn, str(r["underlying"]), expiration)
        if found is None:
            continue
        record = json.loads(r["record_json"])
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO engine_pick_outcomes
                   (pick_id, settled_at, settlement_date, settlement_price, settlement_source,
                    settlement_after_hours, near_strike, pnl_usd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (int(r["id"]), _iso(now), expiration, found.price, found.source,
                 int(found.after_hours), int(near_short_strike(record, found.price)),
                 round(pick_pnl_at(record, found.price), 2)),
            )
        settled += 1
    return settled


def record_trade(conn: sqlite3.Connection, record: dict, *, lots: int, fill_per_share: float,
                 commission_usd: float, taken_at: datetime, note: str | None = None,
                 pick_id: int | None = None) -> int:
    """Store a trade the operator took. ``fill_per_share``: net credit (+) or debit (-)."""
    if lots <= 0:
        raise ValueError("lots must be positive")
    modelled = float(record["entry_cash_usd"])
    if modelled > 0 and fill_per_share < 0 or modelled < 0 and fill_per_share > 0:
        raise ValueError("fill sign must match the structure: credit received (+) or debit paid (-)")
    width_loss = float(record["max_loss_usd"])
    # Max loss at the real fill: modelled max loss shifted by the fill difference.
    max_loss = max(1.0, (width_loss - (fill_per_share * 100 - float(record["entry_cash_usd"]))) * lots)
    with conn:
        cur = conn.execute(
            """INSERT INTO engine_trades
               (pick_id, taken_at, lane, underlying, expiration, family, shape, structure_key,
                lots, fill_per_share, commission_usd, max_loss_usd, note, record_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pick_id, _iso(taken_at), record["lane"], record["underlying"], record["expiration"],
             record["family"], record["shape"], record["structure_key"], int(lots),
             float(fill_per_share), float(commission_usd), round(max_loss, 2), note, _json(record)),
        )
    return int(cur.lastrowid)


def _trade_pnl(trade: sqlite3.Row | dict, cash_per_share_at_close: float, close_commission: float) -> float:
    lots = int(trade["lots"])
    return round((float(trade["fill_per_share"]) + cash_per_share_at_close) * 100.0 * lots
                 - float(trade["commission_usd"]) - close_commission, 2)


def close_trade(conn: sqlite3.Connection, trade_id: int, *, cash_per_share: float,
                commission_usd: float, closed_at: datetime, underlying_price: float | None = None) -> float:
    """Manual close. ``cash_per_share``: cash received (+) or paid (-) to close, per share."""
    trade = conn.execute("SELECT * FROM engine_trades WHERE id=?", (trade_id,)).fetchone()
    if trade is None:
        raise ValueError(f"unknown trade {trade_id}")
    pnl = _trade_pnl(trade, cash_per_share, commission_usd)
    with conn:
        conn.execute(
            """INSERT INTO engine_trade_closes
               (trade_id, closed_at, kind, cash_per_share, underlying_price, commission_usd, pnl_usd)
               VALUES (?, ?, 'MANUAL', ?, ?, ?, ?)""",
            (trade_id, _iso(closed_at), float(cash_per_share), underlying_price,
             float(commission_usd), pnl),
        )
    return pnl


def settle_due_trades(conn: sqlite3.Connection, *, now: datetime) -> int:
    local = now.astimezone(NY)
    rows = conn.execute(
        """SELECT t.* FROM engine_trades t LEFT JOIN engine_trade_closes c ON c.trade_id = t.id
           WHERE c.trade_id IS NULL AND t.expiration <= ?""",
        (local.date().isoformat(),),
    ).fetchall()
    settled = 0
    for t in rows:
        expiration = str(t["expiration"])
        if expiration == local.date().isoformat() and local.time() < SETTLE_AFTER:
            continue
        found = settlement_price(conn, str(t["underlying"]), expiration)
        if found is None:
            continue
        payoff = payoff_per_share(json.loads(t["record_json"]), found.price)
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO engine_trade_closes
                   (trade_id, closed_at, kind, cash_per_share, underlying_price, commission_usd, pnl_usd)
                   VALUES (?, ?, 'EXPIRY', ?, ?, 0, ?)""",
                (int(t["id"]), _iso(now), payoff, found.price, _trade_pnl(t, payoff, 0.0)),
            )
        settled += 1
    return settled


def prune_candidates(conn: sqlite3.Connection, *, now: datetime,
                     keep_days: int = CANDIDATE_RETENTION_DAYS) -> int:
    """Drop stored candidates of old non-decision scans; picks and outcomes stay."""
    cutoff = (now.astimezone(NY).date().toordinal() - keep_days)
    cutoff_date = date.fromordinal(cutoff).isoformat()
    with conn:
        cur = conn.execute(
            """DELETE FROM engine_candidates WHERE scan_id IN
               (SELECT id FROM engine_scans WHERE session_date < ? AND decision = 0)""",
            (cutoff_date,),
        )
    return int(cur.rowcount)


# -------------------------------------------------------------------- reads
def _scan_dict(row: sqlite3.Row) -> dict:
    scan = dict(row)
    scan["rejections"] = json.loads(scan.pop("rejections_json") or "{}")
    scan["chains_without_history"] = json.loads(scan.pop("chains_without_history_json") or "[]")
    scan["chains_blocked"] = json.loads(scan.pop("chains_blocked_json") or "{}")
    scan["config"] = json.loads(scan.pop("config_json") or "{}")
    return scan


def latest_scan(conn: sqlite3.Connection, lane: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM engine_scans WHERE lane=? ORDER BY id DESC LIMIT 1", (lane,)
    ).fetchone()
    if row is None:
        return None
    scan = _scan_dict(row)
    cands = conn.execute(
        "SELECT kind, rank, record_json FROM engine_candidates WHERE scan_id=? ORDER BY kind, rank",
        (scan["id"],),
    ).fetchall()
    scan["passed"] = [json.loads(c["record_json"]) for c in cands if c["kind"] == "PASSED"]
    scan["near_misses"] = [json.loads(c["record_json"]) for c in cands if c["kind"] == "NEAR_MISS"]
    return scan


def session_picks(conn: sqlite3.Connection, lane: str, session_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM engine_picks WHERE lane=? AND session_date=? ORDER BY id", (lane, session_date)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["record"] = json.loads(d.pop("record_json"))
        out.append(d)
    return out


def picks_with_outcomes(conn: sqlite3.Connection, lane: str | None = None) -> list[dict]:
    sql = """SELECT p.*, o.settled_at, o.settlement_date, o.settlement_price, o.settlement_source,
                    o.settlement_after_hours, o.near_strike, o.pnl_usd
             FROM engine_picks p LEFT JOIN engine_pick_outcomes o ON o.pick_id = p.id"""
    params: tuple = ()
    if lane:
        sql += " WHERE p.lane=?"
        params = (lane,)
    sql += " ORDER BY p.first_seen_at DESC, p.id DESC"
    out = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(r)
        d["record"] = json.loads(d.pop("record_json"))
        out.append(d)
    return out


def trades_with_closes(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT t.*, c.closed_at, c.kind AS close_kind, c.cash_per_share AS close_cash_per_share,
                  c.underlying_price AS close_underlying_price, c.commission_usd AS close_commission_usd,
                  c.pnl_usd
           FROM engine_trades t LEFT JOIN engine_trade_closes c ON c.trade_id = t.id
           ORDER BY t.taken_at DESC, t.id DESC"""
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["record"] = json.loads(d.pop("record_json"))
        out.append(d)
    return out


def conservative_pop(record: dict) -> float | None:
    """Mixture probability of profit stored with the candidate."""
    pop = record.get("pop")
    return float(pop) if pop is not None else None


# ---------------------------------------------------------------- scorecard
@dataclass(frozen=True)
class Scorecard:
    picks: int
    settled: int
    open: int
    wins: int
    expiry_days: int
    total_pnl_usd: float
    total_risk_usd: float
    predicted_ev_usd: float
    avg_pnl_usd: float | None
    pnl_ci95_usd: tuple[float, float] | None      # cluster bootstrap by expiry date
    hit_rate: float | None
    predicted_hit_rate: float | None
    max_drawdown_usd: float
    worst_day_usd: float | None
    near_strike_settlements: int

    @property
    def return_on_risk(self) -> float | None:
        return self.total_pnl_usd / self.total_risk_usd if self.total_risk_usd else None


def cluster_bootstrap_ci(pnl_by_day: dict[str, list[float]], reps: int = BOOTSTRAP_REPS,
                         seed: int = 7) -> tuple[float, float] | None:
    """95 % range of the average trade, resampling expiry days (clusters) with replacement."""
    days = list(pnl_by_day)
    if len(days) < 5:
        return None
    rng = np.random.default_rng(seed)
    sums = np.array([sum(pnl_by_day[d]) for d in days])
    counts = np.array([len(pnl_by_day[d]) for d in days], dtype=float)
    idx = rng.integers(0, len(days), size=(reps, len(days)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def drawdown(cumulative: Iterable[float]) -> float:
    peak, worst = 0.0, 0.0
    for v in cumulative:
        peak = max(peak, v)
        worst = min(worst, v - peak)
    return worst


def scorecard(picks: list[dict]) -> Scorecard:
    settled = [p for p in picks if p.get("pnl_usd") is not None]
    pnls = np.array([float(p["pnl_usd"]) for p in settled], dtype=float)
    wins = int((pnls > 0).sum()) if len(pnls) else 0
    by_day: dict[str, list[float]] = defaultdict(list)
    for p in settled:
        by_day[str(p["settlement_date"])].append(float(p["pnl_usd"]))
    day_totals = [sum(by_day[d]) for d in sorted(by_day)]
    cumulative = list(np.cumsum(day_totals)) if day_totals else []
    pops = [x for x in (conservative_pop(p["record"]) for p in settled) if x is not None]
    return Scorecard(
        picks=len(picks), settled=len(settled), open=len(picks) - len(settled), wins=wins,
        expiry_days=len(by_day),
        total_pnl_usd=float(pnls.sum()) if len(pnls) else 0.0,
        total_risk_usd=float(sum(float(p["max_loss_usd"]) for p in settled)),
        predicted_ev_usd=float(sum(float(p["conservative_ev_usd"]) for p in settled)),
        avg_pnl_usd=float(pnls.mean()) if len(pnls) else None,
        pnl_ci95_usd=cluster_bootstrap_ci(by_day),
        hit_rate=wins / len(pnls) if len(pnls) else None,
        predicted_hit_rate=float(np.mean(pops)) if pops else None,
        max_drawdown_usd=drawdown(cumulative),
        worst_day_usd=min(day_totals) if day_totals else None,
        near_strike_settlements=sum(1 for p in settled if p.get("near_strike")),
    )


def verdict(card: Scorecard) -> tuple[str, str]:
    """(kind, sentence). Never a confidence claim from the in-sample mean alone."""
    if card.expiry_days < MIN_EXPIRY_DAYS_FOR_VERDICT:
        return ("wait", f"Too early to judge: {card.settled} settled trade"
                f"{'s' if card.settled != 1 else ''} over {card.expiry_days} expiry day"
                f"{'s' if card.expiry_days != 1 else ''}; a verdict needs "
                f"{MIN_EXPIRY_DAYS_FOR_VERDICT} expiry days and a backtest through a volatility shock.")
    lo, hi = card.pnl_ci95_usd or (0.0, 0.0)
    base = (f"Over {card.expiry_days} expiry days the average trade is "
            f"{'+' if card.avg_pnl_usd >= 0 else '−'}${abs(card.avg_pnl_usd):,.0f} "
            f"(bootstrap range {lo:+,.0f} to {hi:+,.0f}), max drawdown "
            f"−${abs(card.max_drawdown_usd):,.0f}.")
    if lo > 0:
        return ("good", "Positive so far. " + base + " Live results only; a tail day is not in this sample until it happens.")
    if hi < 0:
        return ("bad", "Losing. " + base + " The models' edge is not showing up in outcomes.")
    return ("wait", "Not distinguishable from zero. " + base)


# ------------------------------------------------------------------ exposure
@dataclass(frozen=True)
class Exposure:
    open_trades: int
    open_risk_usd: float
    by_group: dict[str, float]
    trades_today: int
    realised_pnl_usd: float

    def after(self, max_loss_usd: float) -> float:
        return self.open_risk_usd + max_loss_usd


def exposure(trades: list[dict], *, today: date) -> Exposure:
    open_trades = [t for t in trades if t.get("pnl_usd") is None]
    by_group: dict[str, float] = defaultdict(float)
    for t in open_trades:
        by_group[name_group(t["underlying"])] += float(t["max_loss_usd"])
    taken_today = sum(1 for t in trades if str(t["taken_at"])[:10] == today.isoformat())
    realised = sum(float(t["pnl_usd"]) for t in trades if t.get("pnl_usd") is not None)
    return Exposure(len(open_trades), float(sum(by_group.values())), dict(by_group),
                    taken_today, float(realised))


# ------------------------------------------------------------------ backtest
def load_backtest_summary(path: str | Path | None) -> dict | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
