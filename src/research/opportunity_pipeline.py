"""Persist opportunity assessments (signal + matched placebo) and resolve them.

Runs inside the research cycle, strictly *after* proposals and admission, and
never blocks the cycle: the caller wraps it, and every proposal is handled in
its own transaction.  Nothing here places or implies an order.

Timeline per proposal
  1. assess  -> one SIGNAL row (verdict, score, every input) and one PLACEBO row,
     written together, before the outcome exists;
  2. resolve -> after the expiry session, one outcome per row from the same
     stored terminal price the shadow-outcome path uses.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from src.database.repository import get_connection
from src.decision.opportunity import (
    SCORING_VERSION,
    VERDICT_PLACEBO,
    ChainQuote,
    assess_idea,
    build_placebo_legs,
)
from src.decision.quote_noise import prior_iv_variation_for_leg
from src.decision.trade_ideas import (
    IdeaLeg,
    TradeIdea,
    entry_cashflow_usd,
    score_proposal,
    structure_fees_usd,
    terminal_value_usd,
)
from src.research.shadow_expiry_outcome_v1 import _expiry_snapshots_bulk

LOG = logging.getLogger(__name__)
PLACEBO_REASON = "MATCHED_RANDOM_CENTRE"


@dataclass(frozen=True)
class AssessResult:
    assessed: int
    placebos: int
    without_placebo: int
    errors: int


@dataclass(frozen=True)
class ResolveResult:
    due: int
    resolved: int
    awaiting_terminal_price: int


def _legs_to_json(legs) -> str:
    return json.dumps(
        [
            {
                "option_quote_id": l.option_quote_id,
                "right": l.right,
                "strike": l.strike,
                "side": l.side,
                "quantity": l.quantity,
                "multiplier": l.multiplier,
                "entry_price": l.entry_price,
                "bid": l.bid,
                "ask": l.ask,
                "market_iv": l.market_iv,
            }
            for l in legs
        ],
        sort_keys=True,
    )


def _legs_from_json(text: str) -> tuple[IdeaLeg, ...]:
    return tuple(IdeaLeg(**item) for item in json.loads(text))


def _chain(conn, snapshot_id: int, expiration: str, right: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT oq.id, oq.strike, oq.bid, oq.ask, oq.shares_per_contract,
               oq.quote_at, oq.volume, oq.open_interest,
               pmo.implied_volatility AS iv
        FROM option_quotes AS oq
        JOIN provider_model_observations AS pmo
          ON pmo.option_quote_id = oq.id AND pmo.provider = 'THETADATA'
        WHERE oq.snapshot_id = ? AND oq.expiration = ? AND oq.right = ?
          AND oq.bid IS NOT NULL AND oq.ask IS NOT NULL
          AND pmo.implied_volatility IS NOT NULL AND pmo.implied_volatility > 0
          AND pmo.id = (SELECT MAX(id) FROM provider_model_observations
                        WHERE option_quote_id = oq.id AND provider = 'THETADATA');
        """,
        (snapshot_id, expiration, right),
    ).fetchall()


def _seconds_between(later: str | None, earlier: str | None) -> float | None:
    try:
        a = datetime.fromisoformat(str(later).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(earlier).replace("Z", "+00:00"))
        if a.tzinfo is None or b.tzinfo is None:
            return None
        return (a - b).total_seconds()
    except (TypeError, ValueError):
        return None


def _db_features(conn, idea: TradeIdea, snapshot_id: int, chain_rows) -> dict[str, Any]:
    """Inputs the pure scorer cannot see.  Logged for later study; the verdict
    does not use them, so no outcome-fitted rule can hide in here."""
    snap = conn.execute(
        "SELECT captured_at FROM market_snapshots WHERE id = ?;", (snapshot_id,)
    ).fetchone()
    target_row = next(
        (r for r in chain_rows if abs(float(r["strike"]) - idea.target_strike) < 1e-9), None
    )
    opposite = "P" if str(idea.right).upper().startswith("C") else "C"
    parity_gap = None
    if target_row is not None:
        other = conn.execute(
            """
            SELECT pmo.implied_volatility AS iv
            FROM option_quotes AS oq
            JOIN provider_model_observations AS pmo
              ON pmo.option_quote_id = oq.id AND pmo.provider = 'THETADATA'
            WHERE oq.snapshot_id = ? AND oq.expiration = ? AND oq.strike = ?
              AND oq.right = ? AND pmo.implied_volatility > 0
            ORDER BY pmo.id DESC LIMIT 1;
            """,
            (snapshot_id, idea.expiration, idea.target_strike, opposite),
        ).fetchone()
        if other is not None:
            parity_gap = float(other["iv"]) - float(target_row["iv"])
    return {
        "chain_strikes": len(chain_rows),
        "target_quote_age_seconds": (
            _seconds_between(snap["captured_at"], target_row["quote_at"])
            if (snap and target_row is not None) else None
        ),
        "target_volume": target_row["volume"] if target_row is not None else None,
        "target_open_interest": target_row["open_interest"] if target_row is not None else None,
        "opposite_right_iv_minus_this": parity_gap,
    }


