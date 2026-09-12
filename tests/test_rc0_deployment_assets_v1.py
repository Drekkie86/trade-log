from pathlib import Path

from src.operations.service_resources import (
    SERVICE_RESOURCE_POLICIES,
)
from src.operations.systemd_resources import (
    expected_dropin_text,
)


ROOT = Path(__file__).resolve().parents[1]


def test_deep_health_timer_is_not_five_minute_io_loop():
    text = (
        ROOT
        / "deploy/systemd/christiania-health.timer"
    ).read_text(
        encoding="utf-8"
    )

    assert "OnUnitActiveSec=6h" in text
    assert "OnUnitActiveSec=5m" not in text


def test_lightweight_supervisor_runs_every_five_minutes():
    text = (
        ROOT
        / "deploy/systemd/christiania-supervisor.timer"
    ).read_text(
        encoding="utf-8"
    )

    assert "OnUnitActiveSec=5m" in text
    assert "Persistent=true" in text


def test_supervisor_service_allows_only_sqlite_data_and_audit_writes():
    text = (
        ROOT
        / "deploy/systemd/christiania-supervisor.service"
    ).read_text(
        encoding="utf-8"
    )

    assert "ProtectSystem=strict" in text

    assert (
        "ReadWritePaths=/var/lib/christiania/data "
        "/var/lib/christiania/audit"
        in text
    )

    assert (
        "ReadWritePaths=/var/lib/christiania/audit\n"
        not in text
    )

    assert (
        "christiania_rc0_supervisor.py"
        in text
    )


def test_core_unit_files_do_not_duplicate_resource_policy():
    for unit in (
        "christiania-theta.service",
        "christiania-daemon.service",
        "christiania-app.service",
    ):
        text = (
            ROOT
            / "deploy/systemd"
            / unit
        ).read_text(
            encoding="utf-8"
        )

        assert "MemoryHigh=" not in text
        assert "MemoryMax=" not in text
        assert "OOMPolicy=" not in text
        assert "TimeoutStartSec=" not in text
        assert "TimeoutStopSec=" not in text


def test_canonical_policy_generates_core_resource_limits():
    expected = {
        "christiania-theta.service": {
            "MemoryHigh": 1610612736,
            "MemoryMax": 2684354560,
            "TimeoutStartSec": 90,
            "TimeoutStopSec": 90,
        },
        "christiania-daemon.service": {
            "MemoryHigh": 805306368,
            "MemoryMax": 1342177280,
            "TimeoutStartSec": 90,
            "TimeoutStopSec": 90,
        },
        "christiania-app.service": {
            "MemoryHigh": 536870912,
            "MemoryMax": 1073741824,
            "TimeoutStartSec": 90,
            "TimeoutStopSec": 90,
        },
    }

    for unit, values in expected.items():
        policy = (
            SERVICE_RESOURCE_POLICIES[
                unit
            ]
        )

        assert (
            policy.memory_high_bytes
            == values["MemoryHigh"]
        )

        assert (
            policy.memory_max_bytes
            == values["MemoryMax"]
        )

        assert (
            policy.timeout_start_seconds
            == values["TimeoutStartSec"]
        )

        assert (
            policy.timeout_stop_seconds
            == values["TimeoutStopSec"]
        )

        assert policy.oom_policy == "stop"

        dropin = expected_dropin_text(
            unit
        )

        assert (
            f"MemoryHigh={values['MemoryHigh']}"
            in dropin
        )

        assert (
            f"MemoryMax={values['MemoryMax']}"
            in dropin
        )

        assert (
            f"TimeoutStartSec={values['TimeoutStartSec']}s"
            in dropin
        )

        assert (
            f"TimeoutStopSec={values['TimeoutStopSec']}s"
            in dropin
        )

        assert "OOMPolicy=stop" in dropin


def test_all_14_services_have_canonical_resource_policy():
    assert (
        len(
            SERVICE_RESOURCE_POLICIES
        )
        == 14
    )

    for unit, policy in (
        SERVICE_RESOURCE_POLICIES.items()
    ):
        assert (
            policy.memory_high_bytes
            > 0
        )

        assert (
            policy.memory_max_bytes
            > policy.memory_high_bytes
        )

        assert (
            policy.timeout_start_seconds
            > 0
        )

        assert (
            policy.timeout_stop_seconds
            > 0
        )

        assert (
            policy.oom_policy
            == "stop"
        )

        dropin = expected_dropin_text(
            unit
        )

        assert "[Service]" in dropin
        assert "MemoryHigh=" in dropin
        assert "MemoryMax=" in dropin
        assert "TimeoutStartSec=" in dropin
        assert "TimeoutStopSec=" in dropin
        assert "OOMPolicy=stop" in dropin


def test_failure_injection_contains_no_database_mutation_commands():
    text = (
        ROOT
        / "deploy/rc0_failure_injection.sh"
    ).read_text(
        encoding="utf-8"
    ).lower()

    forbidden = (
        "sqlite3 ",
        "rm ",
        "mv ",
        "truncate ",
        "dd ",
        "sed -i",
        "trade_log.db",
        "update ",
        "delete ",
        "drop table",
    )

    found = [
        token
        for token in forbidden
        if token in text
    ]

    assert found == []


def test_bootstrap_never_enables_firewall_implicitly():
    text = (
        ROOT
        / "deploy/bootstrap_ubuntu_2404_rc0.sh"
    ).read_text(
        encoding="utf-8"
    )

    assert "ufw enable" not in text
    assert (
        "openjdk-21-jre-headless"
        in text
    )


def test_legacy_installer_still_materializes_deployed_commit_identity():
    text = (
        ROOT
        / "deploy/install_one_vm.sh"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'git -C "${SOURCE_DIR}" rev-parse HEAD'
        in text
    )

    assert (
        '"${APP_DIR}/DEPLOYED_COMMIT"'
        in text
    )

    assert "--exclude '.git'" in text


def test_legacy_installer_wildcard_covers_reliability_units():
    installer = (
        ROOT
        / "deploy/install_one_vm.sh"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "deploy/systemd/"
        "christiania-*.service"
        in installer
    )

    assert (
        "deploy/systemd/"
        "christiania-*.timer"
        in installer
    )


def test_research_daemon_does_not_die_with_theta_dependency():
    text = (
        ROOT
        / "deploy/systemd/christiania-daemon.service"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "After=network-online.target "
        "christiania-theta.service"
        in text
    )

    assert (
        "Wants=network-online.target "
        "christiania-theta.service"
        in text
    )

    assert (
        "Requires=christiania-theta.service"
        not in text
    )