from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_windows_deployer_exposes_explicit_recovery_switch():
    script = _read("deploy/deploy_release.ps1")

    assert "[switch]$RecoveryNoSchemaChange" in script
    assert "--recovery-no-schema-change" in script


def test_receiver_recovery_mode_requires_same_schema():
    script = _read("deploy/receive_release.sh")

    assert "validate_target_no_schema_change" in script
    assert (
        "Recovery deployment refused: target release expects schema"
        in script
    )
    assert "health.schema_version != EXPECTED_SCHEMA_VERSION" in script


def test_receiver_recovery_gate_only_waives_backup_debt():
    script = _read("deploy/receive_release.sh")

    assert '"backup-freshness-metadata"' in script
    assert '"backup-recovery-point"' in script

    for required in (
        '"release_identity_state": "PASS"',
        '"core_services_state": "PASS"',
        '"supervisor_freshness_state": "PASS"',
        '"resource_policy_state": "PASS"',
    ):
        assert required in script

    assert (
        "Recovery deployment refused by supervisor check"
        in script
    )


def test_recovery_mode_does_not_disable_normal_deployment_gate():
    script = _read("deploy/receive_release.sh")

    assert "--deployment-safe" in script
    assert 'if [[ "${RECOVERY_NO_SCHEMA_CHANGE}" -eq 1 ]]; then' in script


def test_bounded_compression_timer_is_staged_but_not_enabled_by_policy():
    supervisor = _read("src/operations/rc0_supervisor.py")
    timer = _read(
        "deploy/systemd/christiania-backup-compress.timer"
    )
    service = _read(
        "deploy/systemd/christiania-backup-compress.service"
    )

    disabled_block = supervisor.split(
        "INTENTIONALLY_DISABLED_TIMERS = (",
        1,
    )[1].split(")", 1)[0]

    assert "christiania-backup-compress.timer" in disabled_block
    assert "OnCalendar=*-*-* 03:30:00 UTC" in timer
    assert "--max-files 1" in service
