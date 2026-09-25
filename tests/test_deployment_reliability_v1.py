from pathlib import Path
from types import SimpleNamespace

import pytest

from run_theta_terminal import (
    theta_auth_mode,
    theta_command,
)
from src.operations.sqlite_runtime import create_verified_backup


ROOT = Path(__file__).resolve().parents[1]


def test_systemd_app_binds_loopback_only():
    unit = (
        ROOT
        / "deploy/systemd/christiania-app.service"
    ).read_text(encoding="utf-8")

    assert "--host 127.0.0.1" in unit
    assert "--host 0.0.0.0" not in unit


def test_systemd_daemon_wants_theta_and_restarts():
    unit = (
        ROOT
        / "deploy/systemd/christiania-daemon.service"
    ).read_text(encoding="utf-8")

    assert "After=network-online.target christiania-theta.service" in unit
    assert "Wants=network-online.target christiania-theta.service" in unit
    assert "Requires=christiania-theta.service" not in unit
    assert "Restart=always" in unit
    assert "KillSignal=SIGTERM" in unit


def test_backup_timer_is_persistent_and_after_market_hours():
    timer = (
        ROOT
        / "deploy/systemd/christiania-backup.timer"
    ).read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* 23:30:00 UTC" in timer
    assert "Persistent=true" in timer


def test_health_timer_uses_strict_daemon_health():
    service = (
        ROOT
        / "deploy/systemd/christiania-health.service"
    ).read_text(encoding="utf-8")

    assert "--strict-daemon" in service
    assert "--json" in service


def test_deployment_env_contains_current_26_symbol_universe():
    env = (
        ROOT
        / "deploy/christiania.env.example"
    ).read_text(encoding="utf-8")

    line = next(
        value
        for value in env.splitlines()
        if value.startswith("CHRISTIANIA_SYMBOLS=")
    )
    symbols = line.split("=", 1)[1].split(",")

    assert len(symbols) == 26
    assert len(symbols) == len(set(symbols))
    assert {"AAPL", "SPY", "IBIT"}.issubset(symbols)


def test_theta_command_uses_only_java_jar(monkeypatch, tmp_path):
    jar = tmp_path / "ThetaTerminalv3.jar"
    jar.write_bytes(b"jar")

    monkeypatch.setenv(
        "CHRISTIANIA_THETA_JAR",
        str(jar),
    )
    monkeypatch.setattr(
        "run_theta_terminal.shutil.which",
        lambda name: "/usr/bin/java" if name == "java" else None,
    )

    assert theta_command() == [
        "/usr/bin/java",
        "-jar",
        str(jar),
    ]


def test_theta_command_refuses_missing_jar(monkeypatch):
    monkeypatch.setenv(
        "CHRISTIANIA_THETA_JAR",
        "/missing/ThetaTerminalv3.jar",
    )

    with pytest.raises(
        RuntimeError,
        match="not found",
    ):
        theta_command()


def test_deploy_preflight_passes_for_complete_runtime(
    monkeypatch,
    db_path,
    tmp_path,
):
    import christiania_deploy_preflight as preflight

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    create_verified_backup(
        db_path=db_path,
        backup_dir=backup_dir,
        retention=3,
    )
    theta = tmp_path / "ThetaTerminalv3.jar"
    theta.write_bytes(b"jar")

    monkeypatch.setenv(
        "CHRISTIANIA_DB_PATH",
        str(db_path.resolve()),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_BACKUP_DIR",
        str(backup_dir.resolve()),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_AUDIT_DIR",
        str(audit_dir.resolve()),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_THETA_JAR",
        str(theta.resolve()),
    )
    monkeypatch.setenv(
        "MASSIVE_API_KEY",
        "test-secret",
    )
    monkeypatch.setenv(
        "THETADATA_API_KEY",
        "theta-test-secret",
    )
    monkeypatch.setenv(
        "CHRISTIANIA_SYMBOLS",
        "AAPL,SPY",
    )
    monkeypatch.setattr(
        preflight.shutil,
        "which",
        lambda name: "/usr/bin/java" if name == "java" else None,
    )
    monkeypatch.setattr(
        preflight.importlib.metadata,
        "version",
        lambda name: "1.50.0" if name == "streamlit" else "0",
    )

    checks = preflight.run_preflight()

    assert all(
        check.state == "PASS"
        for check in checks
    )


