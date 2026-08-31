import sqlite3

from src.database.repository import get_connection
from src.research.reference_persistence import (
    persist_massive_reference_and_snapshot,
)


def create_run(db_path):
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
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
                'REFERENCE_PERSISTENCE_TEST',
                '2026-08-31T18:00:00Z',
                'abc',
                'hash',
                '2026-08-31',
                'INTRADAY',
                'STARTED'
            );
            """
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def reference_rows():
    return [
        {
            "ticker": "O:AAPL260914C00245000",
            "expiration_date": "2026-09-14",
            "strike_price": 245.0,
            "contract_type": "call",
            "exercise_style": "american",
            "shares_per_contract": 100,
            "primary_exchange": "X",
        },
        {
            "ticker": "O:AAPL260914P00245000",
            "expiration_date": "2026-09-14",
            "strike_price": 245.0,
            "contract_type": "put",
            "exercise_style": "american",
            "shares_per_contract": 100,
            "primary_exchange": "X",
        },
    ]


def snapshot_rows():
    return [
        {
            "details": {
                "ticker": "O:AAPL260914C00245000"
            }
        }
    ]


def test_reference_and_snapshot_persist_and_reconcile(db_path):
    run_id = create_run(db_path)

    result = persist_massive_reference_and_snapshot(
        research_run_id=run_id,
        underlying="AAPL",
        reference_rows=reference_rows(),
        snapshot_rows=snapshot_rows(),
        observed_at="2026-08-31T18:01:00Z",
        db_path=db_path,
    )

    assert len(result["reference_ids"]) == 2
    assert result["reconciliation"]["reference_count"] == 2
    assert result["reconciliation"]["snapshot_present_count"] == 1
    assert result["reconciliation"]["snapshot_absent_count"] == 1

    conn = get_connection(db_path)
    try:
        listed = conn.execute(
            """
            SELECT COUNT(*)
            FROM listing_reference_contracts
            WHERE research_run_id = ?;
            """,
            (run_id,),
        ).fetchone()[0]
        assert listed == 2

        states = conn.execute(
            """
            SELECT state, reason_code
            FROM provider_observation_availability
            ORDER BY id;
            """
        ).fetchall()
        assert [row["state"] for row in states] == [
            "PRESENT",
            "ABSENT",
        ]
        assert states[1]["reason_code"] == "SNAPSHOT_ROW_ABSENT"

        view = conn.execute(
            """
            SELECT *
            FROM v_reference_snapshot_reconciliation
            WHERE research_run_id = ?
              AND provider = 'MASSIVE'
              AND underlying = 'AAPL';
            """,
            (run_id,),
        ).fetchone()

        assert view["reference_listed_count"] == 2
        assert view["snapshot_present_count"] == 1
        assert view["snapshot_absent_count"] == 1
        assert view["reference_snapshot_reconciles"] == 1
    finally:
        conn.close()


def test_duplicate_reference_frame_fails_closed(db_path):
    run_id = create_run(db_path)

    rows = reference_rows()
    rows.append(dict(rows[0]))

    try:
        persist_massive_reference_and_snapshot(
            research_run_id=run_id,
            underlying="AAPL",
            reference_rows=rows,
            snapshot_rows=[],
            observed_at="2026-08-31T18:01:00Z",
            db_path=db_path,
        )
    except Exception:
        pass
    else:
        raise AssertionError("Expected duplicate reference identity failure.")


def test_snapshot_only_identity_is_reported(db_path):
    run_id = create_run(db_path)

    result = persist_massive_reference_and_snapshot(
        research_run_id=run_id,
        underlying="AAPL",
        reference_rows=reference_rows(),
        snapshot_rows=[
            {
                "details": {
                    "ticker": "O:AAPL260914C00245000"
                }
            },
            {
                "details": {
                    "ticker": "O:AAPL260914C00999000"
                }
            },
        ],
        observed_at="2026-08-31T18:01:00Z",
        db_path=db_path,
    )

    assert result["reconciliation"]["snapshot_only_count"] == 1
    assert result["reconciliation"]["snapshot_only_ids"] == (
        "O:AAPL260914C00999000",
    )
