from __future__ import annotations

import sqlite3

from src.research.decision_discipline_runtime_v1 import load_decision_discipline_runtime


def test_runtime_refuses_to_infer_execution_classification(tmp_path) -> None:
    path = tmp_path / "runtime.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, pnl REAL);")
        conn.execute("INSERT INTO trades (pnl) VALUES (5.0);")
        conn.commit()
    finally:
        conn.close()

    result = load_decision_discipline_runtime(path)
    assert result.state == "DISCIPLINE_CLASSIFICATION_NOT_YET_AVAILABLE"
    assert result.execution_classification_state == "EXPLICIT_EXECUTION_CLASS_NOT_CAPTURED"
    assert result.discipline_leakage is None
    assert result.decision_authority == "NONE_AUTOMATIC_MANUAL_REVIEW_ONLY"


def test_runtime_scores_only_explicit_execution_provenance(tmp_path) -> None:
    path = tmp_path / "runtime.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY,
                execution_class TEXT,
                realized_pnl REAL,
                model_expected_pnl REAL
            );
            """
        )
        rows = [
            ("MODEL_APPROVED", 5.0, 2.0),
            ("DISCRETIONARY_UNAPPROVED", -7.0, None),
            ("MODEL_APPROVED", 4.0, 2.0),
        ]
        conn.executemany(
            "INSERT INTO trades (execution_class, realized_pnl, model_expected_pnl) VALUES (?, ?, ?);",
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    result = load_decision_discipline_runtime(path)
    assert result.state == "DISCIPLINE_EVIDENCE_AVAILABLE"
    assert result.approved_execution_count == 2
    assert result.discretionary_execution_count == 1
    assert result.discipline_leakage is not None
    assert result.discipline_leakage["approved"]["total_pnl"] == 9.0
    assert result.discipline_leakage["discretionary"]["total_pnl"] == -7.0
