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


def test_backup_entrypoint_skips_when_policy_says_nothing_new(
    monkeypatch,
    capsys,
):
    decision = SimpleNamespace(
        due=False,
        reason="NO_NEW_COMPLETED_RESEARCH",
        latest_backup_path="/tmp/existing.db",
        latest_completed_research_at="2026-09-18T19:00:00Z",
        as_dict=lambda: {
            "due": False,
            "reason": "NO_NEW_COMPLETED_RESEARCH",
        },
    )

    monkeypatch.setattr(
        backup_christiania,
        "evaluate_backup_due",
        lambda **kwargs: decision,
    )

    def forbidden_backup(**kwargs):
        raise AssertionError(
            "Redundant full backup must not start."
        )

    monkeypatch.setattr(
        backup_christiania,
        "create_verified_backup",
        forbidden_backup,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["backup_christiania.py", "--json"],
    )

    backup_christiania.main()

    payload = json.loads(
        capsys.readouterr().out
    )

    assert payload["state"] == "SKIPPED"
    assert (
        payload["decision"]["reason"]
        == "NO_NEW_COMPLETED_RESEARCH"
    )


def test_backup_service_runs_bounded_temp_cleanup_after_exit():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    unit = (
        root
        / "deploy/systemd/christiania-backup.service"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "ExecStopPost=/opt/christiania/.venv/bin/python "
        "/opt/christiania/backup_christiania.py "
        "--cleanup-stale-temp"
    ) in unit


def test_cleanup_mode_removes_only_incomplete_backup_temp_files(
    tmp_path,
    monkeypatch,
    capsys,
):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    stale = [
        backup_dir / ".christiania_backup_20260922T233158Z.tmp.db",
        backup_dir / ".christiania_backup_20260922T233158Z.tmp.db-journal",
        backup_dir / ".christiania_backup_20260922T233158Z.tmp.db-wal",
        backup_dir / ".christiania_backup_20260922T233158Z.tmp.db-shm",
    ]
    for path in stale:
        path.write_bytes(b"x")

    valid = (
        backup_dir
        / "christiania_backup_20260921T190133Z.db"
    )
    valid.write_bytes(b"keep")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backup_christiania.py",
            "--backup-dir",
            str(backup_dir),
            "--cleanup-stale-temp",
            "--json",
        ],
    )

    backup_christiania.main()

    payload = json.loads(
        capsys.readouterr().out
    )

    assert payload["state"] == "CLEANED"
    assert payload["removed_count"] == 4
    assert valid.is_file()
    assert not any(
        path.exists()
        for path in stale
    )


def test_backup_cli_loads_runtime_env_before_policy(
    tmp_path,
    monkeypatch,
):
    env_file = tmp_path / "christiania.env"
    env_file.write_text(
        "CHRISTIANIA_DB_PATH=/tmp/runtime-db.db\n",
        encoding="utf-8",
    )

    events = []

    monkeypatch.setattr(
        backup_christiania,
        "DEFAULT_RUNTIME_ENV_FILE",
        env_file,
    )

    def fake_load(path, *, overwrite=False):
        events.append(
            (
                "load",
                str(path),
                overwrite,
            )
        )
        return {
            "CHRISTIANIA_DB_PATH":
                "/tmp/runtime-db.db"
        }

    decision = SimpleNamespace(
        due=False,
        reason="NO_NEW_COMPLETED_RESEARCH",
        latest_backup_path="/tmp/existing.db",
        latest_completed_research_at=None,
        as_dict=lambda: {
            "due": False,
            "reason": "NO_NEW_COMPLETED_RESEARCH",
        },
    )

    def fake_decision(**kwargs):
        events.append(
            ("decision",)
        )
        return decision

    monkeypatch.setattr(
        backup_christiania,
        "load_runtime_env_file",
        fake_load,
    )
    monkeypatch.setattr(
        backup_christiania,
        "evaluate_backup_due",
        fake_decision,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["backup_christiania.py", "--json"],
    )

    backup_christiania.main()

    assert events[0][0] == "load"
    assert events[0][2] is False
    assert events[1] == ("decision",)
