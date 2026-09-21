from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import backup_christiania


def test_backup_entrypoint_only_creates_verified_backup(
    monkeypatch,
    capsys,
):
    calls = []

    decision = SimpleNamespace(
        due=True,
        reason="NEW_COMPLETED_RESEARCH_SINCE_BACKUP",
        as_dict=lambda: {
            "due": True,
            "reason": "NEW_COMPLETED_RESEARCH_SINCE_BACKUP",
        },
    )

    result = SimpleNamespace(
        backup_path="/tmp/christiania_backup_test.db",
        source_path="/tmp/trade_log.db",
        schema_version=33,
        integrity_check="ok",
        foreign_key_violation_count=0,
        pruned_count=0,
        as_dict=lambda: {
            "backup_path": "/tmp/christiania_backup_test.db",
            "source_path": "/tmp/trade_log.db",
            "schema_version": 33,
            "integrity_check": "ok",
            "foreign_key_violation_count": 0,
            "pruned_count": 0,
        },
    )

    def create_verified_backup(**kwargs):
        calls.append(kwargs)
        return result

    monkeypatch.setattr(
        backup_christiania,
        "evaluate_backup_due",
        lambda **kwargs: decision,
    )
    monkeypatch.setattr(
        backup_christiania,
        "create_verified_backup",
        create_verified_backup,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["backup_christiania.py", "--json"],
    )

    backup_christiania.main()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert len(calls) == 1
    assert calls[0]["db_path"] is None
    assert calls[0]["backup_dir"] is None
    assert calls[0]["retention"] is None
    assert callable(calls[0]["progress"])
    assert payload["state"] == "CREATED"
    assert payload["backup"]["backup_path"] == result.backup_path
    assert "compression" not in payload
    assert "Starting Christiania verified SQLite backup" in captured.err
    assert "Verified backup promoted" in captured.err
