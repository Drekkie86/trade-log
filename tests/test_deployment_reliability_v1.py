from pathlib import Path

import pytest

from run_theta_terminal import (
    theta_auth_mode,
    theta_command,
)


ROOT = Path(__file__).resolve().parents[1]


def test_systemd_app_binds_loopback_only():
    unit = (
        ROOT
        / "deploy/systemd/christiania-app.service"
    ).read_text(encoding="utf-8")

    assert "--host 127.0.0.1" in unit
    assert "--host 0.0.0.0" not in unit


def test_systemd_daemon_requires_theta_and_restarts():
    unit = (
        ROOT
        / "deploy/systemd/christiania-daemon.service"
    ).read_text(encoding="utf-8")

    assert "Requires=christiania-theta.service" in unit
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
