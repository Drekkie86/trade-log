from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.database.repository import resolve_db_path
from src.operations.sqlite_runtime import open_readonly_connection


RUNTIME_VERSION = "1.0.0"


@dataclass(frozen=True)
class ProspectiveEvidenceState:
    freeze_run_id: int | None
    frozen_through_session_date: str | None
    prospective_start_session_date: str | None
    protocol_state: str | None
    prospective_independent_dates: int
    hypothesis_count: int
    p_values_enabled: bool
    fdr_enabled: bool
    admission_enabled: bool
    decision_enabled: bool


@dataclass(frozen=True)
class ShadowEvidenceState:
    candidate_count: int
    shadow_tracked_count: int
    closed_or_expired_count: int
    scored_count: int
    rejected_count: int
    complete_mark_count: int
    incomplete_mark_count: int
    profitable_mark_count: int
    losing_mark_count: int
    zero_mark_count: int
    marked_candidate_count: int
    marked_research_run_count: int
    decision_time_probability_state: str


@dataclass(frozen=True)
class CalibrationShadowRuntime:
    version: str
    state: str
    prospective: ProspectiveEvidenceState
    shadow: ShadowEvidenceState
    thesis_probability_channel_state: str
    profit_probability_channel_state: str
    promotion_authority: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _table_exists(conn, name: str, *, kind: str | None = None) -> bool:
    if kind is None:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=? LIMIT 1;",
            (name,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type=? AND name=? LIMIT 1;",
            (kind, name),
        ).fetchone()
    return row is not None


def _empty_prospective() -> ProspectiveEvidenceState:
    return ProspectiveEvidenceState(
        freeze_run_id=None,
        frozen_through_session_date=None,
        prospective_start_session_date=None,
        protocol_state=None,
        prospective_independent_dates=0,
        hypothesis_count=0,
        p_values_enabled=False,
        fdr_enabled=False,
        admission_enabled=False,
        decision_enabled=False,
    )


def _empty_shadow() -> ShadowEvidenceState:
    return ShadowEvidenceState(
        candidate_count=0,
        shadow_tracked_count=0,
        closed_or_expired_count=0,
        scored_count=0,
        rejected_count=0,
        complete_mark_count=0,
        incomplete_mark_count=0,
        profitable_mark_count=0,
        losing_mark_count=0,
        zero_mark_count=0,
        marked_candidate_count=0,
        marked_research_run_count=0,
        decision_time_probability_state="NOT_AVAILABLE",
    )


def _prospective_state(conn) -> ProspectiveEvidenceState:
    if not _table_exists(conn, "prospective_research_freeze_v1_runs", kind="table"):
        return _empty_prospective()

    row = conn.execute(
        """
        SELECT
            id,
            frozen_through_session_date,
            prospective_start_session_date,
            protocol_state,
            p_values_enabled,
            fdr_enabled,
            admission_enabled,
            decision_enabled
        FROM prospective_research_freeze_v1_runs
        ORDER BY id DESC
        LIMIT 1;
        """
    ).fetchone()
    if row is None:
        return _empty_prospective()

    hypothesis_count = 0
    if _table_exists(conn, "prospective_research_hypotheses_v1", kind="table"):
        hypothesis_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM prospective_research_hypotheses_v1 WHERE freeze_run_id=?;",
                (int(row["id"]),),
            ).fetchone()[0]
        )

    prospective_dates = 0
    if _table_exists(conn, "v_local_surface_v2_prospective_partition_v2", kind="view"):
        columns = {
            str(item[1])
            for item in conn.execute(
                "PRAGMA table_info(v_local_surface_v2_prospective_partition_v2);"
            ).fetchall()
        }
        if "session_date" in columns:
            prospective_dates = int(
                conn.execute(
                    """
                    SELECT COUNT(DISTINCT session_date)
                    FROM v_local_surface_v2_prospective_partition_v2
                    WHERE session_date >= ?;
                    """,
                    (str(row["prospective_start_session_date"]),),
                ).fetchone()[0]
            )

    return ProspectiveEvidenceState(
        freeze_run_id=int(row["id"]),
        frozen_through_session_date=str(row["frozen_through_session_date"]),
        prospective_start_session_date=str(row["prospective_start_session_date"]),
        protocol_state=str(row["protocol_state"]),
        prospective_independent_dates=prospective_dates,
        hypothesis_count=hypothesis_count,
        p_values_enabled=bool(row["p_values_enabled"]),
        fdr_enabled=bool(row["fdr_enabled"]),
        admission_enabled=bool(row["admission_enabled"]),
        decision_enabled=bool(row["decision_enabled"]),
    )


