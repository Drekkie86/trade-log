from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.research.programme_family_governance_v1 import (
    ACTIVATION_ALLOCATED_ONLY,
    ACTIVATION_BLOCKED_INVALID,
    ACTIVATION_BLOCKED_UNFROZEN,
    INFERENCE_DISABLED,
    load_programme_governance_snapshot,
    validate_programme_budget,
)


def _write_governance(
    root: Path,
    *,
    budget: dict,
    log_lines: list[dict] | None = None,
) -> None:
    directory = root / "research" / "edge_discovery"
    directory.mkdir(parents=True)
    (directory / "PROGRAMME_FAMILY_BUDGET_V1.json").write_text(
        json.dumps(budget),
        encoding="utf-8",
    )
    payload = "".join(json.dumps(item) + "\n" for item in (log_lines or []))
    (directory / "HYPOTHESIS_EVALUATION_LOG.jsonl").write_text(payload, encoding="utf-8")


def _write_calibration_db(
    path: Path,
    *,
    readiness: str,
    dates: int,
    runtime_families: list[str] | None = None,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE local_surface_calibration_validity_v1_runs (
                id INTEGER PRIMARY KEY,
                readiness_state TEXT NOT NULL,
                distinct_session_dates INTEGER NOT NULL,
                p_values_enabled INTEGER NOT NULL,
                fdr_enabled INTEGER NOT NULL,
                decision_enabled INTEGER NOT NULL
            );
            CREATE TABLE hypothesis_scanner_runs (
                id INTEGER PRIMARY KEY,
                hypothesis_family TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO local_surface_calibration_validity_v1_runs(
                readiness_state,
                distinct_session_dates,
                p_values_enabled,
                fdr_enabled,
                decision_enabled
            ) VALUES (?, ?, 0, 0, 0);
            """,
            (readiness, dates),
        )
        conn.executemany(
            "INSERT INTO hypothesis_scanner_runs(hypothesis_family) VALUES (?);",
            [(family_id,) for family_id in (runtime_families or [])],
        )
        conn.commit()
    finally:
        conn.close()


def test_unfrozen_budget_blocks_new_family_but_keeps_discovery_fail_closed(tmp_path: Path) -> None:
    _write_governance(
        tmp_path,
        budget={
            "schema_version": "1.0",
            "status": "UNFROZEN",
            "period_id": "EDGE_PROGRAMME_001",
            "period_start": None,
            "period_end": None,
            "max_families": None,
            "alpha_or_q_budget": None,
            "allocation_method": None,
        },
    )
    db = tmp_path / "research.db"
    _write_calibration_db(
        db,
        readiness="EXPLORATORY_VALIDITY_ONLY",
        dates=7,
        runtime_families=["LOCAL_SURFACE_IV_RESIDUAL"] * 4,
    )

    snapshot = load_programme_governance_snapshot(db, repository_root=tmp_path)

    assert snapshot.activation_state == ACTIVATION_BLOCKED_UNFROZEN
    assert snapshot.ready_for_new_family_activation is False
    assert snapshot.inference_state == INFERENCE_DISABLED
    assert snapshot.p_values_enabled is False
    assert snapshot.fdr_enabled is False
    assert snapshot.decision_enabled is False
    assert snapshot.calibration_distinct_dates == 7
    assert snapshot.runtime_family_ids == ("LOCAL_SURFACE_IV_RESIDUAL",)
    assert snapshot.opened_family_ids == ("LOCAL_SURFACE_IV_RESIDUAL",)
    assert snapshot.opened_family_count == 1
    assert snapshot.runtime_scanner_run_count == 4
    assert snapshot.family_usage[0].runtime_scanner_runs == 4
    assert snapshot.family_usage[0].observed_in_runtime is True


def test_frozen_budget_allows_only_allocated_family_space(tmp_path: Path) -> None:
    _write_governance(
        tmp_path,
        budget={
            "schema_version": "1.0",
            "status": "FROZEN",
            "period_id": "EDGE_PROGRAMME_002",
            "period_start": "2026-09-14",
            "period_end": "2026-12-31",
            "max_families": 3,
            "alpha_or_q_budget": None,
            "allocation_method": "PREALLOCATED_FAMILIES_NO_INFERENCE_UNTIL_CALIBRATED",
            "family_ids": ["LOCAL_SURFACE_IV_RESIDUAL", "IV_VS_RV_GAP", "DEFINED_RISK_VRP"],
        },
        log_lines=[
            {"family_id": "LOCAL_SURFACE_IV_RESIDUAL", "variant_id": "v1"},
            {"family_id": "LOCAL_SURFACE_IV_RESIDUAL", "variant_id": "v2"},
        ],
    )

    snapshot = load_programme_governance_snapshot(
        tmp_path / "missing.db",
        repository_root=tmp_path,
    )

    assert snapshot.activation_state == ACTIVATION_ALLOCATED_ONLY
    assert snapshot.ready_for_new_family_activation is True
    assert snapshot.opened_family_count == 1
    assert snapshot.remaining_family_slots == 2
    assert snapshot.hypothesis_evaluation_count == 2
    assert snapshot.family_usage[0].family_id == "LOCAL_SURFACE_IV_RESIDUAL"
    assert snapshot.family_usage[0].allocated is True
    assert snapshot.inference_state == INFERENCE_DISABLED
    assert any("alpha_or_q_budget" in warning for warning in snapshot.budget_warnings)


def test_runtime_family_outside_frozen_allocation_fails_closed(tmp_path: Path) -> None:
    _write_governance(
        tmp_path,
        budget={
            "schema_version": "1.0",
            "status": "FROZEN",
            "period_id": "EDGE_PROGRAMME_003",
            "period_start": "2026-09-14",
            "period_end": "2026-12-31",
            "max_families": 2,
            "alpha_or_q_budget": 0.05,
            "allocation_method": "PREALLOCATED",
            "family_ids": ["FAMILY_A", "FAMILY_B"],
        },
    )
    db = tmp_path / "research.db"
    _write_calibration_db(
        db,
        readiness="EXPLORATORY_VALIDITY_ONLY",
        dates=6,
        runtime_families=["FAMILY_C"],
    )

    snapshot = load_programme_governance_snapshot(db, repository_root=tmp_path)

    assert snapshot.activation_state == ACTIVATION_BLOCKED_INVALID
    assert snapshot.ready_for_new_family_activation is False
    assert "FAMILY_C" in snapshot.activation_detail


def test_logged_family_outside_frozen_allocation_fails_closed(tmp_path: Path) -> None:
    _write_governance(
        tmp_path,
        budget={
            "schema_version": "1.0",
            "status": "FROZEN",
            "period_id": "EDGE_PROGRAMME_004",
            "period_start": "2026-09-14",
            "period_end": "2026-12-31",
            "max_families": 2,
            "alpha_or_q_budget": 0.05,
            "allocation_method": "PREALLOCATED",
            "family_ids": ["FAMILY_A", "FAMILY_B"],
        },
        log_lines=[{"family_id": "FAMILY_C", "variant_id": "oops"}],
    )

    snapshot = load_programme_governance_snapshot(
        tmp_path / "missing.db",
        repository_root=tmp_path,
    )

    assert snapshot.activation_state == ACTIVATION_BLOCKED_INVALID
    assert snapshot.ready_for_new_family_activation is False
    assert "FAMILY_C" in snapshot.activation_detail


def test_frozen_budget_requires_explicit_period_capacity_and_allocation() -> None:
    errors, warnings = validate_programme_budget(
        {
            "status": "FROZEN",
            "period_id": "EDGE_PROGRAMME_BAD",
            "period_start": None,
            "period_end": None,
            "max_families": None,
            "family_ids": [],
            "allocation_method": None,
            "alpha_or_q_budget": None,
        }
    )

    assert errors
    assert any("period_start" in error for error in errors)
    assert any("max_families" in error for error in errors)
    assert any("family_ids" in error for error in errors)
    assert any("allocation_method" in error for error in errors)
    assert any("alpha_or_q_budget" in warning for warning in warnings)


def test_current_repository_budget_remains_deliberately_unfrozen() -> None:
    root = Path(__file__).resolve().parents[1]
    snapshot = load_programme_governance_snapshot(
        root / "does-not-exist.db",
        repository_root=root,
    )

    assert snapshot.budget_status == "UNFROZEN"
    assert snapshot.activation_state == ACTIVATION_BLOCKED_UNFROZEN
    assert snapshot.ready_for_new_family_activation is False
    assert snapshot.inference_state == INFERENCE_DISABLED
