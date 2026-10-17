from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import backup_christiania


def _obj(**fields):
    return SimpleNamespace(**fields, as_dict=lambda: fields)


def test_service_pipeline_compresses_new_copy_immediately(monkeypatch, capsys):
    events = []
    due = _obj(due=True, reason="DUE")
    backup = _obj(backup_path="/scratch/new.db", source_path="/source.db",
                  schema_version=36, integrity_check=None, quick_check="ok",
                  verification_level="routine", foreign_key_violation_count=0,
                  pruned_count=0)
    archive = _obj(compressed_path="/scratch/new.db.gz", compressed_size_bytes=123)
    monkeypatch.setattr(backup_christiania, "compress_pending_routine_backup",
                        lambda path: events.append("pending") or None)
    monkeypatch.setattr(backup_christiania, "evaluate_backup_due",
                        lambda **kw: events.append("due") or due)
    monkeypatch.setattr(backup_christiania, "create_verified_backup",
                        lambda **kw: events.append("snapshot") or backup)
    monkeypatch.setattr(backup_christiania, "compress_verified_backup",
                        lambda path: events.append(("compress", path)) or archive)
    monkeypatch.setattr(sys, "argv", ["backup_christiania.py", "--json", "--compress-after"])
    backup_christiania.main()
    payload = json.loads(capsys.readouterr().out)
    assert events == ["pending", "due", "snapshot", ("compress", "/scratch/new.db")]
    assert payload["state"] == "CREATED_AND_COMPRESSED"
    assert payload["compression"]["compressed_path"] == "/scratch/new.db.gz"
    assert payload["backup"]["verification_level"] == "routine"


def test_skipped_copy_can_complete_pending_compression(monkeypatch, capsys):
    completed = _obj(compressed_path="/scratch/prior.db.gz")
    monkeypatch.setattr(backup_christiania, "compress_pending_routine_backup",
                        lambda path: completed)
    monkeypatch.setattr(backup_christiania, "evaluate_backup_due",
                        lambda **kw: _obj(due=False, reason="NO_NEW_RESEARCH"))
    monkeypatch.setattr(backup_christiania, "create_verified_backup",
                        lambda **kw: pytest.fail("No new 30 GiB copy allowed"))
    monkeypatch.setattr(sys, "argv", ["backup_christiania.py", "--json", "--compress-after"])
    backup_christiania.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "SKIPPED"
    assert payload["compression"]["compressed_path"] == completed.compressed_path


def test_failed_pending_compression_aborts_before_new_copy(monkeypatch):
    def fail(_):
        raise RuntimeError("LOW_HEADROOM")
    monkeypatch.setattr(backup_christiania, "compress_pending_routine_backup", fail)
    monkeypatch.setattr(backup_christiania, "evaluate_backup_due",
                        lambda **kw: pytest.fail("No policy decision after failed recovery"))
    monkeypatch.setattr(backup_christiania, "create_verified_backup",
                        lambda **kw: pytest.fail("No new copy after failed recovery"))
    monkeypatch.setattr(sys, "argv", ["backup_christiania.py", "--compress-after"])
    with pytest.raises(RuntimeError, match="LOW_HEADROOM"):
        backup_christiania.main()


def test_pending_picker_ignores_legacy_unmanifested_and_prefers_newest(tmp_path, monkeypatch):
    backups = tmp_path / "backups"
    backups.mkdir()
    legacy = backups / "christiania_backup_20261001T000000Z.db"
    older = backups / "christiania_backup_20261002T000000Z.db"
    newest = backups / "christiania_backup_20261003T000000Z.db"
    for p in (legacy, older, newest):
        p.write_bytes(b"sample")
    for p in (older, newest):
        (backups / (p.name + ".manifest.json")).write_text("{}")
    monkeypatch.setattr(backup_christiania, "resolve_backup_dir", lambda x: backups)
    called = []
    monkeypatch.setattr(backup_christiania, "compress_verified_backup",
                        lambda p: called.append(p) or _obj(compressed_path=str(p)+".gz"))
    result = backup_christiania.compress_pending_routine_backup(None)
    assert called == [newest]
    assert result.compressed_path == str(newest) + ".gz"


def test_systemd_backup_service_compresses_in_same_bounded_unit():
    unit = (Path(__file__).resolve().parents[1] /
            "deploy/systemd/christiania-backup.service").read_text()
    assert "TimeoutStartSec=5400" in unit
    assert "backup_christiania.py --compress-after" in unit
    assert "ExecStopPost=" in unit