def test_deploy_preflight_uses_fast_backup_inventory_by_default(
    monkeypatch,
    db_path,
    tmp_path,
):
    import christiania_deploy_preflight as preflight

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    theta = tmp_path / "ThetaTerminalv3.jar"
    theta.write_bytes(b"jar")

    monkeypatch.setenv(
        "CHRISTIANIA_DB_PATH",
        str(db_path.resolve()),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_BACKUP_DIR",
        str(backup_dir.resolve()),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_AUDIT_DIR",
        str(audit_dir.resolve()),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_THETA_JAR",
        str(theta.resolve()),
    )
    monkeypatch.setenv(
        "MASSIVE_API_KEY",
        "test-secret",
    )
    monkeypatch.setenv(
        "THETADATA_API_KEY",
        "theta-test-secret",
    )
    monkeypatch.setenv(
        "CHRISTIANIA_SYMBOLS",
        "AAPL,SPY",
    )
    monkeypatch.setattr(
        preflight.shutil,
        "which",
        lambda name: "/usr/bin/java" if name == "java" else None,
    )
    monkeypatch.setattr(
        preflight.importlib.metadata,
        "version",
        lambda name: "1.50.0" if name == "streamlit" else "0",
    )

    calls = {
        "fast": 0,
        "deep": 0,
    }

    def fake_fast(path):
        assert path == backup_dir.resolve()
        calls["fast"] += 1
        return SimpleNamespace(
            total_files=1,
            valid_files=0,
        )

    def forbidden_deep(path):
        calls["deep"] += 1
        raise AssertionError(
            "Normal deployment preflight must not deep-verify backups."
        )

    monkeypatch.setattr(
        preflight,
        "inventory_backups_fast",
        fake_fast,
    )
    monkeypatch.setattr(
        preflight,
        "inventory_backups",
        forbidden_deep,
    )

    checks = {
        check.name: check
        for check in preflight.run_preflight()
    }

    assert calls == {
        "fast": 1,
        "deep": 0,
    }
    assert checks["backup-file-available"].state == "PASS"
    assert "verified-backup-available" not in checks


def test_deploy_preflight_strict_backup_uses_deep_inventory(
    monkeypatch,
    db_path,
    tmp_path,
):
    import christiania_deploy_preflight as preflight

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    theta = tmp_path / "ThetaTerminalv3.jar"
    theta.write_bytes(b"jar")

    monkeypatch.setenv(
        "CHRISTIANIA_DB_PATH",
        str(db_path.resolve()),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_BACKUP_DIR",
        str(backup_dir.resolve()),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_AUDIT_DIR",
        str(audit_dir.resolve()),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_THETA_JAR",
        str(theta.resolve()),
    )
    monkeypatch.setenv(
        "MASSIVE_API_KEY",
        "test-secret",
    )
    monkeypatch.setenv(
        "THETADATA_API_KEY",
        "theta-test-secret",
    )
    monkeypatch.setenv(
        "CHRISTIANIA_SYMBOLS",
        "AAPL,SPY",
    )
    monkeypatch.setattr(
        preflight.shutil,
        "which",
        lambda name: "/usr/bin/java" if name == "java" else None,
    )
    monkeypatch.setattr(
        preflight.importlib.metadata,
        "version",
        lambda name: "1.50.0" if name == "streamlit" else "0",
    )

    calls = {
        "fast": 0,
        "deep": 0,
    }

    def forbidden_fast(path):
        calls["fast"] += 1
        raise AssertionError(
            "Strict deployment preflight must deep-verify backups."
        )

    def fake_deep(path):
        assert path == backup_dir.resolve()
        calls["deep"] += 1
        return SimpleNamespace(
            total_files=1,
            valid_files=1,
        )

    monkeypatch.setattr(
        preflight,
        "inventory_backups_fast",
        forbidden_fast,
    )
    monkeypatch.setattr(
        preflight,
        "inventory_backups",
        fake_deep,
    )

    checks = {
        check.name: check
        for check in preflight.run_preflight(
            strict_backup=True,
        )
    }

    assert calls == {
        "fast": 0,
        "deep": 1,
    }
    assert checks["verified-backup-available"].state == "PASS"
    assert "backup-file-available" not in checks


