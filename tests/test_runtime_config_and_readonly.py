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


def test_health_cli_strict_theta_returns_four(monkeypatch):
    import sys

    import christiania_health

    monkeypatch.setattr(
        christiania_health,
        "load_command_deck",
        lambda *args, **kwargs: {
            "ready": True,
            "theta_health": {"state": "UNREACHABLE"},
            "daemon_health": {"state": "HEALTHY"},
        },
    )

    old = sys.argv
    sys.argv = [
        "christiania_health.py",
        "--json",
        "--strict-theta",
    ]

    try:
        assert christiania_health.main() == 4
    finally:
        sys.argv = old


def test_health_cli_non_strict_does_not_fail_only_for_theta(monkeypatch):
    import sys

    import christiania_health

    monkeypatch.setattr(
        christiania_health,
        "load_command_deck",
        lambda *args, **kwargs: {
            "ready": True,
            "theta_health": {"state": "UNREACHABLE"},
            "daemon_health": {"state": "HEALTHY"},
        },
    )

    old = sys.argv
    sys.argv = [
        "christiania_health.py",
        "--json",
    ]

    try:
        assert christiania_health.main() == 0
    finally:
        sys.argv = old


def test_health_cli_strict_backup_returns_five(monkeypatch):
    import sys

    import christiania_health

    monkeypatch.setattr(
        christiania_health,
        "load_command_deck",
        lambda *args, **kwargs: {
            "ready": True,
            "theta_health": {"state": "READY"},
            "daemon_health": {"state": "HEALTHY"},
        },
    )
    monkeypatch.setattr(
        christiania_health,
        "inventory_backups",
        lambda: type(
            "Inventory",
            (),
            {
                "as_dict": lambda self: {
                    "valid_files": 0,
                    "latest_valid_age_hours": None,
                }
            },
        )(),
    )

    old = sys.argv
    sys.argv = [
        "christiania_health.py",
        "--json",
        "--strict-backup",
    ]

    try:
        assert christiania_health.main() == 5
    finally:
        sys.argv = old


def test_health_cli_strict_backup_accepts_fresh_verified_backup(monkeypatch):
    import sys

    import christiania_health

    monkeypatch.setattr(
        christiania_health,
        "load_command_deck",
        lambda *args, **kwargs: {
            "ready": True,
            "theta_health": {"state": "READY"},
            "daemon_health": {"state": "HEALTHY"},
        },
    )
    monkeypatch.setattr(
        christiania_health,
        "inventory_backups",
        lambda: type(
            "Inventory",
            (),
            {
                "as_dict": lambda self: {
                    "valid_files": 1,
                    "latest_valid_age_hours": 2.0,
                }
            },
        )(),
    )

    old = sys.argv
    sys.argv = [
        "christiania_health.py",
        "--json",
        "--strict-backup",
    ]

    try:
        assert christiania_health.main() == 0
    finally:
        sys.argv = old

def test_health_cli_non_strict_uses_metadata_only_backup_inventory(monkeypatch):
    import sys
    import christiania_health

    calls = {"fast": 0, "deep": 0}

    monkeypatch.setattr(
        christiania_health,
        "load_command_deck",
        lambda *args, **kwargs: {
            "ready": True,
            "database": {
                "path": "test.db",
                "schema_version": 27,
                "expected_schema_version": 27,
                "journal_mode": "wal",
                "quick_check": "ok",
                "foreign_key_violation_count": 0,
            },
            "market_clock": {"state": "CLOSED", "next_sample_at": None},
            "theta_health": {"state": "READY"},
            "daemon_health": {"state": "HEALTHY"},
            "latest_iteration": None,
            "prospective": {
                "independent_dates": 0,
                "recovered_samples": 0,
            },
        },
    )

    class Inventory:
        def __init__(self, payload):
            self.payload = payload

        def as_dict(self):
            return self.payload

    def fast_inventory():
        calls["fast"] += 1
        return Inventory(
            {
                "total_files": 2,
                "valid_files": 0,
                "latest_valid_age_hours": None,
            }
        )

    def deep_inventory():
        calls["deep"] += 1
        raise AssertionError("deep backup verification must not run")

    monkeypatch.setattr(christiania_health, "inventory_backups_fast", fast_inventory)
    monkeypatch.setattr(christiania_health, "inventory_backups", deep_inventory)

    old = sys.argv
    sys.argv = ["christiania_health.py", "--json"]
    try:
        assert christiania_health.main() == 0
    finally:
        sys.argv = old

    assert calls == {"fast": 1, "deep": 0}


def test_health_cli_strict_backup_uses_deep_backup_inventory(monkeypatch):
    import sys
    import christiania_health

    calls = {"fast": 0, "deep": 0}

    monkeypatch.setattr(
        christiania_health,
        "load_command_deck",
        lambda *args, **kwargs: {
            "ready": True,
            "theta_health": {"state": "READY"},
            "daemon_health": {"state": "HEALTHY"},
        },
    )

    class Inventory:
        def as_dict(self):
            return {
                "total_files": 1,
                "valid_files": 1,
                "latest_valid_age_hours": 1.0,
            }

    def fast_inventory():
        calls["fast"] += 1
        raise AssertionError("fast inventory must not replace strict verification")

    def deep_inventory():
        calls["deep"] += 1
        return Inventory()

    monkeypatch.setattr(christiania_health, "inventory_backups_fast", fast_inventory)
    monkeypatch.setattr(christiania_health, "inventory_backups", deep_inventory)

    old = sys.argv
    sys.argv = ["christiania_health.py", "--json", "--strict-backup"]
    try:
        assert christiania_health.main() == 0
    finally:
        sys.argv = old

    assert calls == {"fast": 0, "deep": 1}

