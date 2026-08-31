from src.database.repository import get_connection
from src.research.reference_persistence import (
    persist_massive_reference_frame,
)
from src.research.thetadata_live_evidence import (
    ThetaLiveEvidenceError,
    join_thetadata_live_evidence,
    persist_thetadata_live_availability,
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
                'THETA_LIVE_JOIN_TEST',
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
        },
        {
            "ticker": "O:AAPL260914P00245000",
            "expiration_date": "2026-09-14",
            "strike_price": 245.0,
            "contract_type": "put",
            "exercise_style": "american",
            "shares_per_contract": 100,
        },
    ]


def persisted_reference_contracts(db_path, run_id):
    mapping = persist_massive_reference_frame(
        research_run_id=run_id,
        underlying="AAPL",
        reference_rows=reference_rows(),
        observed_at="2026-08-31T18:01:00Z",
        db_path=db_path,
    )

    return [
        {
            "id": mapping["O:AAPL260914C00245000"],
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
        },
        {
            "id": mapping["O:AAPL260914P00245000"],
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "P",
        },
    ]


def test_quote_freshness_comes_from_quote_age_not_greek_timestamp():
    refs = [
        {
            "id": 1,
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
        }
    ]

    joined = join_thetadata_live_evidence(
        reference_contracts=refs,
        quote_rows=[
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "CALL",
                "quote_age_seconds": 90.0,
                "raw_timestamp": "09:32:00",
            }
        ],
        greek_rows=[
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "CALL",
                "iv_error": 0.001,
                "raw_timestamp": "11:05:00",
            }
        ],
    )

    assert joined[0].quote_freshness.value == "STALE"
    assert joined[0].greek_quality.value == "GOOD"


def test_missing_quote_does_not_become_fresh_from_greek_presence():
    refs = [
        {
            "id": 1,
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
        }
    ]

    joined = join_thetadata_live_evidence(
        reference_contracts=refs,
        quote_rows=[],
        greek_rows=[
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "CALL",
                "iv_error": 0.001,
            }
        ],
    )

    assert joined[0].quote_state == "ABSENT"
    assert joined[0].quote_freshness.value == "UNKNOWN"
    assert joined[0].greek_state == "PRESENT"


def test_persists_quote_and_greek_availability(db_path):
    run_id = create_run(db_path)
    refs = persisted_reference_contracts(
        db_path,
        run_id,
    )

    joined = join_thetadata_live_evidence(
        reference_contracts=refs,
        quote_rows=[
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "CALL",
                "quote_age_seconds": 2.0,
            }
        ],
        greek_rows=[
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "CALL",
                "iv_error": 0.001,
            }
        ],
    )

    counts = persist_thetadata_live_availability(
        joined=joined,
        observed_at="2026-08-31T18:02:00Z",
        db_path=db_path,
    )

    assert counts == {
        "quote_present": 1,
        "quote_absent": 1,
        "greek_present": 1,
        "greek_absent": 1,
    }

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT evidence_family, state, reason_code, reason_detail
            FROM provider_observation_availability
            WHERE provider = 'THETADATA'
            ORDER BY id;
            """
        ).fetchall()
        assert len(rows) == 4

        assert rows[0]["evidence_family"] == "THETADATA_QUOTE"
        assert rows[0]["state"] == "PRESENT"
        assert rows[0]["reason_detail"] == "freshness=FRESH"

        assert rows[1]["evidence_family"] == "THETADATA_GREEKS"
        assert rows[1]["state"] == "PRESENT"
        assert rows[1]["reason_detail"] == "greek_quality=GOOD"

        assert rows[2]["state"] == "ABSENT"
        assert rows[2]["reason_code"] == "QUOTE_OBSERVATION_ABSENT"

        assert rows[3]["state"] == "ABSENT"
        assert rows[3]["reason_code"] == "MODEL_OBSERVATION_ABSENT"
    finally:
        conn.close()


def test_duplicate_theta_quote_identity_fails_closed():
    refs = [
        {
            "id": 1,
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
        }
    ]

    duplicate = {
        "underlying": "AAPL",
        "expiration": "2026-09-14",
        "strike": 245.0,
        "right": "CALL",
        "quote_age_seconds": 2.0,
    }

    try:
        join_thetadata_live_evidence(
            reference_contracts=refs,
            quote_rows=[duplicate, dict(duplicate)],
            greek_rows=[],
        )
    except ThetaLiveEvidenceError:
        pass
    else:
        raise AssertionError(
            "Expected duplicate quote identity failure."
        )


def test_unknown_quote_age_is_not_fresh():
    refs = [
        {
            "id": 1,
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
        }
    ]

    joined = join_thetadata_live_evidence(
        reference_contracts=refs,
        quote_rows=[
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "CALL",
            }
        ],
        greek_rows=[],
    )

    assert joined[0].quote_state == "PRESENT"
    assert joined[0].quote_freshness.value == "UNKNOWN"
