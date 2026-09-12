from pathlib import Path

from src.operations.service_resources import (
    MIB,
    SERVICE_RESOURCE_POLICIES,
    managed_service_units,
    service_resource_policy,
    systemd_dropin_text,
)
from src.operations.systemd_resources import (
    check_resource_dropins,
    dropin_path,
    write_resource_dropins,
)


EXPECTED_UNITS = {
    "christiania-app.service",
    "christiania-audit.service",
    "christiania-backup.service",
    "christiania-burn-in.service",
    "christiania-daemon.service",
    "christiania-health.service",
    "christiania-oauth2-proxy.service",
    "christiania-restore-drill.service",
    "christiania-supervisor.service",
    "christiania-theta-recover.service",
    "christiania-theta-refresh.service",
    "christiania-theta-watchdog.service",
    "christiania-theta.service",
    "christiania-v1-readiness.service",
}


def test_resource_policy_covers_all_managed_services():
    assert set(
        managed_service_units()
    ) == EXPECTED_UNITS

    assert set(
        SERVICE_RESOURCE_POLICIES
    ) == EXPECTED_UNITS


def test_existing_core_limits_are_preserved():
    app = service_resource_policy(
        "christiania-app.service"
    )
    daemon = service_resource_policy(
        "christiania-daemon.service"
    )
    theta = service_resource_policy(
        "christiania-theta.service"
    )

    assert app.memory_high_bytes == 512 * MIB
    assert app.memory_max_bytes == 1024 * MIB

    assert daemon.memory_high_bytes == 768 * MIB
    assert daemon.memory_max_bytes == 1280 * MIB

    assert theta.memory_high_bytes == 1536 * MIB
    assert theta.memory_max_bytes == 2560 * MIB


def test_every_service_has_finite_resource_governance():
    for policy in SERVICE_RESOURCE_POLICIES.values():
        assert policy.memory_warning_bytes > 0
        assert policy.memory_high_bytes > 0
        assert policy.memory_max_bytes > 0

        assert (
            policy.memory_warning_bytes
            < policy.memory_high_bytes
            < policy.memory_max_bytes
        )

        assert policy.timeout_start_seconds > 0
        assert policy.timeout_stop_seconds > 0
        assert policy.oom_policy == "stop"


def test_watchdog_has_tight_start_timeout():
    watchdog = service_resource_policy(
        "christiania-theta-watchdog.service"
    )

    assert watchdog.timeout_start_seconds == 45


def test_oauth2_proxy_is_governed_before_enablement():
    proxy = service_resource_policy(
        "christiania-oauth2-proxy.service"
    )

    assert proxy.memory_high_bytes == 192 * MIB
    assert proxy.memory_max_bytes == 256 * MIB
    assert proxy.timeout_start_seconds == 90


def test_burn_in_cannot_consume_the_machine_again():
    burn_in = service_resource_policy(
        "christiania-burn-in.service"
    )

    assert burn_in.memory_high_bytes == 384 * MIB
    assert burn_in.memory_max_bytes == 512 * MIB
    assert burn_in.timeout_start_seconds == 180


def test_systemd_dropin_contains_complete_policy():
    policy = service_resource_policy(
        "christiania-supervisor.service"
    )

    text = systemd_dropin_text(
        policy
    )

    assert text == (
        "[Service]\n"
        f"MemoryHigh={192 * MIB}\n"
        f"MemoryMax={256 * MIB}\n"
        "TimeoutStartSec=120s\n"
        "TimeoutStopSec=90s\n"
        "OOMPolicy=stop\n"
    )


def test_write_and_check_resource_dropins(
    tmp_path: Path,
):
    written = write_resource_dropins(
        tmp_path
    )

    assert len(written) == len(
        EXPECTED_UNITS
    )

    assert all(
        path.is_file()
        for path in written
    )

    checks = check_resource_dropins(
        tmp_path
    )

    assert len(checks) == len(
        EXPECTED_UNITS
    )

    assert all(
        check.passed
        for check in checks
    )


def test_resource_check_detects_missing_dropin(
    tmp_path: Path,
):
    write_resource_dropins(
        tmp_path
    )

    missing = dropin_path(
        tmp_path,
        "christiania-health.service",
    )
    missing.unlink()

    checks = {
        check.unit: check
        for check in check_resource_dropins(
            tmp_path
        )
    }

    assert (
        checks[
            "christiania-health.service"
        ].state
        == "FAIL"
    )


def test_resource_check_detects_drift(
    tmp_path: Path,
):
    write_resource_dropins(
        tmp_path
    )

    drifted = dropin_path(
        tmp_path,
        "christiania-backup.service",
    )
    drifted.write_text(
        "[Service]\nMemoryMax=infinity\n",
        encoding="utf-8",
    )

    checks = {
        check.unit: check
        for check in check_resource_dropins(
            tmp_path
        )
    }

    assert (
        checks[
            "christiania-backup.service"
        ].state
        == "FAIL"
    )