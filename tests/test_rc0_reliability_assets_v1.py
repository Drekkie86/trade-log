from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_theta_watchdog_has_thresholded_failure_recovery():
    service = read(
        "deploy/systemd/christiania-theta-watchdog.service"
    )
    timer = read(
        "deploy/systemd/christiania-theta-watchdog.timer"
    )
    assert "OnFailure=christiania-theta-recover.service" in service
    assert "User=christiania" in service
    assert "Requires=christiania-theta.service" not in service
    assert "After=network-online.target christiania-theta.service" in service
    assert "OnUnitActiveSec=60s" in timer
    assert "Persistent=true" in timer


def test_theta_recovery_is_root_and_preventive_refresh_is_off_market():
    recovery = read(
        "deploy/systemd/christiania-theta-recover.service"
    )
    refresh_service = read(
        "deploy/systemd/christiania-theta-refresh.service"
    )
    refresh_timer = read(
        "deploy/systemd/christiania-theta-refresh.timer"
    )
    assert "User=root" in recovery
    assert "--reason watchdog-threshold" in recovery
    assert "User=root" in refresh_service
    assert "--reason preventive-daily-refresh" in refresh_service
    assert "OnCalendar=*-*-* 08:00:00 UTC" in refresh_timer


def test_env_example_contains_external_observability_contract():
    env = read("deploy/christiania.env.example")
    assert "CHRISTIANIA_ALERT_WEBHOOK_URL=" in env
    assert "CHRISTIANIA_HEARTBEAT_URL=" in env
    assert "CHRISTIANIA_HEARTBEAT_FAILURE_URL=" in env
    assert "CHRISTIANIA_REQUIRE_EXTERNAL_OBSERVABILITY=0" in env