def test_deploy_preflight_rejects_backup_in_live_db_directory(
    monkeypatch,
    db_path,
    tmp_path,
):
    import christiania_deploy_preflight as preflight

    theta = tmp_path / "ThetaTerminalv3.jar"
    theta.write_bytes(b"jar")

    monkeypatch.setenv(
        "CHRISTIANIA_DB_PATH",
        str(db_path.resolve()),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_BACKUP_DIR",
        str(db_path.resolve().parent),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_THETA_JAR",
        str(theta.resolve()),
    )
    monkeypatch.setenv(
        "MASSIVE_API_KEY",
        "test-secret",
    )
    monkeypatch.setenv(
        "CHRISTIANIA_SYMBOLS",
        "AAPL,SPY",
    )
    monkeypatch.setattr(
        preflight.shutil,
        "which",
        lambda name: "/usr/bin/java" if name == "java" else None,
    )

    checks = {
        check.name: check
        for check in preflight.run_preflight()
    }

    assert (
        checks["backup-separation"].state
        == "FAIL"
    )


def test_theta_auth_mode_prefers_environment_api_key(monkeypatch, tmp_path):
    jar = tmp_path / "ThetaTerminalv3.jar"
    jar.write_bytes(b"jar")

    monkeypatch.setenv("CHRISTIANIA_THETA_JAR", str(jar))
    monkeypatch.setenv("THETADATA_API_KEY", "secret")

    assert theta_auth_mode() == "API_KEY_ENV"


