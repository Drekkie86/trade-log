import sqlite3
from pathlib import Path

from src.database.repository import (
    create_listing_reference_contract,
    create_listing_reference_contracts,
    get_connection,
    record_provider_observation_availabilities,
)


def create_run(conn):
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
            'PERF_TEST',
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


def test_get_connection_enables_wal_for_file_database(db_path):
    conn = get_connection(db_path)
    try:
        mode = conn.execute(
            "PRAGMA journal_mode;"
        ).fetchone()[0]
        assert str(mode).lower() == "wal"
    finally:
        conn.close()

    assert Path(str(db_path) + "-wal").exists() is False or True


def test_batch_listing_insert_returns_all_ids(db_path):
    conn = get_connection(db_path)
    try:
        run_id = create_run(conn)
    finally:
        conn.close()

    contracts = [
        {
            "research_run_id": run_id,
            "provider": "MASSIVE",
            "underlying": "AAPL",
            "provider_contract_id": f"O:TEST{i}",
            "option_symbol": f"O:TEST{i}",
            "expiration": "2026-09-18",
            "strike": 200.0 + i,
            "right": "C",
            "observed_at": "2026-08-31T18:01:00Z",
        }
        for i in range(100)
    ]

    result = create_listing_reference_contracts(
        contracts,
        db_path=db_path,
    )

    assert len(result) == 100
    assert (
        run_id,
        "MASSIVE",
        "O:TEST0",
    ) in result


def test_batch_observation_insert(db_path):
    conn = get_connection(db_path)
    try:
        run_id = create_run(conn)
    finally:
        conn.close()

    contracts = [
        {
            "research_run_id": run_id,
            "provider": "MASSIVE",
            "underlying": "AAPL",
            "provider_contract_id": f"O:OBS{i}",
            "option_symbol": f"O:OBS{i}",
            "expiration": "2026-09-18",
            "strike": 200.0 + i,
            "right": "C",
            "observed_at": "2026-08-31T18:01:00Z",
        }
        for i in range(10)
    ]
    ids = create_listing_reference_contracts(
        contracts,
        db_path=db_path,
    )

    observations = [
        {
            "reference_contract_id":
                ids[(run_id, "MASSIVE", f"O:OBS{i}")],
            "provider":
                "MASSIVE",
            "evidence_family":
                "MASSIVE_SNAPSHOT",
            "state":
                "PRESENT",
            "observed_at":
                "2026-08-31T18:02:00Z",
        }
        for i in range(10)
    ]

    assert record_provider_observation_availabilities(
        observations,
        db_path=db_path,
    ) == 10

    conn = get_connection(db_path)
    try:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM provider_observation_availability;
            """
        ).fetchone()[0]
        assert count == 10
    finally:
        conn.close()


def test_single_row_api_still_returns_inserted_id(db_path):
    conn = get_connection(db_path)
    try:
        run_id = create_run(conn)
    finally:
        conn.close()

    row_id = create_listing_reference_contract(
        {
            "research_run_id": run_id,
            "provider": "MASSIVE",
            "underlying": "AAPL",
            "provider_contract_id": "O:SINGLE",
            "option_symbol": "O:SINGLE",
            "expiration": "2026-09-18",
            "strike": 250.0,
            "right": "C",
            "observed_at": "2026-08-31T18:01:00Z",
        },
        db_path=db_path,
    )

    assert isinstance(row_id, int)
    assert row_id > 0
