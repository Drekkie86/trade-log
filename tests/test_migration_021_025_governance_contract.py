from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sql(prefix: str) -> str:
    path = next((ROOT / "migrations").glob(f"{prefix}_*.sql"))
    return path.read_text(encoding="utf-8")


def test_migration_021_keeps_inference_and_decision_disabled():
    sql = _sql("021")
    assert "p_values_enabled INTEGER NOT NULL DEFAULT 0 CHECK(p_values_enabled=0)" in sql
    assert "fdr_enabled INTEGER NOT NULL DEFAULT 0 CHECK(fdr_enabled=0)" in sql
    assert "decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0)" in sql


def test_migration_022_keeps_calibration_readiness_observational():
    sql = _sql("022")
    assert "p_values_enabled INTEGER NOT NULL DEFAULT 0 CHECK(p_values_enabled=0)" in sql
    assert "fdr_enabled INTEGER NOT NULL DEFAULT 0 CHECK(fdr_enabled=0)" in sql
    assert "decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0)" in sql


def test_migration_023_preserves_honest_theta_timestamp_confidence_states():
    sql = _sql("023")
    assert "DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED" in sql
    assert "DOCUMENTED_AND_LIVE_VALIDATED" in sql
    assert "live_probe_state" in sql
    assert "decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0)" in sql


def test_migration_024_locks_prospective_and_decision_firewalls():
    sql = _sql("024")
    assert "FROZEN_PROSPECTIVE_OBSERVATION_ONLY" in sql
    assert "admission_enabled INTEGER NOT NULL DEFAULT 0 CHECK(admission_enabled=0)" in sql
    assert "decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0)" in sql
    assert "POST_FREEZE_PROSPECTIVE" in sql


def test_migration_025_makes_recovery_provenance_queryable_without_new_decisions():
    sql = _sql("025")
    assert "RECOVERED_AFTER_TRANSIENT_PROVIDER_FAILURE" in sql
    assert "recovery_error_type" in sql
    assert "recovery_error_message" in sql
    assert "v_local_surface_v2_prospective_partition_v2" in sql
    assert "decision_enabled" not in sql
