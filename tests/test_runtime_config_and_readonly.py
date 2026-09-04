import sqlite3

import pytest

from src import config
from src.database.repository import (
    resolve_db_path,
)
from src.operations.sqlite_runtime import (
    open_readonly_connection,
)


def test_runtime_setting_process_environment_wins(
    monkeypatch,
    tmp_path,
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHRISTIANIA_DB_PATH=from-file.db\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        config,
        "ENV_FILE",
        env_file,
    )
    monkeypatch.setenv(
        "CHRISTIANIA_DB_PATH",
        "from-process.db",
    )

    assert (
        config.get_runtime_setting(
            "CHRISTIANIA_DB_PATH"
        )
        == "from-process.db"
    )


def test_runtime_setting_falls_back_to_local_env(
    monkeypatch,
    tmp_path,
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHRISTIANIA_BACKUP_RETENTION=9\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        config,
        "ENV_FILE",
        env_file,
    )
    monkeypatch.delenv(
        "CHRISTIANIA_BACKUP_RETENTION",
        raising=False,
    )

    assert (
        config.get_runtime_setting(
            "CHRISTIANIA_BACKUP_RETENTION"
        )
        == "9"
    )


def test_resolve_db_path_explicit_argument_wins(
    monkeypatch,
    tmp_path,
):
    configured = tmp_path / "configured.db"
    explicit = tmp_path / "explicit.db"

    monkeypatch.setenv(
        "CHRISTIANIA_DB_PATH",
        str(configured),
    )

    assert (
        resolve_db_path(explicit)
        == explicit
    )


def test_resolve_db_path_uses_runtime_environment(
    monkeypatch,
    tmp_path,
):
    configured = tmp_path / "configured.db"

    monkeypatch.setenv(
        "CHRISTIANIA_DB_PATH",
        str(configured),
    )

    assert (
        resolve_db_path()
        == configured
    )


def test_readonly_connection_refuses_write(
    db_path,
):
    conn = open_readonly_connection(
        db_path
    )

    try:
        assert (
            conn.execute(
                "PRAGMA query_only;"
            ).fetchone()[0]
            == 1
        )

        with pytest.raises(
            sqlite3.OperationalError
        ):
            conn.execute(
                '''
                CREATE TABLE should_not_exist(
                    id INTEGER
                );
                '''
            )

    finally:
        conn.close()

def test_health_cli_returns_nonzero_for_missing_database(
    tmp_path,
):
    import sys

    import christiania_health

    missing = tmp_path / "missing.db"

    old_argv = sys.argv
    sys.argv = [
        "christiania_health.py",
        "--db",
        str(missing),
    ]

    try:
        assert christiania_health.main() == 2
    finally:
        sys.argv = old_argv


def test_health_cli_strict_daemon_returns_three_without_lease(
    db_path,
):
    import sys

    import christiania_health

    old = sys.argv
    sys.argv = [
        "christiania_health.py",
        "--db",
        str(db_path),
        "--strict-daemon",
    ]

    try:
        assert christiania_health.main() == 3
    finally:
        sys.argv = old
