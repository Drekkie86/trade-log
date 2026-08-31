from src.database.repository import (
    get_connection,
    record_unmatched_provider_contract_observation,
)
from src.research.reference_persistence import (
    persist_massive_reference_and_snapshot,
)
from src.research.thetadata_live_evidence import (
    find_thetadata_unmatched_evidence,
    persist_thetadata_unmatched_evidence,
)


def create_run(db_path):
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id, started_at, code_git_sha,
                preregistration_hash, us_session_date,
                us_session_state, status
            )
            VALUES (
                'UNMATCHED_TEST', '2026-08-31T18:00:00Z', 'abc',
                'hash', '2026-08-31', 'INTRADAY', 'STARTED'
            );
            """
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def test_massive_snapshot_only_is_persisted(db_path):
    run_id = create_run(db_path)
    reference_rows = [
        {
            "ticker": "O:AAPL260914C00245000",
            "expiration_date": "2026-09-14",
            "strike_price": 245.0,
            "contract_type": "call",
            "shares_per_contract": 100,
        }
    ]
    snapshot_rows = [
        {
            "details": {
                "ticker": "O:AAPL260914C00245000",
                "expiration_date": "2026-09-14",
                "strike_price": 245.0,
                "contract_type": "call",
            }
        },
        {
            "details": {
                "ticker": "O:AAPL260914P00250000",
                "expiration_date": "2026-09-14",
                "strike_price": 250.0,
                "contract_type": "put",
            }
        },
    ]

    result = persist_massive_reference_and_snapshot(
        research_run_id=run_id,
        underlying="AAPL",
        reference_rows=reference_rows,
        snapshot_rows=snapshot_rows,
        observed_at="2026-08-31T18:01:00Z",
        db_path=db_path,
    )
    assert result["reconciliation"]["snapshot_only_count"] == 1

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM unmatched_provider_contract_observations
            WHERE research_run_id = ?;
            """,
            (run_id,),
        ).fetchone()
        assert row["anomaly_type"] == "SNAPSHOT_ONLY"
        assert row["provider_contract_id"] == "O:AAPL260914P00250000"
        assert row["right"] == "P"
    finally:
        conn.close()


def test_theta_only_quote_and_greek_are_persistable(db_path):
    run_id = create_run(db_path)
    refs = [
        {
            "id": 1,
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
        }
    ]
    quote_rows = [
        {
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
        },
        {
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 250.0,
            "right": "P",
        },
    ]
    greek_rows = [
        {
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
        },
        {
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 255.0,
            "right": "P",
        },
    ]

    unmatched = find_thetadata_unmatched_evidence(
        reference_contracts=refs,
        quote_rows=quote_rows,
        greek_rows=greek_rows,
    )
    assert {
        item.anomaly_type
        for item in unmatched
    } == {
        "THETA_QUOTE_ONLY",
        "THETA_GREEK_ONLY",
    }

    assert persist_thetadata_unmatched_evidence(
        research_run_id=run_id,
        unmatched=unmatched,
        observed_at="2026-08-31T18:02:00Z",
        db_path=db_path,
    ) == 2


def test_unmatched_evidence_is_immutable(db_path):
    run_id = create_run(db_path)
    item_id = record_unmatched_provider_contract_observation(
        {
            "research_run_id": run_id,
            "provider": "THETADATA",
            "evidence_family": "THETADATA_QUOTE",
            "anomaly_type": "THETA_QUOTE_ONLY",
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 250.0,
            "right": "P",
            "observed_at": "2026-08-31T18:02:00Z",
        },
        db_path=db_path,
    )

    import sqlite3
    conn = get_connection(db_path)
    try:
        try:
            conn.execute(
                """
                UPDATE unmatched_provider_contract_observations
                SET strike = 999
                WHERE id = ?;
                """,
                (item_id,),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("Expected immutable evidence trigger.")
    finally:
        conn.close()