def assess_new_proposals(
    *, research_run_id: int, db_path=None, now: datetime | None = None
) -> AssessResult:
    stamp = (now or datetime.now(UTC)).isoformat()
    conn = get_connection(db_path)
    try:
        pids = [
            int(r["id"])
            for r in conn.execute(
                """
                SELECT ssp.id FROM shadow_structure_proposals AS ssp
                WHERE ssp.research_run_id = ? AND ssp.proposal_state = 'PROPOSED'
                  AND NOT EXISTS (SELECT 1 FROM opportunity_assessments_v1 AS a
                                  WHERE a.proposal_id = ssp.id AND a.kind = 'SIGNAL')
                ORDER BY ssp.id;
                """,
                (research_run_id,),
            ).fetchall()
        ]
    finally:
        conn.close()

    assessed = placebos = without = errors = 0
    noise_cache: dict[int, tuple[float, int] | None] = {}
    for pid in pids:
        try:
            idea = score_proposal(pid, db_path=db_path)
            conn = get_connection(db_path)
            try:
                snapshot_id = int(
                    conn.execute(
                        "SELECT snapshot_id FROM option_quotes WHERE id = ?;",
                        (idea.legs[0].option_quote_id,),
                    ).fetchone()["snapshot_id"]
                )
                chain_rows = _chain(conn, snapshot_id, idea.expiration, idea.right)
                for leg in idea.legs:
                    if leg.option_quote_id not in noise_cache:
                        noise_cache[leg.option_quote_id] = prior_iv_variation_for_leg(
                            conn, leg.option_quote_id
                        )
                estimates = {
                    qid: noise_cache[qid]
                    for qid in [leg.option_quote_id for leg in idea.legs]
                    if noise_cache[qid] is not None
                }
                assessment = assess_idea(
                    idea,
                    historical_iv_sigma_by_quote_id={
                        qid: value[0] for qid, value in estimates.items()
                    },
                    historical_iv_samples_by_quote_id={
                        qid: value[1] for qid, value in estimates.items()
                    },
                )
                features = dict(assessment.features)
                features["db"] = _db_features(conn, idea, snapshot_id, chain_rows)
                features["models_available"] = assessment.models_available
                features["models_favouring"] = assessment.models_favouring
                features["residual_vol_pts"] = assessment.residual_vol_pts
                features["sigma_quote_vol_pts"] = assessment.sigma_quote_vol_pts
                features["sigma_model_vol_pts"] = assessment.sigma_model_vol_pts
                chain = [
                    ChainQuote(
                        option_quote_id=int(r["id"]), strike=float(r["strike"]),
                        bid=float(r["bid"]), ask=float(r["ask"]), iv=float(r["iv"]),
                        multiplier=float(r["shares_per_contract"] or 100.0),
                    )
                    for r in chain_rows
                ]
                placebo_legs = build_placebo_legs(idea, chain, seed=pid)
                common = (
                    pid, research_run_id, stamp, SCORING_VERSION, idea.underlying,
                    idea.expiration, idea.right, idea.structure_id, idea.target_strike,
                    idea.session_date,
                )
                insert = (
                    "INSERT INTO opportunity_assessments_v1 (proposal_id, kind, research_run_id, "
                    "assessed_at, scoring_version, underlying, expiration, right, structure_id, "
                    "target_strike, session_date, verdict, reason_code, score, net_edge_usd, "
                    "entry_cashflow_usd, fees_usd, max_loss_usd, legs_json, features_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);"
                )
                conn.execute("BEGIN IMMEDIATE;") if not conn.in_transaction else None
                conn.execute(
                    insert,
                    (common[0], "SIGNAL", *common[1:], assessment.verdict, assessment.reason_code,
                     assessment.score, assessment.net_edge_usd,
                     entry_cashflow_usd(idea.legs), structure_fees_usd(idea.legs),
                     idea.max_loss_usd, _legs_to_json(idea.legs),
                     json.dumps(features, sort_keys=True, default=str)),
                )
                if placebo_legs is not None:
                    conn.execute(
                        insert,
                        (common[0], "PLACEBO", *common[1:], VERDICT_PLACEBO, PLACEBO_REASON,
                         None, None, entry_cashflow_usd(placebo_legs),
                         structure_fees_usd(placebo_legs), None, _legs_to_json(placebo_legs),
                         json.dumps({"seed": pid, "centre_strike": sorted(
                             {l.strike for l in placebo_legs})[1]}, sort_keys=True)),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            assessed += 1
            if placebo_legs is not None:
                placebos += 1
            else:
                without += 1
        except Exception:
            errors += 1
            LOG.exception("Opportunity assessment failed for proposal %s", pid)
    return AssessResult(assessed, placebos, without, errors)


def resolve_opportunity_outcomes(
    *, research_run_id: int, db_path=None, now: datetime | None = None
) -> ResolveResult:
    stamp = (now or datetime.now(UTC)).isoformat()
    conn = get_connection(db_path)
    try:
        run = conn.execute(
            "SELECT us_session_date FROM research_runs WHERE id = ?;", (research_run_id,)
        ).fetchone()
        if run is None or not run["us_session_date"]:
            return ResolveResult(0, 0, 0)
        session_day = date.fromisoformat(str(run["us_session_date"]))
        due = [
            dict(r)
            for r in conn.execute(
                """
                SELECT a.id, a.underlying, a.expiration, a.legs_json,
                       a.entry_cashflow_usd, a.fees_usd
                FROM opportunity_assessments_v1 AS a
                LEFT JOIN opportunity_outcomes_v1 AS o ON o.assessment_id = a.id
                WHERE o.id IS NULL AND a.expiration < ?
                ORDER BY a.id;
                """,
                (session_day.isoformat(),),
            ).fetchall()
        ]
    finally:
        conn.close()
    if not due:
        return ResolveResult(0, 0, 0)

    snapshots = _expiry_snapshots_bulk(candidates=due, db_path=db_path)
    resolved = waiting = 0
    conn = get_connection(db_path)
    try:
        for row in due:
            snap = snapshots.get((str(row["underlying"]), str(row["expiration"])))
            if snap is None:
                waiting += 1
                continue
            legs = _legs_from_json(row["legs_json"])
            terminal_value = terminal_value_usd(legs, float(snap["underlying_price"]))
            gross = float(row["entry_cashflow_usd"]) + terminal_value
            net = gross - float(row["fees_usd"])
            conn.execute(
                "INSERT INTO opportunity_outcomes_v1 (assessment_id, resolved_at, research_run_id, "
                "snapshot_id, snapshot_captured_at, terminal_underlying_price, terminal_value_usd, "
                "gross_pnl_usd, net_pnl_usd) VALUES (?,?,?,?,?,?,?,?,?);",
                (int(row["id"]), stamp, research_run_id, int(snap["id"]),
                 str(snap["captured_at"]), float(snap["underlying_price"]),
                 terminal_value, gross, net),
            )
            resolved += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return ResolveResult(len(due), resolved, waiting)


def load_evidence_rows(*, db_path=None) -> list[dict[str, Any]]:
    """Resolved SIGNAL rows paired with their resolved PLACEBO (or None)."""
    conn = get_connection(db_path)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='opportunity_outcomes_v1';"
        ).fetchone():
            raise sqlite3.OperationalError(
                "Opportunity evidence is unavailable until migration 037 is applied."
            )
        rows = conn.execute(
            """
            SELECT a.proposal_id, a.kind, a.verdict, a.score, a.underlying, a.expiration,
                   a.right, a.target_strike, a.structure_id, o.net_pnl_usd
            FROM opportunity_assessments_v1 AS a
            JOIN opportunity_outcomes_v1 AS o ON o.assessment_id = a.id
            WHERE a.scoring_version = ?;
            """,
            (SCORING_VERSION,),
        ).fetchall()
    finally:
        conn.close()
    placebo = {int(r["proposal_id"]): float(r["net_pnl_usd"]) for r in rows if r["kind"] == "PLACEBO"}
    out = []
    for r in rows:
        if r["kind"] != "SIGNAL":
            continue
        out.append(
            {
                "proposal_id": int(r["proposal_id"]),
                "bet_key": (r["underlying"], r["expiration"], r["right"],
                            float(r["target_strike"]), r["structure_id"]),
                "expiration": r["expiration"],
                "verdict": r["verdict"],
                "score": r["score"],
                "signal_net": float(r["net_pnl_usd"]),
                "placebo_net": placebo.get(int(r["proposal_id"])),
            }
        )
    return out


