from src.ui.home_pages import (
    eur_from_minor, num, results_verdict, system_checks, system_verdict,
)


def test_number_format_is_belgian():
    assert num(12345.67, 2) == "12.345,67"
    assert num(None) == "—"
    assert eur_from_minor(-12345, signed=True) == "-€123,45"
    assert eur_from_minor(500, signed=True) == "+€5,00"


def test_results_never_claims_proof():
    assert results_verdict({"resolved": 0})[0] == "warn"
    tone, head, _ = results_verdict({"resolved": 10, "resolved_expiration_dates": 2})
    assert tone == "warn" and "early" in head.lower()
    tone, head, _ = results_verdict(
        {"resolved": 40, "resolved_expiration_dates": 8, "total_net_eur_minor": 5000}
    )
    assert tone == "warn" and "not proven" in head.lower()
    assert results_verdict(
        {"resolved": 40, "resolved_expiration_dates": 8, "total_net_eur_minor": -1}
    )[0] == "bad"


def test_system_flags_missing_collector():
    snap = {"daemon_health": {"state": "NO_DAEMON_LEASE"},
            "database": {"quick_check": None, "schema_version": 36, "expected_schema_version": 36}}
    rows = system_checks(snap, {"state": "NOT_PROBED"}, {"total_files": 0})
    assert dict((r[0], r[1]) for r in rows)["Collector"] is False
    assert dict((r[0], r[1]) for r in rows)["Database"] is True
    assert system_verdict(rows)[0] == "bad"


def test_system_all_good():
    snap = {"daemon_health": {"state": "HEALTHY"},
            "database": {"quick_check": "ok", "schema_version": 36, "expected_schema_version": 36},
            "latest_iteration": {"status": "COMPLETED", "scheduled_for": "2026-10-16T13:45:00Z"}}
    rows = system_checks(snap, {"state": "READY", "ready": True},
                         {"total_files": 3, "latest_valid_age_hours": 5})
    assert system_verdict(rows)[0] == "good"
