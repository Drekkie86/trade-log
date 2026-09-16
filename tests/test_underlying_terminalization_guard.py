import pytest

from src.database.repository import get_connection
from src.research.independent_runner import (
    IndependentResearchRunnerError,
    _finish_underlying,
)


def _seed_attempted_underlying(db_path) -> int:
    conn = get_connection(db_path)
    try:
        run_id = int(
            conn.execute(
                """
                INSERT INTO research_runs (
                    cohort_id,
                    preregistration_hash,
                    code_git_sha,
                    started_at,
                    us_session_date,
                    us_session_state,
                    status,
                    attempted_underlyings,
                    succeeded_underlyings,
                    failed_underlyings
                )
                VALUES (
                    'INDEPENDENT_RESEARCH_RUNNER_V1',
                    'test-hash',
                    'test-sha',
                    '2026-09-01T18:00:00Z',
                    '2026-09-01',
                    'INTRADAY',
                    'COLLECTING',
                    1,
                    0,
                    0
                );
                """
            ).lastrowid
        )

        conn.execute(
            """
            INSERT INTO research_run_underlyings (
                run_id,
                underlying,
                attempted_at,
                status,
                retry_count
            )
            VALUES (
                ?,
                'AAPL',
                '2026-09-01T18:00:01Z',
                'ATTEMPTED',
                0
            );
            """,
            (run_id,),
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def test_underlying_terminalization_is_single_shot(db_path):
    run_id = _seed_attempted_underlying(db_path)

    _finish_underlying(
        run_id=run_id,
        underlying="AAPL",
        completed_at="2026-09-01T18:00:02Z",
        succeeded=True,
        db_path=db_path,
    )

    with pytest.raises(
        IndependentResearchRunnerError,
        match="terminalized exactly once",
    ):
        _finish_underlying(
            run_id=run_id,
            underlying="AAPL",
            completed_at="2026-09-01T18:00:03Z",
            succeeded=False,
            failure_reason="duplicate terminalization attempt",
            db_path=db_path,
        )

    conn = get_connection(db_path)
    try:
        child = conn.execute(
            """
            SELECT status, failure_code, failure_reason, completed_at
            FROM research_run_underlyings
            WHERE run_id = ?
              AND underlying = 'AAPL';
            """,
            (run_id,),
        ).fetchone()

        parent = conn.execute(
            """
            SELECT
                attempted_underlyings,
                succeeded_underlyings,
                failed_underlyings
            FROM research_runs
            WHERE id = ?;
            """,
            (run_id,),
        ).fetchone()

        assert child["status"] == "SUCCESS"
        assert child["failure_code"] is None
        assert child["failure_reason"] is None
        assert child["completed_at"] == "2026-09-01T18:00:02Z"

        assert parent["attempted_underlyings"] == 1
        assert parent["succeeded_underlyings"] == 1
        assert parent["failed_underlyings"] == 0
    finally:
        conn.close()