def load_prior_quote_noise_for_proposals(
    proposal_ids: list[int], *, db_path=None
) -> dict[int, tuple[dict[int, float], dict[int, int]]]:
    """Read the immutable as-of noise evidence, rather than re-query future quotes."""
    if not proposal_ids:
        return {}
    conn = get_connection(db_path)
    out: dict[int, tuple[dict[int, float], dict[int, int]]] = {}
    try:
        for offset in range(0, len(proposal_ids), 300):
            ids = proposal_ids[offset:offset + 300]
            marks = ",".join("?" for _ in ids)
            records = conn.execute(
                f"""SELECT proposal_id, features_json
                    FROM opportunity_assessments_v1
                    WHERE kind='SIGNAL' AND scoring_version=?
                    AND proposal_id IN ({marks})""",
                (SCORING_VERSION, *ids),
            )
            for record in records:
                features = json.loads(record["features_json"])
                if not features.get("historical_iv_variation_calibrated"):
                    continue
                sigmas = {
                    int(qid): float(value) for qid, value in
                    features["historical_iv_sigma_by_quote_id"].items()
                }
                counts = {
                    int(qid): int(value) for qid, value in
                    features["historical_iv_variation_samples_by_quote_id"].items()
                }
                out[int(record["proposal_id"])] = (sigmas, counts)
        return out
    finally:
        conn.close()
