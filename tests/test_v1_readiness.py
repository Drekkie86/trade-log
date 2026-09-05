from __future__ import annotations

from src.operations.v1_readiness import assess_v1_readiness


def _deck(*, dates=1, daemon="NO_DAEMON_LEASE", theta_ready=None):
    return {
        "ready": True,
        "database": {
            "quick_check": "ok",
            "foreign_key_violation_count": 0,
            "journal_mode": "wal",
        },
        "market_clock": {
            "state": "AFTER_SAMPLE_WINDOW",
            "next_sample_at": "2026-09-08T09:45:00-04:00",
        },
        "daemon_health": {"state": daemon},
        "theta_health": {
            "state": "READY" if theta_ready else "NOT_PROBED",
            "ready": theta_ready,
        },
        "models": [
            {"decision_enabled": 0, "admission_enabled": 0},
            {"decision_enabled": 0, "admission_enabled": 0},
        ],
        "prospective": {"independent_dates": dates},
    }


def _backups(age=1.0):
    return {"valid_files": 2, "latest_valid_age_hours": age}


def test_product_readiness_is_separate_from_science_maturity():
    result = assess_v1_readiness(_deck(dates=1), _backups())
    assert result.product_ready is True
    assert result.product_state == "V1_OPERATIONALLY_READY"
    assert result.scientific_state == "PROSPECTIVE_CALIBRATION_ACCUMULATING"


def test_runtime_gate_requires_daemon_and_theta():
    result = assess_v1_readiness(_deck(), _backups(), require_runtime=True)
    assert result.product_ready is False
    failures = {c.name for c in result.checks if c.state == "FAIL"}
    assert {"research-daemon", "theta-terminal"}.issubset(failures)


def test_runtime_gate_passes_with_healthy_runtime():
    result = assess_v1_readiness(
        _deck(daemon="HEALTHY", theta_ready=True),
        _backups(),
        require_runtime=True,
    )
    assert result.product_ready is True


def test_stale_backup_is_blocking():
    result = assess_v1_readiness(_deck(), _backups(age=40.0))
    assert result.product_ready is False
    assert any(c.name == "verified-backup" and c.state == "FAIL" for c in result.checks)


def test_model_decision_firewall_is_blocking():
    deck = _deck()
    deck["models"][0]["decision_enabled"] = 1
    result = assess_v1_readiness(deck, _backups())
    assert result.product_ready is False


def test_scientific_milestone_labels():
    assert assess_v1_readiness(_deck(dates=5), _backups()).scientific_state == "FIRST_DESCRIPTIVE_REVIEW_REACHED"
    assert assess_v1_readiness(_deck(dates=20), _backups()).scientific_state == "PREREG_REVIEW_THRESHOLD_REACHED"
