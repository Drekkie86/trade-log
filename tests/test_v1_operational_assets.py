from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v1_readiness_timer_is_frequent_persistent_and_delayed_after_boot():
    text = (
        ROOT
        / "deploy/systemd/christiania-v1-readiness.timer"
    ).read_text(encoding="utf-8")
    assert "OnBootSec=7m" in text
    assert "OnUnitActiveSec=5m" in text
    assert "Persistent=true" in text


def test_v1_readiness_service_is_read_only_except_audit_output():
    text = (
        ROOT
        / "deploy/systemd/christiania-v1-readiness.service"
    ).read_text(encoding="utf-8")
    assert "ProtectSystem=strict" in text
    assert "ReadWritePaths=/var/lib/christiania/audit" in text
    assert "EnvironmentFile=/etc/christiania/christiania.env" in text
    assert "christiania_v1_operational_readiness.py --json" in text


def test_operational_activation_runs_core_reliability_and_fail_closed_gate():
    text = (
        ROOT
        / "deploy/activate_operational_independence.sh"
    ).read_text(encoding="utf-8")
    assert "activate_one_vm.sh" in text
    assert "activate_reliability_baseline.sh" in text
    assert "enable --now christiania-v1-readiness.timer" in text
    assert "start christiania-supervisor.service" in text
    assert "start christiania-v1-readiness.service" in text


def test_production_env_documents_v1_fail_closed_observability_gate():
    text = (
        ROOT
        / "deploy/christiania.env.example"
    ).read_text(encoding="utf-8")
    assert "CHRISTIANIA_V1_SUPERVISOR_MAX_AGE_MINUTES=12" in text
    assert "CHRISTIANIA_REQUIRE_EXTERNAL_OBSERVABILITY=0" in text
    assert "activate_operational_independence.sh" in text
