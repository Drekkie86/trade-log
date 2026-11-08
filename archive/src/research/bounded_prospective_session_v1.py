"""Bounded, read-only per-session descriptive audit of frozen H1-H4 evidence.

No database mutation, no hypothesis promotion, no replacement of the legacy
frozen scientific checkpoint. New observations must be collected prospectively.
The result describes one historical session's *already-existing* observations.
"""
from __future__ import annotations

from array import array
from collections import defaultdict
from datetime import date
import hashlib
import json
import sqlite3
import time
from typing import Any

import numpy as np

from src.operations.sqlite_runtime import open_readonly_connection
from src.research.prospective_hypothesis_checkpoint_v1 import (
    _centered_cte,
    _flush_linear_group,
)

DEFAULT_MAX_SECONDS = 20.0
DEFAULT_MAX_ROWS = 500_000
DEFAULT_MAX_RUNS = 64
DEFAULT_MAX_STEPS = 80_000_000

_SCOPED_RUN_QUERY = _centered_cte() + """
    SELECT
        research_run_id, us_session_date, underlying, expiration,
        right, strike, implied_volatility, dte, centered_residual,
        abs_centered_residual, spread_to_mid, greek_age_seconds
    FROM centered
    WHERE research_run_id = ?
      AND us_session_date = ?
      AND centered_residual IS NOT NULL
    ORDER BY research_run_id, underlying, expiration, right, strike;
"""



class BoundedScienceError(RuntimeError):
    """A safety budget or consistency rule prevented a complete result."""


