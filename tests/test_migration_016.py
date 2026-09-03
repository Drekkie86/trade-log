import sqlite3
from pathlib import Path


MIGRATION = Path(
    "migrations"
    "/016_structural_scanner_planner_indexes.sql"
)


def test_migration_016_indexes_stats_and_version(
    tmp_path,
):
    db = tmp_path / "migration_016.db"
    conn = sqlite3.connect(db)

    try:
        conn.executescript(
            """
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );

            INSERT INTO schema_version (
                version,
                applied_at
            )
            VALUES (
                15,
                '2026-09-03T00:00:00Z'
            );

            CREATE TABLE provider_model_observations (
                id INTEGER PRIMARY KEY,
                option_quote_id INTEGER NOT NULL,
                provider TEXT NOT NULL
            );

            CREATE TABLE market_snapshots (
                id INTEGER PRIMARY KEY,
                research_run_id INTEGER,
                provider TEXT
            );

            INSERT INTO provider_model_observations (
                option_quote_id,
                provider
            )
            VALUES
                (101, 'THETADATA'),
                (102, 'THETADATA'),
                (103, 'OTHER');

            INSERT INTO market_snapshots (
                research_run_id,
                provider
            )
            VALUES
                (26, 'THETADATA'),
                (26, 'THETADATA'),
                (25, 'OTHER');
            """
        )

        conn.executescript(
            MIGRATION.read_text(
                encoding="utf-8"
            )
        )

        indexes = {
            row[1]
            for table in (
                "provider_model_observations",
                "market_snapshots",
            )
            for row in conn.execute(
                f'PRAGMA index_list("{table}")'
            ).fetchall()
        }

        assert (
            "idx_provider_model_option_quote_provider"
            in indexes
        )
        assert (
            "idx_market_snapshots_run_provider"
            in indexes
        )

        version_row = conn.execute(
            """
            SELECT version, applied_at
            FROM schema_version
            WHERE version = 16;
            """
        ).fetchone()

        assert version_row is not None
        assert version_row[0] == 16
        assert version_row[1]

        stats = {
            row[0]
            for row in conn.execute(
                """
                SELECT idx
                FROM sqlite_stat1
                WHERE idx IS NOT NULL;
                """
            ).fetchall()
        }

        assert (
            "idx_provider_model_option_quote_provider"
            in stats
        )
        assert (
            "idx_market_snapshots_run_provider"
            in stats
        )
    finally:
        conn.close()
