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



def test_deployed_marker_reads_full_validated_sha_without_git(tmp_path, monkeypatch):
    marker = tmp_path / "DEPLOYED_COMMIT"
    sha = "376cba5ad8d30d2dbe9a8673a9bd3933644cf6af"
    marker.write_text(sha.upper() + "\n", encoding="utf-8")

    def unexpected_git(*_args):
        raise AssertionError("Release marker must not invoke Git")

    monkeypatch.setattr(rm, "_git", unexpected_git)
    assert rm.read_deployed_commit(marker) == sha


def test_missing_or_malformed_marker_fails_as_unknown(tmp_path):
    marker = tmp_path / "DEPLOYED_COMMIT"
    assert rm.read_deployed_commit(marker) is None
    for content in ("", "1.0.0-rc1", "a" * 39, "z" * 40):
        marker.write_text(content, encoding="utf-8")
        assert rm.read_deployed_commit(marker) is None


def test_ops_release_shows_deployed_revision_not_checkout_status():
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8"
    )
    ops = app.split('elif page == "Ops":', 1)[1]
    release = ops.split('elif ops_view == "Release":', 1)[1].split(
        '        else:\n            section_heading("System"', 1
    )[0]
    assert 'read_deployed_commit()' in release
    assert '"Deployed revision"' in release
    assert '"Historical unhealthy samples"' in release
    assert 'build_release_manifest(deep_integrity=False)' in release
    assert 'with st.expander("Technical release fingerprint")' in release
    assert 'f"Product version: {CHRISTIANIA_VERSION} "' in release
    assert '"Git state"' not in release
    assert 'c1.metric("Version"' not in release
    assert 'Dirty / unavailable' not in release
