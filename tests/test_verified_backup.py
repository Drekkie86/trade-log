import sqlite3
import time

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.sqlite_runtime import (
    backup_logical_source_bytes,
    create_verified_backup,
    plan_backup_capacity,
)


def _seed_source(path):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "PRAGMA journal_mode=WAL;"
        )
        conn.execute(
            '''
            CREATE TABLE schema_version(
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            '''
        )
        conn.execute(
            '''
            INSERT INTO schema_version(
                version,
                applied_at
            )
            VALUES(?, '2026-09-05T00:00:00Z');
            ''',
            (EXPECTED_SCHEMA_VERSION,),
        )
        conn.execute(
            '''
            CREATE TABLE evidence(
                id INTEGER PRIMARY KEY,
                value TEXT NOT NULL
            );
            '''
        )
        conn.execute(
            '''
            INSERT INTO evidence(value)
            VALUES('committed-wal-row');
            '''
        )
        conn.commit()
    finally:
        conn.close()


def test_verified_backup_preserves_committed_wal_data(
    tmp_path,
):
    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    _seed_source(source)

    result = create_verified_backup(
        db_path=source,
        backup_dir=backup_dir,
        retention=3,
    )

    assert result.schema_version == EXPECTED_SCHEMA_VERSION
    assert result.integrity_check == "ok"
    assert (
        result.foreign_key_violation_count
        == 0
    )

    backup = sqlite3.connect(
        result.backup_path
    )

    try:
        value = backup.execute(
            '''
            SELECT value
            FROM evidence;
            '''
        ).fetchone()[0]

        assert value == "committed-wal-row"

    finally:
        backup.close()


def test_backup_retention_prunes_oldest(
    tmp_path,
):
    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    _seed_source(source)
    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    for index in range(3):
        stale = (
            backup_dir
            / f"christiania_backup_2026010{index + 1}T000000Z.db"
        )
        stale.write_bytes(
            b"stale"
        )
        old = 1_700_000_000 + index
        import os
        os.utime(stale, (old, old))

    result = create_verified_backup(
        db_path=source,
        backup_dir=backup_dir,
        retention=2,
    )

    backups = list(
        backup_dir.glob(
            "christiania_backup_*.db"
        )
    )

    assert len(backups) == 2
    assert result.pruned_count == 2


def test_verified_backup_rejects_stale_schema(
    tmp_path,
):
    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"

    conn = sqlite3.connect(source)

    try:
        conn.execute(
            """
            CREATE TABLE schema_version(
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO schema_version(
                version,
                applied_at
            )
            VALUES(26, '2026-09-04T00:00:00Z');
            """
        )
        conn.commit()

    finally:
        conn.close()

    import pytest

    with pytest.raises(
        RuntimeError,
        match="does not match expected",
    ):
        create_verified_backup(
            db_path=source,
            backup_dir=backup_dir,
            retention=3,
        )

    assert not list(
        backup_dir.glob(
            "christiania_backup_*.db"
        )
    )


def test_backup_capacity_preflight_refuses_before_file_creation(
    tmp_path,
    monkeypatch,
):
    import shutil

    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    _seed_source(source)
    backup_dir.mkdir(parents=True, exist_ok=True)

    source_size = source.stat().st_size

    class Usage:
        total = 100 * 1024**3
        used = 90 * 1024**3
        free = 10 * 1024**3

    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda path: Usage(),
    )

    import pytest

    with pytest.raises(
        RuntimeError,
        match="Insufficient backup filesystem headroom",
    ):
        create_verified_backup(
            db_path=source,
            backup_dir=backup_dir,
            retention=3,
        )

    assert source_size > 0
    assert not list(
        backup_dir.glob(
            "christiania_backup_*.db"
        )
    )
    assert not list(
        backup_dir.glob(
            ".christiania_backup_*.tmp.db"
        )
    )


def test_backup_temp_is_removed_on_baseexception(
    tmp_path,
    monkeypatch,
):
    import pytest
    import src.operations.sqlite_runtime as sqlite_runtime

    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    _seed_source(source)

    def interrupted_verify(path, *, progress=None):
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        sqlite_runtime,
        "_verify_backup",
        interrupted_verify,
    )

    with pytest.raises(KeyboardInterrupt):
        create_verified_backup(
            db_path=source,
            backup_dir=backup_dir,
            retention=3,
        )

    assert not list(
        backup_dir.glob(
            ".christiania_backup_*.tmp.db"
        )
    )


