from __future__ import annotations

from pathlib import Path

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations import release_manifest as rm


def test_release_manifest_fingerprints_schema_migrations_and_quant_registry(db_path, monkeypatch, tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001.sql").write_text("SELECT 1;", encoding="utf-8")
    (migrations / "002.sql").write_text("SELECT 2;", encoding="utf-8")
    monkeypatch.setattr(rm, "MIGRATIONS", migrations)

    result = rm.build_release_manifest(db_path)

    assert result.version == "1.0.0-rc1"
    assert result.release_channel == "release-candidate"
    assert result.schema_version == EXPECTED_SCHEMA_VERSION
    assert result.expected_schema_version == EXPECTED_SCHEMA_VERSION
    assert len(result.migration_chain_sha256) == 64
    assert len(result.quant_registry_sha256) == 64
    assert result.dependencies["numpy"]
    assert result.dependencies["scipy"]


def test_release_manifest_hash_changes_when_migration_bytes_change(db_path, monkeypatch, tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    path = migrations / "001.sql"
    path.write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(rm, "MIGRATIONS", migrations)
    first = rm.build_release_manifest(db_path).migration_chain_sha256
    path.write_text("SELECT 9;", encoding="utf-8")
    second = rm.build_release_manifest(db_path).migration_chain_sha256
    assert first != second


def test_interactive_release_manifest_never_performs_integrity_scan(
    db_path, monkeypatch,
):
    """The metadata view must not trigger table-wide PRAGMA scans."""
    actual = rm.inspect_database
    called = []

    def spy(path=None, *, deep_integrity=True):
        called.append(deep_integrity)
        if deep_integrity:
            raise AssertionError("Release UI triggered a full database scan")
        return actual(path, deep_integrity=False)

    monkeypatch.setattr(rm, "inspect_database", spy)
    manifest = rm.build_release_manifest(db_path, deep_integrity=False)
    assert manifest.schema_version == EXPECTED_SCHEMA_VERSION
    assert called == [False]


def test_release_manifest_retains_strict_default(db_path, monkeypatch):
    actual = rm.inspect_database
    called = []

    def spy(path=None, *, deep_integrity=True):
        called.append(deep_integrity)
        return actual(path, deep_integrity=deep_integrity)

    monkeypatch.setattr(rm, "inspect_database", spy)
    rm.build_release_manifest(db_path)
    assert called == [True]
