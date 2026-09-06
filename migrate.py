import sqlite3
from pathlib import Path

from src.database.migration_runner import apply_pending_migrations, get_schema_version


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "trade_log.db"
MIGRATIONS_DIR = BASE_DIR / "migrations"


def get_current_version(connection: sqlite3.Connection) -> int:
    return get_schema_version(connection)


def main():
    connection = sqlite3.connect(DB_PATH)
    try:
        before = get_current_version(connection)
        print(f"Current schema version: {before}")
        after = apply_pending_migrations(connection, MIGRATIONS_DIR)
        print(f"Schema is now version {after}")
        print("Migration complete.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