def test_theta_auth_mode_accepts_creds_beside_jar(monkeypatch, tmp_path):
    jar = tmp_path / "ThetaTerminalv3.jar"
    jar.write_bytes(b"jar")
    (tmp_path / "creds.txt").write_text(
        "user@example.com\npassword\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("CHRISTIANIA_THETA_JAR", str(jar))
    monkeypatch.delenv("THETADATA_API_KEY", raising=False)

    assert theta_auth_mode() == "CREDS_FILE"


def test_theta_auth_mode_refuses_missing_credentials(monkeypatch, tmp_path):
    jar = tmp_path / "ThetaTerminalv3.jar"
    jar.write_bytes(b"jar")

    monkeypatch.setenv("CHRISTIANIA_THETA_JAR", str(jar))
    monkeypatch.delenv("THETADATA_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="authentication is not configured"):
        theta_auth_mode()


def test_systemd_theta_and_daemon_have_explicit_restart_limits():
    for name in (
        "christiania-theta.service",
        "christiania-daemon.service",
    ):
        unit = (
            ROOT
            / "deploy/systemd"
            / name
        ).read_text(encoding="utf-8")

        assert "StartLimitIntervalSec=300" in unit
        assert "StartLimitBurst=5" in unit
        assert "RestartSec=15" in unit


def test_one_vm_installer_uses_explicit_env_file_for_manual_preflight():
    script = (ROOT / "deploy/install_one_vm.sh").read_text(encoding="utf-8")
    assert "christiania_deploy_preflight.py --env-file ${ENV_DIR}/christiania.env --require-theta-live" in script


def test_systemd_app_has_explicit_restart_limits():
    unit = (ROOT / "deploy/systemd/christiania-app.service").read_text(encoding="utf-8")
    assert "StartLimitIntervalSec=300" in unit
    assert "StartLimitBurst=5" in unit
    assert "Restart=on-failure" in unit

def test_streamlit_runs_under_proven_backend_identity():
    unit = (
        ROOT
        / "deploy/systemd/christiania-app.service"
    ).read_text(encoding="utf-8")

    assert "User=christiania" in unit
    assert "Group=christiania" in unit
    assert (
        "EnvironmentFile=/etc/christiania/christiania.env"
        in unit
    )
    assert "ReadWritePaths=/var/lib/christiania/data" in unit
    assert "User=christiania-ui" not in unit
    assert "Group=christiania-runtime" not in unit
    assert "IPAddressDeny=any" not in unit


def test_runtime_identity_provisioning_shares_only_read_surfaces():
    script = (
        ROOT
        / "deploy/provision_runtime_identities.sh"
    ).read_text(encoding="utf-8")

    assert 'RUNTIME_GROUP="${CHRISTIANIA_RUNTIME_GROUP:-christiania-runtime}"' in script
    assert 'UI_USER="${CHRISTIANIA_UI_USER:-christiania-ui}"' in script

    for directory in (
        '"${STATE_ROOT}/data"',
        '"${STATE_ROOT}/backups"',
        '"${STATE_ROOT}/audit"',
    ):
        assert directory in script

    assert '"${STATE_ROOT}/release-rollbacks"' not in script
    assert '"${STATE_ROOT}/evidence-archives"' not in script
    assert "chgrp -R" in script
    assert "--groups \"\"" in script
    assert "chmod u=rwx,g=rx,o=" in script
    assert "chmod u=rw,g=r,o=" in script
    assert "g+s" in script


def test_legacy_installer_renders_nonsecret_ui_environment():
    script = (
        ROOT
        / "deploy/install_one_vm.sh"
    ).read_text(encoding="utf-8")

    assert "provision_runtime_identities.sh" in script
    assert "christiania_ui_env.py" in script
    assert 'UI_ENV_ROOT="/etc/christiania-ui"' in script
    assert 'chown -R root:"${RUNTIME_GROUP}" "${APP_DIR}"' in script
    assert 'chown -R root:"${SERVICE_USER}" "${APP_DIR}/vendor"' in script

def test_clean_installer_uses_locked_runtime_and_checks_dependency_health():
    installer = (
        ROOT
        / "deploy/install_one_vm.sh"
    ).read_text(encoding="utf-8")

    assert "requirements-lock-linux-py313.txt" in installer
    assert "--no-deps" in installer
    assert "-m pip check" in installer
    assert 'grep -vE' in installer
    assert 'LC_ALL=C sort -f' in installer


def test_quality_gate_verifies_runtime_lock_without_deferred_ui_rehearsal():
    workflow = (
        ROOT
        / ".github/workflows/quality-gate.yml"
    ).read_text(encoding="utf-8")

    assert "Resolve clean Linux production runtime" in workflow
    assert "committed-runtime-lock-linux-py313.txt" in workflow
    assert "resolved-runtime-lock-linux-py313.txt" in workflow
    assert "diff -u" in workflow
    assert "Prove real Christiania readonly helper under provisioned UI" not in workflow

def test_clean_installer_prefers_python_313_without_replacing_system_python():
    installer = (
        ROOT
        / "deploy/install_one_vm.sh"
    ).read_text(encoding="utf-8")

    assert "resolve_python_313()" in installer
    assert "for candidate in python3.13 python3; do" in installer
    assert 'PYTHON_BIN="$(resolve_python_313)"' in installer
    assert '"${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"' in installer
    assert "update-alternatives" not in installer
    assert "/usr/bin/python3" not in installer

def test_runtime_identity_provisioning_removes_preexisting_group_write_bits():
    script = (
        ROOT
        / "deploy/provision_runtime_identities.sh"
    ).read_text(encoding="utf-8")

    # The provisioning pass must converge existing files to group read-only,
    # not merely add read permission and leave an old group-write bit intact.
    assert "chmod u=rw,g=r,o=" in script
    assert "chmod u+rw,g+r,o-rwx" not in script

def test_dashboard_reads_normalized_admission_view_without_temp_compatibility():
    read_model = (
        ROOT
        / "src/dashboard/read_model.py"
    ).read_text(encoding="utf-8")

    assert (
        read_model.count(
            "v_shadow_admission_decisions_all"
        )
        == 5
    )
    assert (
        "FROM shadow_admission_decisions"
        not in read_model
    )
    assert (
        "JOIN shadow_admission_decisions AS sad"
        not in read_model
    )

    sqlite_runtime = (
        ROOT
        / "src/operations/sqlite_runtime.py"
    ).read_text(encoding="utf-8")

    assert "CREATE TEMP VIEW shadow_admission_decisions" not in sqlite_runtime
    assert "_install_readonly_compatibility_views" not in sqlite_runtime
