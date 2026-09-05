from __future__ import annotations

import json

from src.operations.audit_export import build_audit_snapshot, export_audit_snapshot
from src.operations.sqlite_runtime import create_verified_backup


def test_audit_snapshot_never_exports_secret_values(db_path, tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    audit_dir = tmp_path / "audit"
    create_verified_backup(db_path=db_path, backup_dir=backup_dir, retention=3)

    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db_path))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("CHRISTIANIA_AUDIT_DIR", str(audit_dir))
    monkeypatch.setenv("MASSIVE_API_KEY", "MASSIVE_SUPER_SECRET")
    monkeypatch.setenv("THETADATA_API_KEY", "THETA_SUPER_SECRET")

    payload = build_audit_snapshot()
    encoded = json.dumps(payload)

    assert "MASSIVE_SUPER_SECRET" not in encoded
    assert "THETA_SUPER_SECRET" not in encoded
    assert payload["secret_presence"]["MASSIVE_API_KEY"] is True
    assert payload["secret_presence"]["THETADATA_API_KEY"] is True
    assert payload["disclaimer"].startswith("Operational/research audit only")


def test_audit_export_is_atomic_json_artifact(db_path, tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    audit_dir = tmp_path / "audit"
    create_verified_backup(db_path=db_path, backup_dir=backup_dir, retention=3)
    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db_path))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("CHRISTIANIA_AUDIT_DIR", str(audit_dir))

    path = export_audit_snapshot()
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["artifact"] == "CHRISTIANIA_V1_OPERATIONAL_AUDIT"
    assert not list(audit_dir.glob("*.tmp"))
