import sqlite3
from pathlib import Path

import pytest

from src.database.repository import get_connection


BASE_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BASE_DIR / "trade_log_schema.sql"
MIGRATION_007 = BASE_DIR / "migrations" / "007_selection_universe_integrity.sql"
MIGRATION_008 = BASE_DIR / "migrations" / "008_shadow_persistence.sql"


def build_v8(path: Path) -> sqlite3.Connection:
    conn = get_connection(path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.executescript(MIGRATION_007.read_text(encoding="utf-8"))
    conn.executescript(MIGRATION_008.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def test_migration_008_creates_shadow_objects(tmp_path):
    conn = build_v8(tmp_path / "v8.db")
    try:
        version = conn.execute(
            "SELECT MAX(version) FROM schema_version;"
        ).fetchone()[0]
        assert version == 8

        objects = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master;"
            )
        }

        for required in {
            "listing_reference_contracts",
            "provider_observation_availability",
            "shadow_candidates",
            "shadow_state_events",
            "shadow_outcome_observations",
            "underlying_pin_events",
            "v_reference_snapshot_reconciliation",
            "v_shadow_current_state",
            "v_underlying_pin_state",
        }:
            assert required in objects
    finally:
        conn.close()


def test_reference_and_observation_evidence_are_immutable(tmp_path):
    conn = build_v8(tmp_path / "immutable.db")
    try:
        conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id,
                started_at,
                code_git_sha,
                preregistration_hash,
                us_session_date,
                us_session_state,
                status
            )
            VALUES (
                'TEST',
                '2026-08-31T12:00:00Z',
                'abc',
                'hash',
                '2026-08-31',
                'INTRADAY',
                'STARTED'
            );
            """
        )
        run_id = conn.execute(
            "SELECT id FROM research_runs;"
        ).fetchone()[0]

        conn.execute(
            """
            INSERT INTO listing_reference_contracts (
                research_run_id,
                provider,
                underlying,
                provider_contract_id,
                expiration,
                strike,
                right,
                observed_at,
                ingested_at
            )
            VALUES (?, 'MASSIVE', 'AAPL', 'O:TEST',
                    '2026-09-14', 250, 'C',
                    '2026-08-31T12:00:00Z',
                    '2026-08-31T12:00:00Z');
            """,
            (run_id,),
        )
        ref_id = conn.execute(
            "SELECT id FROM listing_reference_contracts;"
        ).fetchone()[0]

        conn.execute(
            """
            INSERT INTO provider_observation_availability (
                reference_contract_id,
                provider,
                evidence_family,
                state,
                observed_at,
                ingested_at
            )
            VALUES (?, 'MASSIVE', 'MASSIVE_SNAPSHOT',
                    'ABSENT',
                    '2026-08-31T12:00:01Z',
                    '2026-08-31T12:00:01Z');
            """,
            (ref_id,),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                UPDATE listing_reference_contracts
                SET strike = 999
                WHERE id = ?;
                """,
                (ref_id,),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                DELETE FROM provider_observation_availability
                WHERE reference_contract_id = ?;
                """,
                (ref_id,),
            )
    finally:
        conn.close()


def test_reference_snapshot_reconciliation_requires_explicit_state(tmp_path):
    conn = build_v8(tmp_path / "reconcile.db")
    try:
        conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id,
                started_at,
                code_git_sha,
                preregistration_hash,
                us_session_date,
                us_session_state,
                status
            )
            VALUES (
                'TEST',
                '2026-08-31T12:00:00Z',
                'abc',
                'hash',
                '2026-08-31',
                'INTRADAY',
                'STARTED'
            );
            """
        )
        run_id = conn.execute(
            "SELECT id FROM research_runs;"
        ).fetchone()[0]

        for symbol, strike in [('O:A', 250), ('O:B', 255)]:
            conn.execute(
                """
                INSERT INTO listing_reference_contracts (
                    research_run_id,
                    provider,
                    underlying,
                    provider_contract_id,
                    expiration,
                    strike,
                    right,
                    observed_at,
                    ingested_at
                )
                VALUES (?, 'MASSIVE', 'AAPL', ?,
                        '2026-09-14', ?, 'C',
                        '2026-08-31T12:00:00Z',
                        '2026-08-31T12:00:00Z');
                """,
                (run_id, symbol, strike),
            )

        refs = conn.execute(
            "SELECT id FROM listing_reference_contracts ORDER BY id;"
        ).fetchall()

        conn.execute(
            """
            INSERT INTO provider_observation_availability (
                reference_contract_id,
                provider,
                evidence_family,
                state,
                observed_at,
                ingested_at
            )
            VALUES (?, 'MASSIVE', 'MASSIVE_SNAPSHOT',
                    'PRESENT',
                    '2026-08-31T12:00:01Z',
                    '2026-08-31T12:00:01Z');
            """,
            (refs[0][0],),
        )

        row = conn.execute(
            "SELECT * FROM v_reference_snapshot_reconciliation;"
        ).fetchone()
        assert row["reference_listed_count"] == 2
        assert row["snapshot_present_count"] == 1
        assert row["snapshot_absent_count"] == 0
        assert row["reference_snapshot_reconciles"] == 0

        conn.execute(
            """
            INSERT INTO provider_observation_availability (
                reference_contract_id,
                provider,
                evidence_family,
                state,
                observed_at,
                ingested_at
            )
            VALUES (?, 'MASSIVE', 'MASSIVE_SNAPSHOT',
                    'ABSENT',
                    '2026-08-31T12:00:01Z',
                    '2026-08-31T12:00:01Z');
            """,
            (refs[1][0],),
        )

        row = conn.execute(
            "SELECT * FROM v_reference_snapshot_reconciliation;"
        ).fetchone()
        assert row["snapshot_present_count"] == 1
        assert row["snapshot_absent_count"] == 1
        assert row["reference_snapshot_reconciles"] == 1
    finally:
        conn.close()
