from datetime import UTC, datetime, timedelta
import json

from src.operations.v1_operational_readiness import (
    evaluate_operational_readiness,
)


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
SHA = "a" * 40


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _settings():
    return {
        "CHRISTIANIA_REQUIRE_EXTERNAL_OBSERVABILITY": "1",
        "CHRISTIANIA_ALERT_WEBHOOK_URL": "https://alerts.example.invalid/x",
        "CHRISTIANIA_HEARTBEAT_URL": "https://heartbeat.example.invalid/ok",
        "CHRISTIANIA_HEARTBEAT_FAILURE_URL": "https://heartbeat.example.invalid/fail",
        "CHRISTIANIA_V1_SUPERVISOR_MAX_AGE_MINUTES": "12",
    }


def _healthy_supervisor(observed_at):
    return {
        "observed_at": observed_at.isoformat(),
        "state": "HEALTHY",
        "checks": [
            {
                "name": "research-progress",
                "state": "PASS",
                "detail": "Research production current.",
            }
        ],
    }


def _healthy_state(observed_at):
    return {
        "observed_at": observed_at.isoformat(),
        "state": "HEALTHY",
        "heartbeat_state": "SENT",
    }


def _evaluate(tmp_path, supervisor=None, state=None, settings=None):
    audit = tmp_path / "audit"
    audit.mkdir()
    commit = tmp_path / "DEPLOYED_COMMIT"
    commit.write_text(SHA + "\n", encoding="utf-8")
    _write_json(
        audit / "rc0_supervisor_status.json",
        supervisor or _healthy_supervisor(NOW - timedelta(minutes=2)),
    )
    _write_json(
        audit / "rc0_supervisor_state.json",
        state or _healthy_state(NOW - timedelta(minutes=2)),
    )
    return evaluate_operational_readiness(
        now=NOW,
        audit_dir=audit,
        deployed_commit_path=commit,
        settings=settings or _settings(),
        service_state=lambda unit: "active",
        timer_enabled=lambda unit: "enabled",
    )


def test_operational_readiness_passes_only_with_research_and_external_proof(tmp_path):
    report = _evaluate(tmp_path)
    assert report.operationally_ready is True
    assert report.state == "OPERATIONALLY_READY"


def test_missing_research_progress_blocks_even_when_supervisor_claims_healthy(tmp_path):
    supervisor = _healthy_supervisor(NOW - timedelta(minutes=2))
    supervisor["checks"] = []
    report = _evaluate(tmp_path, supervisor=supervisor)
    assert report.operationally_ready is False
    check = next(c for c in report.checks if c.name == "research-production-proof")
    assert check.state == "FAIL"


def test_stale_supervisor_blocks_operational_readiness(tmp_path):
    report = _evaluate(
        tmp_path,
        supervisor=_healthy_supervisor(NOW - timedelta(minutes=30)),
    )
    assert report.operationally_ready is False
    check = next(c for c in report.checks if c.name == "supervisor-status-freshness")
    assert check.state == "FAIL"


def test_external_observability_must_be_fail_closed(tmp_path):
    settings = _settings()
    settings["CHRISTIANIA_REQUIRE_EXTERNAL_OBSERVABILITY"] = "0"
    report = _evaluate(tmp_path, settings=settings)
    assert report.operationally_ready is False
    check = next(c for c in report.checks if c.name == "external-observability-required")
    assert check.state == "FAIL"


def test_recent_external_heartbeat_must_have_been_sent(tmp_path):
    state = _healthy_state(NOW - timedelta(minutes=2))
    state["heartbeat_state"] = "FAILED"
    report = _evaluate(tmp_path, state=state)
    assert report.operationally_ready is False
    check = next(c for c in report.checks if c.name == "external-heartbeat-freshness")
    assert check.state == "FAIL"


def test_inactive_daemon_blocks_operational_readiness(tmp_path):
    audit = tmp_path / "audit"
    audit.mkdir()
    commit = tmp_path / "DEPLOYED_COMMIT"
    commit.write_text(SHA + "\n", encoding="utf-8")
    _write_json(
        audit / "rc0_supervisor_status.json",
        _healthy_supervisor(NOW - timedelta(minutes=2)),
    )
    _write_json(
        audit / "rc0_supervisor_state.json",
        _healthy_state(NOW - timedelta(minutes=2)),
    )
    report = evaluate_operational_readiness(
        now=NOW,
        audit_dir=audit,
        deployed_commit_path=commit,
        settings=_settings(),
        service_state=lambda unit: (
            "inactive" if unit == "christiania-daemon.service" else "active"
        ),
        timer_enabled=lambda unit: "enabled",
    )
    assert report.operationally_ready is False