def _date_text(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise BoundedScienceError("Session must be an ISO date.") from exc
    if parsed.isoformat() != value:
        raise BoundedScienceError("Session date must be canonical ISO form.")
    return value


def _bucket_spread(spread: float | None) -> str:
    if spread is None:
        return "MISSING"
    if spread < 0.05:
        return "LT_05"
    if spread < 0.10:
        return "05_10"
    if spread < 0.20:
        return "10_20"
    return "GE_20"


def _bucket_greek_age(age: float | None) -> str:
    if age is None:
        return "MISSING"
    if abs(age) <= 1:
        return "LE_1S"
    if abs(age) <= 5:
        return "1_5S"
    if abs(age) <= 30:
        return "5_30S"
    return "GT_30S"


def _fresh_stat() -> dict[str, int | float]:
    return {"count": 0, "sum_abs": 0.0, "max_abs": 0.0}


def _add_stat(state: dict[str, int | float], residual: float) -> None:
    state["count"] += 1
    state["sum_abs"] += residual
    state["max_abs"] = max(state["max_abs"], residual)


def _final_stat(state: dict[str, int | float]) -> dict[str, int | float | None]:
    n = int(state["count"])
    return {
        "observation_count": n,
        "mean_abs_centered_residual": float(state["sum_abs"]) / n if n else None,
        "max_abs_centered_residual": state["max_abs"] if n else None,
    }


def _h2_day(accum: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for bucket in sorted(accum):
        summary = accum[bucket]
        q = np.frombuffer(summary["quadratic"], dtype=np.float64)
        linear = np.frombuffer(summary["linear"], dtype=np.float64)
        if not len(q):
            continue
        results.append({
            "dte_bucket": bucket,
            "observation_count": len(q),
            "quadratic_median_abs_residual": float(np.median(q)),
            "local_linear_median_abs_residual": float(np.median(linear)),
            "quadratic_q95_abs_residual": float(np.quantile(q, 0.95)),
            "local_linear_q95_abs_residual": float(np.quantile(linear, 0.95)),
            "local_linear_better_fraction": int(summary["linear_better"]) / len(q),
        })
    return results


def evaluate_one_session(
    session_date: str,
    *,
    db_path=None,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_steps: int = DEFAULT_MAX_STEPS,
    include_contract_episodes: bool = False,
) -> dict[str, Any]:
    """Bounded one-day scientific audit; never persists a checkpoint.

    Work is limited in three ways:
      1. only enumerated research_run_ids for one canonical US session;
      2. hard row and elapsed-time caps, plus SQLite VM-opcode progress cap;
      3. connection opened in URI mode=ro with PRAGMA query_only=ON.

    H4's population recurrence requires joining episodes across *several*
    session results. A single session must NEVER be presented as recurrence.
    """
    day = _date_text(session_date)
    if not (1 <= max_seconds <= 120):
        raise ValueError("Per-day time cap must be between 1 and 120 seconds.")
    if not (1 <= max_rows <= DEFAULT_MAX_ROWS):
        raise ValueError("Per-day row cap must be between 1 and 500,000.")
    if not (10_000 <= max_steps <= DEFAULT_MAX_STEPS):
        raise ValueError("SQLite step cap must be between 10k and 80m.")

    conn = open_readonly_connection(db_path)
    # Never wait up to the generic 30s SQLite busy timeout on a busy VM.
    # These PRAGMAs alter this connection only, not the database.
    conn.execute("PRAGMA busy_timeout=2000;")
    started = time.monotonic()
    deadline = started + max_seconds
    operations = 0
    timed_out = False

    def _interrupt() -> int:
        nonlocal operations, timed_out
        operations += 10_000
        timed_out = (time.monotonic() > deadline or operations > max_steps)
        return 1 if timed_out else 0

    conn.set_progress_handler(_interrupt, 10_000)
    try:
        freeze = conn.execute("""
            SELECT id, frozen_through_session_date
            FROM prospective_research_freeze_v1_runs
            ORDER BY id DESC LIMIT 1
        """).fetchone()
        if freeze is None:
            raise BoundedScienceError("No frozen prospective protocol.")
        cutoff = _date_text(str(freeze["frozen_through_session_date"]))
        if day <= cutoff:
            raise BoundedScienceError("Requested date predates frozen prospective eligibility.")
        calibration = conn.execute("""
            SELECT r.source_null_run_id
            FROM prospective_research_freeze_v1_runs AS f
            JOIN local_surface_calibration_validity_v1_runs AS v
              ON v.id = f.source_validity_run_id
            JOIN local_surface_calibration_readiness_v1_runs AS r
              ON r.id = v.source_calibration_run_id
            WHERE f.id = ?
        """, (freeze["id"],)).fetchone()
        if calibration is None:
            raise BoundedScienceError("Frozen null reference is unavailable.")
        null_run_id = int(calibration["source_null_run_id"])
        run_rows = conn.execute("""
            SELECT id FROM research_runs
            WHERE us_session_date = ?
            ORDER BY id LIMIT ?
        """, (day, DEFAULT_MAX_RUNS + 1)).fetchall()
        if len(run_rows) > DEFAULT_MAX_RUNS:
            raise BoundedScienceError("Run budget exceeded; cannot scan this session.")
        runs = [int(row["id"]) for row in run_rows]
        if not runs:
            raise BoundedScienceError("No genuine research runs for this session.")

        h1 = _fresh_stat()
        h1_positive = 0
        h1_negative = 0
        spread: dict[str, dict[str, int | float]] = defaultdict(_fresh_stat)
        greek: dict[str, dict[str, int | float]] = defaultdict(_fresh_stat)
        h2: dict[str, dict[str, Any]] = {}
        # Contract/date (not intraday row) is the H4 episode unit.
        episodes: dict[tuple[str, str, float, str], dict[str, float | int]] = {}
        row_count = 0

        # A single restricted research_run_id is an indexed research model
        # source. Do not issue unrestricted GROUP BY against the full view.
        query = _SCOPED_RUN_QUERY
        index_guards = []
        real_surface = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='local_surface_residual_v2_observations'"
        ).fetchone()[0] > 0
        for run_id in runs:
            if time.monotonic() >= deadline:
                raise BoundedScienceError("Time budget reached before next research run.")
            # EXPLAIN executes no underlying option-row reads. In production,
            # refuse an unbounded surface scan before touching millions of rows.
            try:
                plan = conn.execute(
                    "EXPLAIN QUERY PLAN " + query,
                    (null_run_id, run_id, day),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if timed_out:
                    raise BoundedScienceError("SQLite plan budget reached.") from exc
                raise
            details = [str(entry[3]) for entry in plan]
            lower = [x.lower() for x in details]
            if real_surface:
                surface_search = any(
                    ("search o " in x and "using " in x) for x in lower
                )
                unsafe_scan = any("scan o" in x for x in lower)
                if not surface_search or unsafe_scan:
                    raise BoundedScienceError(
                        "Production surface query lacks indexed per-run access; "
                        "no observation scan was started."
                    )
            index_guards.append(
                "INDEXED_PER_RUN" if real_surface else "SYNTHETIC_FIXTURE"
            )
            current_key = None
            linear_group: list[Any] = []
            try:
                cursor = conn.execute(query, (null_run_id, run_id, day))
                for row in cursor:
                    row_count += 1
                    if row_count > max_rows:
                        raise BoundedScienceError("Row budget reached before finishing the session.")
                    if row_count % 500 == 0 and time.monotonic() > deadline:
                        raise BoundedScienceError("Time budget reached during row stream.")
                    centered = float(row["centered_residual"])
                    magnitude = float(row["abs_centered_residual"])
                    dte = int(row["dte"])

                    if 14 <= dte <= 20:
                        _add_stat(h1, magnitude)
                        h1_positive += centered > 0
                        h1_negative += centered < 0
                    _add_stat(spread[_bucket_spread(row["spread_to_mid"])], magnitude)
                    _add_stat(greek[_bucket_greek_age(row["greek_age_seconds"])], magnitude)

                    contract = (
                        str(row["underlying"]), str(row["expiration"]),
                        float(row["strike"]), str(row["right"]),
                    )
                    state = episodes.setdefault(contract, {
                        "count": 0, "sum_centered": 0.0, "max_abs": 0.0,
                        "positive_rows": 0, "negative_rows": 0,
                    })
                    state["count"] += 1
                    state["sum_centered"] += centered
                    state["max_abs"] = max(state["max_abs"], magnitude)
                    state["positive_rows"] += centered > 0
                    state["negative_rows"] += centered < 0

                    if 7 <= dte <= 45 and row["implied_volatility"] is not None:
                        # The frozen interpolation uses neighboring strikes
                        # from this very same (run, underlying, expiry, right).
                        key = (
                            run_id, row["underlying"],
                            row["expiration"], row["right"],
                        )
                        if current_key is not None and current_key != key:
                            _flush_linear_group(linear_group, h2)
                            linear_group = []
                        linear_group.append(row)
                        current_key = key
                if linear_group:
                    _flush_linear_group(linear_group, h2)
            except sqlite3.OperationalError as exc:
                if timed_out or "interrupt" in str(exc).lower():
                    raise BoundedScienceError("SQLite instruction/time budget reached.") from exc
                raise

        if row_count == 0:
            raise BoundedScienceError(
                "No evaluable post-freeze observations for this genuine session."
            )
        if time.monotonic() > deadline:
            raise BoundedScienceError("Time budget reached before summary generation.")
        day_episodes = []
        for (underlying, expiry, strike, right), item in sorted(episodes.items()):
            n = int(item["count"])
            day_episodes.append({
                "underlying": underlying,
                "expiration": expiry,
                "strike": strike,
                "right": right,
                "us_session_date": day,
                "observation_count": n,
                "mean_centered_residual": item["sum_centered"] / n,
                "peak_abs_centered_residual": item["max_abs"],
                "positive_count": item["positive_rows"],
                "negative_count": item["negative_rows"],
            })
        identity = hashlib.sha256(
            json.dumps(day_episodes, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        h2_results = _h2_day(h2)
        if time.monotonic() > deadline:
            raise BoundedScienceError("Time budget reached during summary generation.")
        return {
            "classification": "FROZEN_PROSPECTIVE_OBSERVATIONAL_PER_SESSION",
            "decision_enabled": False,
            "trading_edge_claimed": False,
            "read_only": True,
            "complete": True,
            "session_date": day,
            "frozen_run_id": int(freeze["id"]),
            "frozen_null_run_id": null_run_id,
            "research_run_count": len(runs),
            "observation_count": row_count,
            "h1_dte_14_20": _final_stat(h1) | {
                "positive_count": h1_positive, "negative_count": h1_negative,
            },
            "h2_comparison_by_dte": h2_results,
            "h3_spread_to_mid": {
                bucket: _final_stat(value) for bucket, value in sorted(spread.items())
            },
            "h3_greek_age": {
                bucket: _final_stat(value) for bucket, value in sorted(greek.items())
            },
            "h4_contract_session_episode_count": len(day_episodes),
            "h4_episode_sha256": identity,
            "h4_contract_session_episodes": day_episodes if include_contract_episodes else None,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "sqlite_vm_steps_approx": operations,
            "query_access_verification": (
                "INDEXED_PER_RUN" if real_surface else "SYNTHETIC_FIXTURE"
            ),
            "run_plans_verified": len(index_guards),
        }
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()



def combine_completed_sessions(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate only complete date-level evidence, without row pseudo-replication.

    Day-level H1/H2/H3 results remain disaggregated. H4 is reconstructed using
    the *frozen* contract-session episode definition and top-100 ranking, not
    by pooling intraday records or substituting a selected population rate.
    """
    if not sessions or len(sessions) > 100:
        raise BoundedScienceError("Requires 1–100 complete sessions.")
    dates = [str(part.get("session_date")) for part in sessions]
    if dates != sorted(set(dates)):
        raise BoundedScienceError("Session dates must be sorted and distinct.")
    freeze = sessions[0].get("frozen_run_id")
    null = sessions[0].get("frozen_null_run_id")
    contracts: dict[tuple[str, str, float, str], dict[str, Any]] = {}
    total_rows = 0

    for part in sessions:
        if (
            not part.get("complete")
            or part.get("classification") != "FROZEN_PROSPECTIVE_OBSERVATIONAL_PER_SESSION"
            or part.get("decision_enabled") is not False
            or part.get("read_only") is not True
        ):
            raise BoundedScienceError("Cannot merge incomplete/unverified science.")
        if part.get("frozen_run_id") != freeze or part.get("frozen_null_run_id") != null:
            raise BoundedScienceError("Frozen protocol changed within the population.")
        episodes = part.get("h4_contract_session_episodes")
        if not isinstance(episodes, list):
            raise BoundedScienceError("Contract episodes required for H4 aggregation.")
        if len(episodes) != part.get("h4_contract_session_episode_count"):
            raise BoundedScienceError("Episode count mismatch.")
        fingerprint = hashlib.sha256(
            json.dumps(episodes, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if fingerprint != part.get("h4_episode_sha256"):
            raise BoundedScienceError("Episode digest mismatch.")
        total_rows += int(part["observation_count"])
        seen: set[tuple[str, str, float, str]] = set()
        for item in episodes:
            if item.get("us_session_date") != part["session_date"]:
                raise BoundedScienceError("Episode/session date mismatch.")
            key = (
                str(item["underlying"]), str(item["expiration"]),
                float(item["strike"]), str(item["right"]),
            )
            if key in seen:
                raise BoundedScienceError("Duplicate contract episode in one date.")
            seen.add(key)
            state = contracts.setdefault(key, {
                "session_date_count": 0, "total_observation_count": 0,
                "sum_abs_episode_location": 0.0, "max_peak_abs_residual": 0.0,
                "positive_episode_dates": 0, "negative_episode_dates": 0,
            })
            state["session_date_count"] += 1
            state["total_observation_count"] += int(item["observation_count"])
            mean = float(item["mean_centered_residual"])
            state["sum_abs_episode_location"] += abs(mean)
            state["max_peak_abs_residual"] = max(
                state["max_peak_abs_residual"],
                float(item["peak_abs_centered_residual"]),
            )
            state["positive_episode_dates"] += mean > 0
            state["negative_episode_dates"] += mean < 0

    recurring = []
    for key, state in contracts.items():
        days = state["session_date_count"]
        if days < 2:
            continue
        recurring.append({
            "underlying": key[0], "expiration": key[1],
            "strike": key[2], "right": key[3],
            "session_date_count": days,
            "total_observation_count": state["total_observation_count"],
            "mean_abs_episode_location": state["sum_abs_episode_location"] / days,
            "max_peak_abs_residual": state["max_peak_abs_residual"],
            "positive_episode_dates": state["positive_episode_dates"],
            "negative_episode_dates": state["negative_episode_dates"],
            "cross_date_sign_agreement": (
                max(state["positive_episode_dates"], state["negative_episode_dates"]) / days
            ),
        })
    recurring.sort(
        key=lambda x: (
            -x["session_date_count"],
            -x["mean_abs_episode_location"],
            -x["max_peak_abs_residual"],
        ),
    )
    # Avoid presenting the selected top-100 as a population recurrence rate.
    return {
        "classification": "BOUNDED_FROZEN_PROSPECTIVE_DESCRIPTIVE_ONLY",
        "read_only": True,
        "complete": True,
        "decision_enabled": False,
        "independent_dates": len(dates),
        "session_dates": dates,
        "frozen_run_id": freeze,
        "frozen_null_run_id": null,
        "observation_rows": total_rows,
        "h1_per_date": [
            {"us_session_date": p["session_date"], **p["h1_dte_14_20"]}
            for p in sessions
        ],
        "h2_per_date": [
            {
                "us_session_date": p["session_date"],
                "comparison_by_dte": p["h2_comparison_by_dte"],
            }
            for p in sessions
        ],
        "h3_per_date": [
            {
                "us_session_date": p["session_date"],
                "spread_to_mid": p["h3_spread_to_mid"],
                "greek_age": p["h3_greek_age"],
            }
            for p in sessions
        ],
        "h4_recurring_contract_count": len(recurring),
        "h4_top_recurring_contracts": recurring[:100],
        "scope_warning": (
            "H2 is reported per independent date; do not average row-weighted "
            "quantiles. H4 top-100 is selected by recurrence/residual and is "
            "not a population-wide recurrence success rate."
        ),
    }



def preview_session_plan(session_date: str, *, db_path=None) -> dict[str, Any]:
    """Metadata-only first gate: EXPLAIN one scoped research run, never scan quotes."""
    day = _date_text(session_date)
    conn = open_readonly_connection(db_path)
    try:
        freeze = conn.execute(
            "SELECT id FROM prospective_research_freeze_v1_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if freeze is None:
            raise BoundedScienceError("No frozen research run exists.")
        run = conn.execute(
            "SELECT id FROM research_runs WHERE us_session_date=? ORDER BY id LIMIT 1",
            (day,),
        ).fetchone()
        if run is None:
            return {
                "classification": "NO_GENUINE_RESEARCH_RUN",
                "session_date": day,
                "query_executed": False,
                "read_only": True,
            }
        # The first query parameter is the fixed frozen-null reference.
        # EXPLAIN merely builds a plan and does NOT execute the CTE.
        plan = conn.execute(
            "EXPLAIN QUERY PLAN " + _SCOPED_RUN_QUERY,
            (0, int(run["id"]), day),
        ).fetchall()
        details = [str(x[3]).lower() for x in plan]
        seek = any("search o " in x and "using " in x for x in details)
        scan = any("scan o" in x for x in details)
        real = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='local_surface_residual_v2_observations'"
        ).fetchone()[0] > 0
        return {
            "classification": "SESSION_QUERY_PLAN_ONLY",
            "session_date": day,
            "sample_research_run_id": int(run["id"]),
            "real_production_surface": real,
            "indexed_underlying_observation_seek": seek,
            "unsafe_unbounded_observation_scan": scan or (real and not seek),
            "plan_operation_count": len(details),
            "query_executed": False,
            "read_only": True,
        }
    finally:
        conn.close()


def main() -> int:
    """CLI: plan-only by default. Explicit opt-in for bounded one-day execution."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Read-only, frozen H1-H4 single-session audit (no persistence)."
    )
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--execute-one-session", action="store_true")
    args = parser.parse_args()
    try:
        if args.execute_one_session:
            result = evaluate_one_session(
                args.session_date,
                db_path=args.db_path,
                include_contract_episodes=False,
            )
            # The selected H4 contract-session episode data are not in stdout
            # and there is no file write or checkpoint persistence.
        else:
            result = preview_session_plan(args.session_date, db_path=args.db_path)
    except (BoundedScienceError, sqlite3.Error) as exc:
        print(json.dumps({
            "classification": "BOUNDED_SCIENCE_ABORTED",
            "error_type": type(exc).__name__,
            "read_only": True,
            "complete": False,
        }, sort_keys=True))
        return 3
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
