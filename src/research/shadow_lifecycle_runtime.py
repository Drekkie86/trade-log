from __future__ import annotations

from dataclasses import dataclass

from src.database.repository import (
    append_shadow_state_event,
    append_underlying_pin_event,
    get_connection,
)


@dataclass(frozen=True)
class ShadowLifecycleAdvanceResult:
    research_run_id: int
    session_date: str
    closed_count: int
    scored_count: int
    unpinned_count: int


def _latest_state_rows(*, db_path=None):
    conn = get_connection(db_path)
    try:
        return conn.execute(
            """
            WITH latest_state AS (
                SELECT
                    se.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY se.candidate_id
                        ORDER BY se.id DESC
                    ) AS rn
                FROM shadow_state_events AS se
            )
            SELECT
                sc.id AS candidate_id,
                sc.underlying,
                lrc.expiration,
                ls.to_state AS current_state
            FROM shadow_candidates AS sc
            JOIN listing_reference_contracts AS lrc
              ON lrc.id = sc.reference_contract_id
            JOIN latest_state AS ls
              ON ls.candidate_id = sc.id
             AND ls.rn = 1
            WHERE ls.to_state IN ('SHADOW_TRACKED', 'CLOSED_OR_EXPIRED')
            ORDER BY sc.id;
            """
        ).fetchall()
    finally:
        conn.close()


def _latest_pin_action(candidate_id: int, *, db_path=None) -> str | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT action
            FROM underlying_pin_events
            WHERE candidate_id = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (candidate_id,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else str(row["action"])


def _validated_package_outcome_exists(candidate_id: int, *, db_path=None) -> bool:
    """Return whether the candidate has independently validated package evidence.

    Ordinary automated intraday leg-liquidation marks are deliberately *not*
    sufficient to score a candidate. The frozen measurement contract requires
    an explicitly validated package outcome with outcome_eligible=1.
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM shadow_mark_observations
            WHERE candidate_id = ?
              AND measurement_role = 'VALIDATED_PACKAGE_OUTCOME'
              AND outcome_eligible = 1
            LIMIT 1;
            """,
            (candidate_id,),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def advance_shadow_lifecycle(
    *,
    research_run_id: int,
    db_path=None,
) -> ShadowLifecycleAdvanceResult:
    """Advance deterministic shadow lifecycle states for one research session.

    Expiry is based on the research run's US session date. A candidate is
    closed only when expiration is strictly *before* that session date, so an
    expiration-day candidate remains trackable through the expiration session.

    Closing and scoring are separate. Expiry closes and unpins the candidate;
    scoring occurs only when separately validated package-outcome evidence is
    already present. This preserves the existing evidence firewall and never
    upgrades intraday marks into outcome evidence.
    """
    conn = get_connection(db_path)
    try:
        run = conn.execute(
            """
            SELECT
                id,
                us_session_date,
                COALESCE(ended_at, started_at) AS lifecycle_at
            FROM research_runs
            WHERE id = ?;
            """,
            (research_run_id,),
        ).fetchone()
    finally:
        conn.close()

    if run is None:
        raise ValueError(f"Unknown research run {research_run_id}.")

    session_date = str(run["us_session_date"])
    lifecycle_at = str(run["lifecycle_at"])
    if not lifecycle_at:
        raise ValueError(
            f"Research run {research_run_id} has no lifecycle timestamp."
        )

    closed = 0
    scored = 0
    unpinned = 0

    for row in _latest_state_rows(db_path=db_path):
        candidate_id = int(row["candidate_id"])
        current_state = str(row["current_state"])
        expiration = str(row["expiration"])

        if current_state == "SHADOW_TRACKED" and expiration < session_date:
            append_shadow_state_event(
                candidate_id,
                to_state="CLOSED_OR_EXPIRED",
                occurred_at=lifecycle_at,
                actor="SYSTEM",
                reason_code="OPTION_EXPIRATION_SESSION_PASSED",
                note=(
                    "Shadow tracking closed after the option expiration "
                    "session. Scoring remains gated by validated package "
                    "outcome evidence."
                ),
                db_path=db_path,
            )
            current_state = "CLOSED_OR_EXPIRED"
            closed += 1

            if _latest_pin_action(candidate_id, db_path=db_path) == "PIN":
                append_underlying_pin_event(
                    underlying=str(row["underlying"]),
                    candidate_id=candidate_id,
                    action="UNPIN",
                    occurred_at=lifecycle_at,
                    reason="Shadow candidate closed after expiration session.",
                    db_path=db_path,
                )
                unpinned += 1

        if (
            current_state == "CLOSED_OR_EXPIRED"
            and _validated_package_outcome_exists(candidate_id, db_path=db_path)
        ):
            append_shadow_state_event(
                candidate_id,
                to_state="SCORED",
                occurred_at=lifecycle_at,
                actor="SYSTEM",
                reason_code="VALIDATED_PACKAGE_OUTCOME_AVAILABLE",
                note=(
                    "Candidate scored only after independently validated "
                    "package-outcome evidence became available."
                ),
                db_path=db_path,
            )
            scored += 1

    return ShadowLifecycleAdvanceResult(
        research_run_id=research_run_id,
        session_date=session_date,
        closed_count=closed,
        scored_count=scored,
        unpinned_count=unpinned,
    )
