"""Fail-closed, indexed Shadow Lab candidate readiness diagnostics."""
import sqlite3
from pathlib import Path

import pytest

from src.dashboard.read_model import load_command_deck
from src.dashboard.shadow_candidate_validation_v1 import (
    _classify,
    _source_clock_state,
    read_shadow_candidate_validation,
)
from src.database.repository import get_connection
from src.decision.risk_lifecycle import create_frozen_risk_plan
from src.research.shadow_admission import admit_shadow_proposals
from tests._shadow_admission_seed import fx, seed_proposal


def _open_readonly(db_path):
    c = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA query_only=ON")
    return c


def test_empty_db_is_not_reported_as_trade_ready(db_path):
    with _open_readonly(db_path) as conn:
        result = read_shadow_candidate_validation(conn)
    assert result["counts"]["recent_sample_size"] == 0
    assert result["counts"]["sample_economically_eligible"] == 0
    assert result["clock_evidence"] == "GLOBAL_LIVE_SEMANTICS_NOT_VERIFIED"
    assert result["recent_candidates"] == []


def test_intrinsic_candidate_is_reported_but_not_scored(db_path):
    seeded = seed_proposal(db_path)
    d = admit_shadow_proposals(
        fx=fx(), proposal_ids=[seeded["proposal_id"]], db_path=db_path
    ).decisions[0]
    assert d.candidate_id is not None
    with _open_readonly(db_path) as conn:
        result = read_shadow_candidate_validation(conn, limit=10)
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
    recent = result["recent_candidates"]
    assert len(recent) == 1
    record = recent[0]
    assert record["admission_policy"] == "INTRINSIC_RISK_POLICY_V1"
    assert record["risk_plan_recording"] == "NOT_RECORDED"
    assert record["economic_scoring_state"] == "NOT_ELIGIBLE"
    assert "PROVIDER_CLOCK_LIVE_PROBE_NOT_VERIFIED" in record["missing_evidence"]
    assert "PROSPECTIVE_RISK_PLAN_NOT_RECORDED" in record["missing_evidence"]
    assert "INDEPENDENT_ENTRY_EXIT_PACKAGE_RECEIPTS_MISSING" in record["missing_evidence"]
    assert result["counts"]["historical_legacy_admission_decisions"] == 0
    assert result["counts"]["new_intrinsic_admission_decisions"] == 1


def test_db_recorded_frozen_plan_passes_only_its_own_gate(db_path):
    seeded = seed_proposal(db_path)
    d = admit_shadow_proposals(
        fx=fx(), proposal_ids=[seeded["proposal_id"]], db_path=db_path
    ).decisions[0]
    create_frozen_risk_plan(
        candidate_id=d.candidate_id,
        max_defined_loss_eur_minor=d.converted_max_loss_eur_minor,
        risk_basis_eur_minor=d.intrinsic_risk_eur_minor,
        stop_loss_fraction=0.5,
        created_at="2026-09-01T18:02:00+00:00",
        db_path=db_path,
    )
    with _open_readonly(db_path) as conn:
        result = read_shadow_candidate_validation(conn)
    record = result["recent_candidates"][0]
    assert record["risk_plan_recording"] == "DB_RECORDED_PROSPECTIVE"
    assert "PROSPECTIVE_RISK_PLAN_NOT_RECORDED" not in record["missing_evidence"]
    assert record["economic_scoring_state"] == "NOT_ELIGIBLE"
    assert result["counts"]["sample_predeclared_risk_plans"] == 1


def test_undocumented_package_receipts_never_make_scoring_ready():
    r = {
        "candidate_id": 9, "underlying": "AAPL", "surfaced_at": "2026-10-15T14:00:00Z",
        "structure_id": "LONG_1_2_1_BUTTERFLY", "quote_freshness_class": "FRESH",
        "recorded_quote_class": "FRESH", "recorded_greek_class": "GOOD",
        "entry_quote_observation_id": 17, "admission_policy": "INTRINSIC_RISK_POLICY_V1",
        "risk_plan_recording": "DB_RECORDED_PROSPECTIVE",
        "mark_count": 24, "eligible_marks": 3, "recorded_outcome_observations": 2,
    }
    result = _classify(r, "GLOBAL_LIVE_SEMANTICS_PASSED")
    assert result["economic_scoring_state"] == "NOT_ELIGIBLE"
    assert "INDEPENDENT_ENTRY_EXIT_PACKAGE_RECEIPTS_MISSING" in result["missing_evidence"]
    assert "ENTRY_LEG_ASOF_RECEIPTS_NOT_VERIFIED" in result["missing_evidence"]
    assert "PROVIDER_CLOCK_LIVE_PROBE_NOT_VERIFIED" not in result["missing_evidence"]


@pytest.mark.parametrize("n", (0, -1, 101, True))
def test_bounded_candidate_reads_reject_invalid_limits(db_path, n):
    with _open_readonly(db_path) as conn:
        with pytest.raises(ValueError, match="LIMIT_OUT_OF_BOUNDS"):
            read_shadow_candidate_validation(conn, limit=n)


def test_shadow_page_exposes_candidate_validation_without_dashboard_scan(db_path):
    snapshot = load_command_deck(db_path, page="Shadow Lab", deep_integrity=False)
    report = snapshot["shadow_candidate_validation"]
    assert report["counts"]["sample_economically_eligible"] == 0
    assert snapshot["read_model_page"] == "Shadow Lab"
    other = load_command_deck(db_path, page="Dashboard", deep_integrity=False)
    assert other["shadow_candidate_validation"] == {}


def test_actual_sidebar_contains_fail_closed_evidence_gate():
    source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(
        encoding="utf-8"
    )
    top = source.index('elif page == "Shadow Lab":')
    tail = source.index('elif page == "Quant Models":', top)
    shadow = source[top:tail]
    assert 'Prospective candidate validation' in shadow
    assert shadow.index('Prospective candidate validation') < shadow.index(
        "render_shadow_stage0_workbench()"
    )
    assert "NOT all history" in shadow
