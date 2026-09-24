from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import christiania_release_database as release_db
from christiania_release_database import (
    DEFAULT_RELEASE_ROLLBACK_RETENTION,
    _prune_release_rollback_backups,
)
from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.control_plane_status import (
    _deployment_supervisor_state,
)


ROOT = Path(__file__).resolve().parents[1]


def test_no_migration_fast_path_precedes_backup_and_deep_verification():
    source = (
        ROOT / "christiania_release_database.py"
    ).read_text(encoding="utf-8")

    fast_guard = source.index(
        "if schema_before == EXPECTED_SCHEMA_VERSION:"
    )
    fast_return = source.index(
        "return ReleaseDatabaseResult(",
        fast_guard,
    )
    backup_phase = source.index(
        '"Database preparation: creating and fully verifying rollback backup"',
        fast_return,
    )

    fast_path = source[fast_guard:backup_phase]
    assert fast_guard < fast_return < backup_phase
    assert 'backup_path=""' in fast_path
    assert "migrated=False" in fast_path
    assert "skipping rollback" in fast_path


def test_no_migration_fast_path_never_calls_backup_or_deep_verify(
    monkeypatch,
    tmp_path: Path,
):
    database = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    pointer = tmp_path / "rollback.txt"

    monkeypatch.setattr(release_db, "resolve_db_path", lambda: database)
    monkeypatch.setattr(release_db, "resolve_backup_dir", lambda: backup_dir)
    monkeypatch.setattr(
        release_db,
        "inspect_database",
        lambda *args, **kwargs: SimpleNamespace(
            exists=True,
            schema_version=EXPECTED_SCHEMA_VERSION,
            journal_mode="wal",
        ),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("heavy database path must not run without a migration")

    monkeypatch.setattr(release_db, "_create_rollback_backup", forbidden)
    monkeypatch.setattr(release_db, "_verify_database", forbidden)
    monkeypatch.setattr(release_db, "apply_pending_migrations", forbidden)

    result = release_db.prepare_release_database(
        migrations_dir=tmp_path,
        rollback_pointer=pointer,
    )

    assert result.schema_before == EXPECTED_SCHEMA_VERSION
    assert result.schema_after == EXPECTED_SCHEMA_VERSION
    assert result.migrated is False
    assert result.backup_path == ""
    assert not pointer.exists()
    assert not backup_dir.exists()


def test_release_rollback_retention_is_bounded_and_does_not_touch_daily_backups(
    tmp_path: Path,
):
    release_paths: list[Path] = []
    for index in range(5):
        path = tmp_path / f"christiania_release_rollback_{index}_v28.db"
        path.write_bytes(b"rollback")
        os.utime(path, (100 + index, 100 + index))
        release_paths.append(path)

    daily = tmp_path / "christiania_backup_20990101T000000Z.db"
    daily.write_bytes(b"daily")

    pruned = _prune_release_rollback_backups(
        tmp_path,
        keep=DEFAULT_RELEASE_ROLLBACK_RETENTION,
    )

    remaining = sorted(tmp_path.glob("christiania_release_rollback_*.db"))
    assert pruned == 2
    assert len(remaining) == DEFAULT_RELEASE_ROLLBACK_RETENTION
    assert set(remaining) == set(release_paths[-DEFAULT_RELEASE_ROLLBACK_RETENTION:])
    assert daily.is_file()


def test_deployment_supervisor_ignores_explicit_early_memory_warning_only():
    supervisor = {
        "checks": [
            {
                "name": "memory:christiania-daemon.service",
                "state": "FAIL",
                "blocking": True,
                "detail": "MemoryCurrent=793079808 reached warning=536870912.",
            }
        ]
    }

    assert _deployment_supervisor_state(supervisor) == "PASS"


def test_deployment_supervisor_keeps_hard_resource_failure_blocking():
    supervisor = {
        "checks": [
            {
                "name": "disk-headroom",
                "state": "FAIL",
                "blocking": True,
                "detail": "Free space is below the deployment safety minimum.",
            }
        ]
    }

    assert _deployment_supervisor_state(supervisor) == "FAIL"


def test_deployment_supervisor_keeps_nonwarning_memory_failure_blocking():
    supervisor = {
        "checks": [
            {
                "name": "memory:christiania-daemon.service",
                "state": "FAIL",
                "blocking": True,
                "detail": "MemoryMax does not match the resource policy.",
            }
        ]
    }

    assert _deployment_supervisor_state(supervisor) == "FAIL"


def test_receiver_uses_deployment_safety_and_requires_live_edge_before_success():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    current_gate = receiver.index(
        'phase_start "Validating current production deployment safety"'
    )
    current_status = receiver.index(
        '"${PREVIOUS_TARGET}/christiania_status.py"',
        current_gate,
    )
    deployment_safe = receiver.index(
        "--deployment-safe",
        current_status,
    )
    db_prepare = receiver.index(
        'phase_start "Preparing release database"',
        deployment_safe,
    )
    edge_phase = receiver.index(
        'phase_start "Verifying live application and secure edge"',
        db_prepare,
    )
    success = receiver.index(
        'echo "CHRISTIANIA RELEASE ACTIVATED"',
        edge_phase,
    )

    assert current_gate < current_status < deployment_safe < db_prepare < edge_phase < success
    assert "http://127.0.0.1:8501/_stcore/health" in receiver
    assert "http://127.0.0.1:4180/ping" in receiver
    assert "caddy validate --config /etc/caddy/Caddyfile" in receiver
    assert "systemctl restart caddy.service" not in receiver
    assert 'verify_public_edge "${PUBLIC_HOST}"' in receiver
    assert 'database_migrated=${DB_MIGRATED}' in receiver


def test_receiver_explicitly_handles_no_migration_database_fast_path():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    assert 'if [[ "${DB_MIGRATED}" -eq 1 ]]; then' in receiver
    assert (
        "No schema migration required; rollback DB snapshot and deep DB scans were skipped."
        in receiver
    )
    assert "DATABASE_PREPARED=0" in receiver
