import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "trade_log.db"
MIGRATIONS_DIR = BASE_DIR / "migrations"


def get_current_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        """
        SELECT MAX(version)
        FROM schema_version;
        """
    ).fetchone()

    if row is None or row[0] is None:
        raise RuntimeError(
            "Database does not contain a schema version."
        )

    return int(row[0])


def main():
    connection = sqlite3.connect(DB_PATH)

    try:
        connection.execute("PRAGMA foreign_keys = ON;")

        current_version = get_current_version(connection)

        print(f"Current schema version: {current_version}")

        migration_files = sorted(
            MIGRATIONS_DIR.glob("*.sql")
        )

        for migration_path in migration_files:
            migration_version = int(
                migration_path.name.split("_", 1)[0]
            )

            if migration_version <= current_version:
                continue

            print(
                f"Applying migration "
                f"{migration_path.name}..."
            )

            sql = migration_path.read_text(
                encoding="utf-8"
            )

            connection.executescript(sql)

            current_version = get_current_version(
                connection
            )

            print(
                f"Schema is now version "
                f"{current_version}"
            )

        print("Migration complete.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()