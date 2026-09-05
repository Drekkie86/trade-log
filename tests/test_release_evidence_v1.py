from __future__ import annotations

from src.operations import release_evidence as re


def test_release_evidence_export_is_json_and_contains_no_secret_values(monkeypatch, tmp_path):
    monkeypatch.setattr(re, "load_command_deck", lambda include_provider_health=True: {
        "ready": True,
        "database": {"quick_check": "ok", "foreign_key_violation_count": 0, "journal_mode": "wal"},
        "market_clock": {"state": "NON_SESSION_DAY", "next_sample_at": "x"},
        "daemon_health": {"state": "HEALTHY"},
        "theta_health": {"state": "READY", "ready": True},
        "models": [{"decision_enabled": False, "admission_enabled": False}],
        "prospective": {"independent_dates": 1},
        "theta_timestamp_semantics": {"confidence_state": "DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED"},
    })
    monkeypatch.setattr(re, "inventory_backups", lambda: type("X", (), {"as_dict": lambda self: {"valid_files": 1, "latest_valid_age_hours": 1.0}})())
    monkeypatch.setattr(re, "build_release_manifest", lambda: type("M", (), {"as_dict": lambda self: {"git_sha": "abc", "git_clean": True}})())
    monkeypatch.setattr(re, "inspect_secure_edge_configuration", lambda: type("E", (), {"as_dict": lambda self: {"ready": True, "public_host": "example.test"}})())
    monkeypatch.setattr(re, "read_burn_in_samples", lambda: ())
    monkeypatch.setattr(re, "current_boot_id", lambda: "boot")
    path = re.export_release_evidence(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "CHRISTIANIA_V1_RELEASE_EVIDENCE" in text
    assert "client_secret" not in text.lower()
    assert "cookie_secret" not in text.lower()
    assert "api_key" not in text.lower()
