from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.database.repository import resolve_db_path
from src.operations.sqlite_runtime import open_readonly_connection
from src.research.decision_discipline_v1 import (
    APPROVED_EXECUTION,
    DISCRETIONARY_EXECUTION,
    ExecutionObservation,
    analyze_discipline_leakage,
)
from src.research.prospective_shadow_runtime_v1 import load_calibration_shadow_runtime


RUNTIME_VERSION = "1.0.0"


@dataclass(frozen=True)
class DecisionDisciplineRuntime:
    version: str
    state: str
    calibration_shadow_state: str
    promotion_authority: str
    execution_classification_state: str
    approved_execution_count: int
    discretionary_execution_count: int
    discipline_leakage: dict[str, Any] | None
    decision_authority: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;",
        (name,),
    ).fetchone() is not None


def _columns(conn, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table});").fetchall()}


def _execution_observations(conn) -> tuple[str, list[ExecutionObservation]]:
    if not _table_exists(conn, "trades"):
        return "TRADE_TABLE_UNAVAILABLE", []

    columns = _columns(conn, "trades")
    if "execution_class" not in columns:
        return "EXPLICIT_EXECUTION_CLASS_NOT_CAPTURED", []

    pnl_column = next(
        (
            name
            for name in (
                "realized_pnl",
                "net_pnl",
                "pnl",
                "realized_pnl_eur_minor",
                "net_pnl_eur_minor",
            )
            if name in columns
        ),
        None,
    )
    if pnl_column is None:
        return "EXECUTION_CLASS_PRESENT_PNL_NOT_CAPTURED", []

    expected_column = next(
        (
            name
            for name in ("model_expected_pnl", "model_expected_value_minor")
            if name in columns
        ),
        None,
    )
    expected_sql = expected_column if expected_column is not None else "NULL"
    rows = conn.execute(
        f"""
        SELECT id, execution_class, {pnl_column} AS pnl, {expected_sql} AS expected_pnl
        FROM trades
        WHERE execution_class IN (?, ?)
          AND {pnl_column} IS NOT NULL
        ORDER BY id;
        """,
        (APPROVED_EXECUTION, DISCRETIONARY_EXECUTION),
    ).fetchall()
    observations = [
        ExecutionObservation(
            sequence=index,
            execution_class=str(row["execution_class"]),
            pnl=float(row["pnl"]),
            model_expected_pnl=(
                None if row["expected_pnl"] is None else float(row["expected_pnl"])
            ),
        )
        for index, row in enumerate(rows, start=1)
    ]
    return "EXPLICIT_EXECUTION_CLASS_AVAILABLE", observations


def load_decision_discipline_runtime(
    db_path: str | Path | None = None,
) -> DecisionDisciplineRuntime:
    path = resolve_db_path(db_path)
    calibration = load_calibration_shadow_runtime(path)
    if not path.exists():
        return DecisionDisciplineRuntime(
            version=RUNTIME_VERSION,
            state="DATABASE_UNAVAILABLE",
            calibration_shadow_state=calibration.state,
            promotion_authority=calibration.promotion_authority,
            execution_classification_state="NOT_AVAILABLE",
            approved_execution_count=0,
            discretionary_execution_count=0,
            discipline_leakage=None,
            decision_authority="NONE_AUTOMATIC_MANUAL_REVIEW_ONLY",
            detail="Database unavailable. No decision or operator-behaviour evidence can be summarized.",
        )

    conn = open_readonly_connection(path)
    try:
        classification_state, observations = _execution_observations(conn)
    finally:
        conn.close()

    leakage = analyze_discipline_leakage(observations) if observations else None
    approved_count = sum(row.execution_class == APPROVED_EXECUTION for row in observations)
    discretionary_count = sum(
        row.execution_class == DISCRETIONARY_EXECUTION for row in observations
    )

    if classification_state != "EXPLICIT_EXECUTION_CLASS_AVAILABLE":
        state = "DISCIPLINE_CLASSIFICATION_NOT_YET_AVAILABLE"
        detail = (
            "Christiania does not infer approved versus discretionary behaviour from ambiguous historical fields. "
            "The distinction becomes scoreable only when explicit execution provenance is captured."
        )
    elif not observations:
        state = "NO_CLASSIFIED_EXECUTION_EVIDENCE"
        detail = "Explicit classification exists, but there are no classified resolved executions to score."
    else:
        state = "DISCIPLINE_EVIDENCE_AVAILABLE"
        detail = (
            "Approved and discretionary execution evidence is separated. This is descriptive governance evidence, "
            "not broker authority or automatic trade approval."
        )

    return DecisionDisciplineRuntime(
        version=RUNTIME_VERSION,
        state=state,
        calibration_shadow_state=calibration.state,
        promotion_authority=calibration.promotion_authority,
        execution_classification_state=classification_state,
        approved_execution_count=approved_count,
        discretionary_execution_count=discretionary_count,
        discipline_leakage=None if leakage is None else leakage.as_dict(),
        decision_authority="NONE_AUTOMATIC_MANUAL_REVIEW_ONLY",
        detail=detail,
    )
