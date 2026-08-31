import sqlite3
from pathlib import Path

import pytest

from src.database.repository import get_connection

BASE = Path(__file__).resolve().parents[1]
SCHEMA = BASE / "trade_log_schema.sql"
M007 = BASE / "migrations" / "007_selection_universe_integrity.sql"
M008 = BASE / "migrations" / "008_shadow_persistence.sql"
M009 = BASE / "migrations" / "009_hostile_review_hardening.sql"


def build_v9(path):
    conn = get_connection(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(M007.read_text(encoding="utf-8"))
    conn.executescript(M008.read_text(encoding="utf-8"))
    conn.executescript(M009.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def create_candidate(conn):
    conn.execute(
        """
        INSERT INTO research_runs (
            cohort_id, started_at, code_git_sha,
            preregistration_hash, us_session_date,
            us_session_state, status
        )
        VALUES (
            'V9_TEST', '2026-08-31T18:00:00Z', 'abc',
            'hash', '2026-08-31', 'INTRADAY', 'STARTED'
        );
        """
    )
    run_id = conn.execute(
        "SELECT id FROM research_runs ORDER BY id DESC LIMIT 1;"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO listing_reference_contracts (
            research_run_id, provider, underlying,
            provider_contract_id, expiration, strike, right,
            observed_at, ingested_at
        )
        VALUES (?, 'MASSIVE', 'AAPL', 'O:TEST',
                '2026-09-14', 245, 'C',
                '2026-08-31T18:00:00Z',
                '2026-08-31T18:00:00Z');
        """,
        (run_id,),
    )
    ref_id = conn.execute(
        "SELECT id FROM listing_reference_contracts ORDER BY id DESC LIMIT 1;"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO shadow_candidates (
            research_run_id, reference_contract_id, underlying,
            scanner_family_id, scanner_version, scanner_rule_version,
            surfaced_at, universe_status,
            structure_id, structure_version,
            hypothesis_family, hypothesis_version,
            sizing_policy_version, max_theoretical_loss_minor,
            admission_label
        )
        VALUES (?, ?, 'AAPL', 'S', 'v1', 'r1',
                '2026-08-31T18:01:00Z', 'CONSISTENT',
                'LONG_CALL', 'v1', 'H', 'v1',
                'SIZING_POLICY_V1', 10000,
                'CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING');
        """,
        (run_id, ref_id),
    )
    candidate_id = conn.execute(
        "SELECT id FROM shadow_candidates ORDER BY id DESC LIMIT 1;"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO shadow_state_events (
            candidate_id, from_state, to_state, occurred_at, actor
        )
        VALUES (?, NULL, 'SURFACED',
                '2026-08-31T18:01:00Z', 'SYSTEM');
        """,
        (candidate_id,),
    )
    return candidate_id


def test_null_from_state_cannot_bypass_lifecycle(tmp_path):
    conn = build_v9(tmp_path / "v9.db")
    try:
        candidate_id = create_candidate(conn)
        with pytest.raises(
            sqlite3.IntegrityError,
            match="from_state does not match current state",
        ):
            conn.execute(
                """
                INSERT INTO shadow_state_events (
                    candidate_id, from_state, to_state, occurred_at, actor
                )
                VALUES (?, NULL, 'SHADOW_TRACKED',
                        '2026-08-31T18:02:00Z', 'ATTACK');
                """,
                (candidate_id,),
            )

        conn.execute(
            """
            INSERT INTO shadow_state_events (
                candidate_id, from_state, to_state, occurred_at, actor
            )
            VALUES (?, 'SURFACED', 'INVESTIGATED',
                    '2026-08-31T18:02:00Z', 'USER');
            """,
            (candidate_id,),
        )
    finally:
        conn.close()


def test_first_pin_event_must_be_pin_and_view_is_underlying_scoped(tmp_path):
    conn = build_v9(tmp_path / "pin.db")
    try:
        candidate_id = create_candidate(conn)
        with pytest.raises(
            sqlite3.IntegrityError,
            match="First underlying pin event must be PIN",
        ):
            conn.execute(
                """
                INSERT INTO underlying_pin_events (
                    underlying, candidate_id, action, occurred_at, reason
                )
                VALUES ('AAPL', ?, 'UNPIN',
                        '2026-08-31T18:03:00Z', 'bad first event');
                """,
                (candidate_id,),
            )

        conn.execute(
            """
            INSERT INTO underlying_pin_events (
                underlying, candidate_id, action, occurred_at, reason
            )
            VALUES ('AAPL', ?, 'PIN',
                    '2026-08-31T18:03:00Z', 'active');
            """,
            (candidate_id,),
        )

        rows = conn.execute(
            "SELECT underlying FROM v_active_underlying_pins;"
        ).fetchall()
        assert [row["underlying"] for row in rows] == ["AAPL"]
    finally:
        conn.close()


def test_native_schema_does_not_delete_version_history():
    assert "DELETE FROM schema_version" not in SCHEMA.read_text(encoding="utf-8")
