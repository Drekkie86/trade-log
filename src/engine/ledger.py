"""Persistence for scans, picks and outcomes, plus the read models for the UI.

Every structure the engine puts in the top list is frozen as a pick the first
time it appears in a session. Picks are settled at expiry at intrinsic value.
The track record is computed only from these frozen records, so the scorecard
cannot be flattered after the fact.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

import numpy as np

from src.engine.chains import NY
from src.engine.history import settlement_price
from src.engine.pipeline import ScanResult

STORED_PASSED = 20
SETTLE_AFTER = time(16, 15)


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


# ------------------------------------------------------------------- writes
def record_scan(conn: sqlite3.Connection, result: ScanResult, *, completed_at: datetime) -> int:
    with conn:
        cur = conn.execute(
            """INSERT INTO engine_scans
               (lane, asof_at, completed_at, status, engine_version, config_json,
                chains_scanned, structures_scored, passed_count, rejections_json,
                chains_without_history_json)
               VALUES (?, ?, ?, 'COMPLETED', ?, ?, ?, ?, ?, ?, ?)""",
            (result.lane, _iso(result.asof), _iso(completed_at), result.engine_version,
             _json(result.config.as_dict()), result.chains_scanned, result.structures_scored,
             len(result.passed), _json(dict(result.rejections)),
             _json(sorted(set(result.chains_without_history)))),
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
        session_date = result.asof.astimezone(NY).date().isoformat()
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
               (lane, asof_at, completed_at, status, engine_version, config_json,
                rejections_json, chains_without_history_json, error_message)
               VALUES (?, ?, ?, 'FAILED', ?, ?, '{}', '[]', ?)""",
            (lane, _iso(asof), _iso(datetime.now(UTC)), engine_version, _json(config),
             f"{type(error).__name__}: {error}"[:2000]),
        )
    return int(cur.lastrowid)


def pick_pnl_at(record: dict, price: float) -> float:
    """Hold-to-expiry P&L of a frozen pick at one settlement price."""
    payoff = 0.0
    for leg in record["legs"]:
        k = float(leg["strike"])
        intrinsic = max(0.0, price - k) if leg["right"] == "C" else max(0.0, k - price)
        payoff += int(leg["side"]) * intrinsic
    return payoff * 100.0 + float(record["entry_cash_usd"]) - float(record["commission_usd"])


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
        price, source = found
        record = json.loads(r["record_json"])
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO engine_pick_outcomes
                   (pick_id, settled_at, settlement_date, settlement_price, settlement_source, pnl_usd)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (int(r["id"]), _iso(now), expiration, price, source,
                 round(pick_pnl_at(record, price), 2)),
            )
        settled += 1
    return settled


# -------------------------------------------------------------------- reads
def latest_scan(conn: sqlite3.Connection, lane: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM engine_scans WHERE lane=? ORDER BY id DESC LIMIT 1", (lane,)
    ).fetchone()
    if row is None:
        return None
    scan = dict(row)
    scan["rejections"] = json.loads(scan.pop("rejections_json") or "{}")
    scan["chains_without_history"] = json.loads(scan.pop("chains_without_history_json") or "[]")
    scan["config"] = json.loads(scan.pop("config_json") or "{}")
    cands = conn.execute(
        "SELECT kind, rank, record_json FROM engine_candidates WHERE scan_id=? ORDER BY kind, rank",
        (scan["id"],),
    ).fetchall()
    scan["passed"] = [json.loads(c["record_json"]) for c in cands if c["kind"] == "PASSED"]
    scan["near_misses"] = [json.loads(c["record_json"]) for c in cands if c["kind"] == "NEAR_MISS"]
    return scan


def last_successful_scan_at(conn: sqlite3.Connection, lane: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(asof_at) FROM engine_scans WHERE lane=? AND status='COMPLETED'", (lane,)
    ).fetchone()
    return row[0] if row else None


def picks_with_outcomes(conn: sqlite3.Connection, lane: str | None = None) -> list[dict]:
    sql = """SELECT p.*, o.settled_at, o.settlement_date, o.settlement_price, o.settlement_source, o.pnl_usd
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


def conservative_pop(record: dict) -> float | None:
    """Lower of the two forecast models' probability of profit."""
    scores = record.get("scores", {})
    pops = [scores.get(m, {}).get("pop") for m in ("VOL_FORECAST", "EMPIRICAL")]
    pops = [x for x in pops if x is not None]
    return min(pops) if len(pops) == 2 else None


@dataclass(frozen=True)
class Scorecard:
    picks: int
    settled: int
    open: int
    wins: int
    total_pnl_usd: float
    total_risk_usd: float
    predicted_ev_usd: float
    avg_pnl_usd: float | None
    pnl_ci95_usd: tuple[float, float] | None
    hit_rate: float | None
    predicted_hit_rate: float | None

    @property
    def return_on_risk(self) -> float | None:
        return self.total_pnl_usd / self.total_risk_usd if self.total_risk_usd else None


def scorecard(picks: list[dict]) -> Scorecard:
    settled = [p for p in picks if p.get("pnl_usd") is not None]
    pnls = np.array([float(p["pnl_usd"]) for p in settled], dtype=float)
    wins = int((pnls > 0).sum()) if len(pnls) else 0
    ci = None
    if len(pnls) >= 5:
        se = float(pnls.std(ddof=1) / math.sqrt(len(pnls)))
        ci = (float(pnls.mean() - 1.96 * se), float(pnls.mean() + 1.96 * se))
    pops = [x for x in (conservative_pop(p["record"]) for p in settled) if x is not None]
    return Scorecard(
        picks=len(picks), settled=len(settled), open=len(picks) - len(settled), wins=wins,
        total_pnl_usd=float(pnls.sum()) if len(pnls) else 0.0,
        total_risk_usd=float(sum(float(p["max_loss_usd"]) for p in settled)),
        predicted_ev_usd=float(sum(float(p["conservative_ev_usd"]) for p in settled)),
        avg_pnl_usd=float(pnls.mean()) if len(pnls) else None,
        pnl_ci95_usd=ci,
        hit_rate=wins / len(pnls) if len(pnls) else None,
        predicted_hit_rate=float(np.mean(pops)) if pops else None,
    )