def _shadow_state(conn) -> ShadowEvidenceState:
    if not _table_exists(conn, "shadow_candidates", kind="table"):
        return _empty_shadow()

    candidate_count = int(conn.execute("SELECT COUNT(*) FROM shadow_candidates;").fetchone()[0])
    counts = {
        "SHADOW_TRACKED": 0,
        "CLOSED_OR_EXPIRED": 0,
        "SCORED": 0,
        "REJECTED": 0,
    }
    if _table_exists(conn, "shadow_state_events", kind="table"):
        rows = conn.execute(
            """
            WITH latest_state AS (
                SELECT
                    candidate_id,
                    to_state,
                    ROW_NUMBER() OVER (PARTITION BY candidate_id ORDER BY id DESC) AS rn
                FROM shadow_state_events
            )
            SELECT to_state, COUNT(*) AS n
            FROM latest_state
            WHERE rn=1
            GROUP BY to_state;
            """
        ).fetchall()
        for row in rows:
            state = str(row["to_state"])
            if state in counts:
                counts[state] = int(row["n"])

    complete = incomplete = profitable = losing = zero = marked_candidates = marked_runs = 0
    probability_state = "NOT_CAPTURED_IN_SHADOW_MARKS"
    if _table_exists(conn, "shadow_mark_observations", kind="table"):
        mark_row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN quality_state='COMPLETE' THEN 1 ELSE 0 END) AS complete_count,
                SUM(CASE WHEN quality_state<>'COMPLETE' THEN 1 ELSE 0 END) AS incomplete_count,
                SUM(CASE WHEN quality_state='COMPLETE' AND estimated_net_pnl_eur_minor > 0 THEN 1 ELSE 0 END) AS profitable_count,
                SUM(CASE WHEN quality_state='COMPLETE' AND estimated_net_pnl_eur_minor < 0 THEN 1 ELSE 0 END) AS losing_count,
                SUM(CASE WHEN quality_state='COMPLETE' AND estimated_net_pnl_eur_minor = 0 THEN 1 ELSE 0 END) AS zero_count,
                COUNT(DISTINCT candidate_id) AS candidate_count,
                COUNT(DISTINCT research_run_id) AS run_count
            FROM shadow_mark_observations;
            """
        ).fetchone()
        complete = int(mark_row["complete_count"] or 0)
        incomplete = int(mark_row["incomplete_count"] or 0)
        profitable = int(mark_row["profitable_count"] or 0)
        losing = int(mark_row["losing_count"] or 0)
        zero = int(mark_row["zero_count"] or 0)
        marked_candidates = int(mark_row["candidate_count"] or 0)
        marked_runs = int(mark_row["run_count"] or 0)

        mark_columns = {
            str(item[1]) for item in conn.execute("PRAGMA table_info(shadow_mark_observations);").fetchall()
        }
        probability_columns = {"p_thesis", "p_profit", "probability_thesis", "probability_profit"}
        if mark_columns & probability_columns:
            probability_state = "PROBABILITY_FIELDS_PRESENT"

    return ShadowEvidenceState(
        candidate_count=candidate_count,
        shadow_tracked_count=counts["SHADOW_TRACKED"],
        closed_or_expired_count=counts["CLOSED_OR_EXPIRED"],
        scored_count=counts["SCORED"],
        rejected_count=counts["REJECTED"],
        complete_mark_count=complete,
        incomplete_mark_count=incomplete,
        profitable_mark_count=profitable,
        losing_mark_count=losing,
        zero_mark_count=zero,
        marked_candidate_count=marked_candidates,
        marked_research_run_count=marked_runs,
        decision_time_probability_state=probability_state,
    )


def load_calibration_shadow_runtime(db_path: str | Path | None = None) -> CalibrationShadowRuntime:
    path = resolve_db_path(db_path)
    if not path.exists():
        return CalibrationShadowRuntime(
            version=RUNTIME_VERSION,
            state="DATABASE_UNAVAILABLE",
            prospective=_empty_prospective(),
            shadow=_empty_shadow(),
            thesis_probability_channel_state="NO_EVIDENCE",
            profit_probability_channel_state="NO_EVIDENCE",
            promotion_authority="NONE_RESEARCH_ONLY",
            detail="Database is unavailable; calibration and shadow evidence cannot be summarized.",
        )

    conn = open_readonly_connection(path)
    try:
        prospective = _prospective_state(conn)
        shadow = _shadow_state(conn)
    finally:
        conn.close()

    thesis_channel = "ACCUMULATING_NOT_YET_SCOREABLE"
    profit_channel = (
        "SCOREABLE_IF_DECISION_TIME_PROBABILITIES_EXIST"
        if shadow.complete_mark_count > 0
        else "ACCUMULATING_OUTCOMES"
    )
    if shadow.decision_time_probability_state == "PROBABILITY_FIELDS_PRESENT" and shadow.complete_mark_count > 0:
        profit_channel = "SCOREABLE"

    if prospective.freeze_run_id is None and shadow.candidate_count == 0:
        state = "NO_PROSPECTIVE_OR_SHADOW_EVIDENCE"
    elif prospective.prospective_independent_dates < 5:
        state = "ACCUMULATING_PROSPECTIVE_EVIDENCE"
    else:
        state = "DESCRIPTIVE_REVIEW_AVAILABLE"

    firewall_enabled = not any(
        (
            prospective.p_values_enabled,
            prospective.fdr_enabled,
            prospective.admission_enabled,
            prospective.decision_enabled,
        )
    )
    detail = (
        "Prospective and shadow evidence are summarized read-only. Automatic promotion remains disabled."
        if firewall_enabled
        else "WARNING: one or more downstream inference/admission/decision flags are enabled; manual governance review required."
    )

    return CalibrationShadowRuntime(
        version=RUNTIME_VERSION,
        state=state,
        prospective=prospective,
        shadow=shadow,
        thesis_probability_channel_state=thesis_channel,
        profit_probability_channel_state=profit_channel,
        promotion_authority="NONE_AUTOMATIC_REVIEW_ONLY",
        detail=detail,
    )
