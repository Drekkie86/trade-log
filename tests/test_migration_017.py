import sqlite3
from pathlib import Path


MIGRATION = Path(
    "migrations"
    "/017_shadow_mark_measurement_role.sql"
)


def test_migration_017_labels_existing_marks_and_version(
    tmp_path,
):
    db = tmp_path / "migration_017.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

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
                16,
                '2026-09-03T00:00:00Z'
            );

            CREATE TABLE shadow_mark_observations (
                id INTEGER PRIMARY KEY,
                candidate_id INTEGER NOT NULL,
                research_run_id INTEGER NOT NULL,
                observed_at TEXT NOT NULL,
                provider TEXT NOT NULL,
                structure_mark_usd_minor INTEGER,
                gross_pnl_usd_minor INTEGER,
                estimated_net_pnl_usd_minor INTEGER,
                gross_pnl_eur_minor INTEGER,
                estimated_net_pnl_eur_minor INTEGER,
                entry_fx_observation_id INTEGER,
                quality_state TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                UNIQUE(candidate_id, research_run_id)
            );

            INSERT INTO shadow_mark_observations (
                candidate_id,
                research_run_id,
                observed_at,
                provider,
                structure_mark_usd_minor,
                gross_pnl_usd_minor,
                quality_state,
                evidence_json
            )
            VALUES (
                1,
                39,
                '2026-09-03T18:31:48Z',
                'THETADATA',
                -43700,
                -55500,
                'COMPLETE_UNVERIFIED_FRESHNESS',
                '{}'
            );
            """
        )

        conn.executescript(
            MIGRATION.read_text(encoding="utf-8")
        )

        row = conn.execute(
            """
            SELECT
                measurement_role,
                outcome_eligible,
                gross_pnl_usd_minor
            FROM shadow_mark_observations
            WHERE id = 1;
            """
        ).fetchone()

        assert row["measurement_role"] == (
            "INDEPENDENT_LEG_LIQUIDATION_STRESS"
        )
        assert row["outcome_eligible"] == 0
        assert row["gross_pnl_usd_minor"] == -55500

        version = conn.execute(
            "SELECT MAX(version) FROM schema_version;"
        ).fetchone()[0]
        assert version == 17
    finally:
        conn.close()
