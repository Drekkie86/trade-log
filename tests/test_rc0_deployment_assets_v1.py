from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_deep_health_timer_is_not_five_minute_io_loop():
    text = (
        ROOT
        / "deploy/systemd/christiania-health.timer"
    ).read_text(encoding="utf-8")
    assert "OnUnitActiveSec=6h" in text
    assert "OnUnitActiveSec=5m" not in text


def test_lightweight_supervisor_runs_every_five_minutes():
    text = (
        ROOT
        / "deploy/systemd/christiania-supervisor.timer"
    ).read_text(encoding="utf-8")
    assert "OnUnitActiveSec=5m" in text
    assert "Persistent=true" in text


def test_supervisor_service_allows_only_sqlite_data_and_audit_writes():
    text = (
        ROOT
        / "deploy/systemd/christiania-supervisor.service"
    ).read_text(encoding="utf-8")
    assert "ProtectSystem=strict" in text
    assert (
        "ReadWritePaths=/var/lib/christiania/data "
        "/var/lib/christiania/audit"
    ) in text
    assert "ReadWritePaths=/var/lib/christiania/audit\n" not in text
    assert "christiania_rc0_supervisor.py" in text


def test_core_services_have_exact_memory_containment_policy():
    expected = {
        "christiania-theta.service": (
            "MemoryHigh=1536M",
            "MemoryMax=2560M",
        ),
        "christiania-daemon.service": (
            "MemoryHigh=768M",
            "MemoryMax=1280M",
        ),
        "christiania-app.service": (
            "MemoryHigh=512M",
            "MemoryMax=1024M",
        ),
    }

    for unit, (memory_high, memory_max) in expected.items():
        text = (
            ROOT / "deploy/systemd" / unit
        ).read_text(encoding="utf-8")
        assert memory_high in text
        assert memory_max in text
        assert "OOMPolicy=stop" in text


def test_failure_injection_contains_no_database_mutation_commands():
    text = (
        ROOT
        / "deploy/rc0_failure_injection.sh"
    ).read_text(encoding="utf-8").lower()

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
    found = [token for token in forbidden if token in text]
    assert found == []


def test_bootstrap_never_enables_firewall_implicitly():
    text = (
        ROOT
        / "deploy/bootstrap_ubuntu_2404_rc0.sh"
    ).read_text(encoding="utf-8")
    assert "ufw enable" not in text
    assert "openjdk-21-jre-headless" in text