def test_backup_capacity_counts_committed_wal_growth(
    tmp_path,
):
    source = tmp_path / "source.db"

    conn = sqlite3.connect(source)
    try:
        conn.execute(
            "PRAGMA journal_mode=WAL;"
        )
        conn.execute(
            "PRAGMA wal_autocheckpoint=0;"
        )
        conn.execute(
            """
            CREATE TABLE schema_version(
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO schema_version(
                version,
                applied_at
            )
            VALUES(?, '2026-09-24T00:00:00Z');
            """,
            (EXPECTED_SCHEMA_VERSION,),
        )
        conn.execute(
            """
            CREATE TABLE evidence(
                id INTEGER PRIMARY KEY,
                payload BLOB NOT NULL
            );
            """
        )
        conn.commit()

        main_before = source.stat().st_size

        conn.executemany(
            "INSERT INTO evidence(payload) VALUES(?)",
            [
                (b"x" * 4096,)
                for _ in range(2048)
            ],
        )
        conn.commit()

        main_after = source.stat().st_size
        logical = backup_logical_source_bytes(
            source
        )

        assert main_after == main_before
        assert logical > main_after
    finally:
        conn.close()

def test_backup_preprunes_before_capacity_check(
    tmp_path,
    monkeypatch,
):
    import os
    import shutil
    import src.operations.sqlite_runtime as sqlite_runtime

    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    _seed_source(source)
    backup_dir.mkdir(parents=True, exist_ok=True)

    for index in range(3):
        path = (
            backup_dir
            / f"christiania_backup_2026010{index + 1}T000000Z.db"
        )
        path.write_bytes(b"historical")
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))

    observed_counts = []

    class Usage:
        total = 100 * 1024**3
        used = 50 * 1024**3
        free = 50 * 1024**3

    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda path: Usage(),
    )

    original_assert = sqlite_runtime.assert_backup_capacity

    def assert_after_preprune(*, source, target_dir):
        observed_counts.append(
            len(
                sqlite_runtime.backup_data_files(
                    target_dir
                )
            )
        )
        return original_assert(
            source=source,
            target_dir=target_dir,
        )

    monkeypatch.setattr(
        sqlite_runtime,
        "assert_backup_capacity",
        assert_after_preprune,
    )

    result = create_verified_backup(
        db_path=source,
        backup_dir=backup_dir,
        retention=3,
    )

    assert observed_counts == [2]
    assert result.pruned_count == 1
    assert len(
        sqlite_runtime.backup_data_files(
            backup_dir
        )
    ) == 3


def test_backup_retention_one_preserves_last_good_before_new_copy(
    tmp_path,
    monkeypatch,
):
    import shutil

    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    _seed_source(source)
    backup_dir.mkdir(parents=True, exist_ok=True)

    previous = (
        backup_dir
        / "christiania_backup_20260101T000000Z.db"
    )
    previous.write_bytes(b"known-good")

    class Usage:
        total = 100 * 1024**3
        used = 95 * 1024**3
        free = 5 * 1024**3

    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda path: Usage(),
    )

    import pytest

    with pytest.raises(
        RuntimeError,
        match="Insufficient backup filesystem headroom",
    ):
        create_verified_backup(
            db_path=source,
            backup_dir=backup_dir,
            retention=1,
        )

    assert previous.read_bytes() == b"known-good"

def test_backup_capacity_plan_counts_only_policy_prunable_backups(
    tmp_path,
    monkeypatch,
):
    import os
    import shutil

    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    _seed_source(source)
    backup_dir.mkdir(parents=True)

    sizes = [
        100,
        200,
        300,
        400,
    ]
    for index, size in enumerate(
        sizes
    ):
        path = (
            backup_dir
            / f"christiania_backup_2026020{index + 1}T000000Z.db"
        )
        path.write_bytes(
            b"x" * size
        )
        os.utime(
            path,
            (
                1_700_000_000 + index,
                1_700_000_000 + index,
            ),
        )

    class Usage:
        total = 100 * 1024**3
        used = 60 * 1024**3
        free = 40 * 1024**3

    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda path: Usage(),
    )

    plan = plan_backup_capacity(
        source=source,
        target_dir=backup_dir,
        retention=3,
    )

    # Retention 3 makes one slot by preserving the two newest files.
    assert plan.preprune_keep == 2
    assert plan.current_backup_count == 4
    assert plan.reclaimable_bytes == 300
    assert (
        plan.projected_free_bytes
        == Usage.free + 300
    )
