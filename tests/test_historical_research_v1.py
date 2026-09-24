from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.repository import (
    create_market_snapshot,
)
from src.operations.historical_research import (
    analyze_archived_session,
    analyze_historical_connection,
    analyze_hot_session,
    compare_hot_archive_session,
    compare_hot_connection_to_archive,
    open_historical_session,
)
from src.operations.research_archive import (
    create_research_archive,
)


SESSION = "2026-09-01"


def _insert_completed_run(
    conn: sqlite3.Connection,
    *,
    session_date: str,
    minute: int,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO research_runs(
            cohort_id,
            preregistration_hash,
            code_git_sha,
            started_at,
            ended_at,
            us_session_date,
            us_session_state,
            status
        )
        VALUES(
            'COHORT_HISTORICAL_TEST',
            'historical-test-prereg',
            'deadbeef',
            ?,
            ?,
            ?,
            'INTRADAY',
            'COMPLETED'
        );
        """,
        (
            f"{session_date}T14:{minute:02d}:00Z",
            f"{session_date}T14:{minute:02d}:30Z",
            session_date,
        ),
    )

    return int(
        cursor.lastrowid
    )


def _quote(
    symbol: str,
    strike: float,
) -> dict:
    timestamp = (
        "2026-09-01T14:00:00Z"
    )

    return {
        "provider_contract_id":
            symbol,
        "option_symbol":
            symbol,
        "right": "C",
        "strike": strike,
        "expiration":
            "2026-10-16",
        "quote_at":
            timestamp,
        "bid": 1.0,
        "bid_source":
            "FETCHED",
        "bid_at":
            timestamp,
        "ask": 1.2,
        "ask_source":
            "FETCHED",
        "ask_at":
            timestamp,
        "last": None,
        "last_source":
            "UNKNOWN",
        "last_at": None,
        "implied_volatility":
            0.25,
        "iv_source":
            "FETCHED",
        "iv_at":
            timestamp,
        "delta": 0.4,
        "delta_source":
            "FETCHED",
        "delta_at":
            timestamp,
        "gamma": 0.02,
        "gamma_source":
            "FETCHED",
        "gamma_at":
            timestamp,
        "theta": -0.03,
        "theta_source":
            "FETCHED",
        "theta_at":
            timestamp,
        "vega": 0.08,
        "vega_source":
            "FETCHED",
        "vega_at":
            timestamp,
        "volume": 10,
        "volume_source":
            "FETCHED",
        "volume_at":
            timestamp,
        "open_interest": 20,
        "open_interest_source":
            "FETCHED",
        "open_interest_at":
            timestamp,
    }


def _snapshot(
    *,
    run_id: int,
    suffix: str,
) -> dict:
    return {
        "captured_at":
            "2026-09-01T14:00:00Z",
        "underlying": "TEST",
        "provider": "MASSIVE",
        "provider_snapshot_id":
            f"historical-{suffix}",
        "research_run_id":
            run_id,
        "us_session_date":
            SESSION,
        "us_session_state":
            "INTRADAY",
        "underlying_price":
            100.0,
        "underlying_source":
            "FETCHED",
        "underlying_at":
            "2026-09-01T14:00:00Z",
        "fx_to_eur": None,
        "fx_source": "UNKNOWN",
        "fx_at": None,
        "notes":
            "historical analysis test",
    }


def _seed_archive(
    db_path: Path,
    archive_dir: Path,
    monkeypatch,
) -> tuple[
    int,
    object,
]:
    conn = sqlite3.connect(
        db_path
    )

    try:
        old_run = (
            _insert_completed_run(
                conn,
                session_date=SESSION,
                minute=0,
            )
        )

        for index in range(
            50
        ):
            day = (
                2
                + index // 25
            )

            _insert_completed_run(
                conn,
                session_date=(
                    f"2026-09-{day:02d}"
                ),
                minute=(
                    index % 25
                ),
            )

        conn.commit()

    finally:
        conn.close()

    create_market_snapshot(
        _snapshot(
            run_id=old_run,
            suffix="baseline",
        ),
        [
            _quote(
                "TEST-C-100",
                100.0,
            ),
        ],
        db_path=db_path,
    )

    monkeypatch.setenv(
        "CHRISTIANIA_EVIDENCE_ARCHIVE_MIN_FREE_BYTES",
        "0",
    )

    manifest = (
        create_research_archive(
            SESSION,
            db_path=db_path,
            archive_dir=
                archive_dir,
            keep_hot_runs=50,
        )
    )

    return (
        old_run,
        manifest,
    )


def test_historical_analysis_hot_and_archive_have_identical_canonical_result(
    db_path,
    tmp_path,
    monkeypatch,
):
    archive_dir = (
        tmp_path
        / "archives"
    )

    (
        old_run,
        manifest,
    ) = _seed_archive(
        db_path,
        archive_dir,
        monkeypatch,
    )

    archive = (
        analyze_archived_session(
            SESSION,
            archive_dir=
                archive_dir,
        )
    )

    hot = analyze_hot_session(
        SESSION,
        db_path=db_path,
    )

    parity = (
        compare_hot_archive_session(
            SESSION,
            db_path=db_path,
            archive_dir=
                archive_dir,
        )
    )

    assert archive.run_ids == (
        old_run,
    )
    assert hot.run_ids == (
        old_run,
    )
    assert (
        archive.canonical_sha256
        == hot.canonical_sha256
    )
    assert parity.passed is True
    assert (
        parity.mismatched_metrics
        == ()
    )
    assert all(
        parity.metric_matches.values()
    )

    quote_metric = next(
        metric
        for metric
        in archive.metrics
        if (
            metric.name
            == "quote_universe_quality"
        )
    )

    assert len(
        quote_metric.rows
    ) == 1

    assert (
        manifest.archive_filename
        == archive.archive_filename
    )


def test_historical_parity_detects_hot_drift_after_archive(
    db_path,
    tmp_path,
    monkeypatch,
):
    archive_dir = (
        tmp_path
        / "archives"
    )

    (
        old_run,
        _,
    ) = _seed_archive(
        db_path,
        archive_dir,
        monkeypatch,
    )

    create_market_snapshot(
        _snapshot(
            run_id=old_run,
            suffix="post-archive",
        ),
        [
            _quote(
                "TEST-C-105",
                105.0,
            ),
        ],
        db_path=db_path,
    )

    parity = (
        compare_hot_archive_session(
            SESSION,
            db_path=db_path,
            archive_dir=
                archive_dir,
        )
    )

    assert parity.passed is False
    assert (
        "quote_universe_quality"
        in parity.mismatched_metrics
    )


def test_historical_analysis_hash_excludes_storage_schema_version(
    db_path,
):
    run_id = (
        _insert_completed_run_for_hash_test(
            db_path
        )
    )

    uri = (
        Path(
            db_path
        ).resolve().as_uri()
        + "?mode=ro"
    )

    conn = sqlite3.connect(
        uri,
        uri=True,
    )

    try:
        v33 = (
            analyze_historical_connection(
                conn,
                session_date=SESSION,
                run_ids=(
                    run_id,
                ),
                source="ARCHIVE",
                source_schema_version=33,
            )
        )

        v34 = (
            analyze_historical_connection(
                conn,
                session_date=SESSION,
                run_ids=(
                    run_id,
                ),
                source="HOT",
                source_schema_version=34,
            )
        )

        assert (
            v33.canonical_sha256
            == v34.canonical_sha256
        )
        assert (
            v33.source_schema_version
            == 33
        )
        assert (
            v34.source_schema_version
            == 34
        )

    finally:
        conn.close()


def _insert_completed_run_for_hash_test(
    db_path: Path,
) -> int:
    conn = sqlite3.connect(
        db_path
    )

    try:
        run_id = (
            _insert_completed_run(
                conn,
                session_date=SESSION,
                minute=1,
            )
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def test_hybrid_historical_session_is_read_only_and_exposes_hot_schema(
    db_path,
    tmp_path,
    monkeypatch,
):
    archive_dir = (
        tmp_path
        / "archives"
    )

    _seed_archive(
        db_path,
        archive_dir,
        monkeypatch,
    )

    with open_historical_session(
        SESSION,
        db_path=db_path,
        archive_dir=
            archive_dir,
    ) as (
        manifest,
        conn,
    ):
        archive_quotes = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM option_quotes;
                """
            ).fetchone()[0]
        )

        hot_schema = int(
            conn.execute(
                """
                SELECT MAX(version)
                FROM hot.schema_version;
                """
            ).fetchone()[0]
        )

        query_only = int(
            conn.execute(
                "PRAGMA query_only;"
            ).fetchone()[0]
        )

        assert archive_quotes == 1
        assert hot_schema == 34
        assert query_only == 1
        assert (
            manifest.session_date
            == SESSION
        )

        with pytest.raises(
            sqlite3.OperationalError,
        ):
            conn.execute(
                """
                CREATE TEMP TABLE
                forbidden_write(
                    id INTEGER
                );
                """
            )


def test_parity_can_run_inside_existing_hot_write_transaction(
    db_path,
    tmp_path,
    monkeypatch,
):
    archive_dir = (
        tmp_path
        / "archives"
    )

    (
        _,
        manifest,
    ) = _seed_archive(
        db_path,
        archive_dir,
        monkeypatch,
    )

    manifest_path = (
        archive_dir
        / manifest.manifest_filename
    )

    conn = sqlite3.connect(
        db_path,
        isolation_level=None,
    )

    try:
        conn.execute(
            "BEGIN IMMEDIATE;"
        )

        parity = (
            compare_hot_connection_to_archive(
                conn,
                manifest_path=
                    manifest_path,
            )
        )

        assert parity.passed is True
        assert conn.in_transaction is True

        conn.rollback()

    finally:
        conn.close()


def test_archived_analysis_survives_hot_raw_evidence_removal(
    db_path,
    tmp_path,
    monkeypatch,
):
    archive_dir = (
        tmp_path
        / "archives"
    )

    (
        old_run,
        _,
    ) = _seed_archive(
        db_path,
        archive_dir,
        monkeypatch,
    )

    before = (
        analyze_archived_session(
            SESSION,
            archive_dir=
                archive_dir,
        )
    )

    conn = sqlite3.connect(
        db_path
    )

    try:
        # Model the post-prune state without coupling this historical-reader
        # test to V2C's full remote-proof machinery. The production prune
        # temporarily drops this exact guard transactionally.
        conn.execute(
            """
            DROP TRIGGER
            trg_option_quotes_no_delete;
            """
        )

        conn.execute(
            """
            DELETE FROM option_quotes
            WHERE snapshot_id IN (
                SELECT id
                FROM market_snapshots
                WHERE research_run_id = ?
            );
            """,
            (
                old_run,
            ),
        )

        conn.commit()

    finally:
        conn.close()

    after = (
        analyze_archived_session(
            SESSION,
            archive_dir=
                archive_dir,
        )
    )

    hot_after = (
        analyze_hot_session(
            SESSION,
            db_path=db_path,
        )
    )

    assert (
        after.canonical_sha256
        == before.canonical_sha256
    )

    quote_before = next(
        metric
        for metric in before.metrics
        if (
            metric.name
            == "quote_universe_quality"
        )
    )

    quote_after = next(
        metric
        for metric in after.metrics
        if (
            metric.name
            == "quote_universe_quality"
        )
    )

    assert (
        quote_after.sha256
        == quote_before.sha256
    )
    assert (
        len(
            quote_after.rows
        )
        == 1
    )

    assert (
        hot_after.canonical_sha256
        != after.canonical_sha256
    )


def test_historical_analysis_fails_closed_on_missing_required_columns():
    conn = sqlite3.connect(
        ":memory:"
    )

    try:
        conn.executescript(
            """
            CREATE TABLE research_runs(
                id INTEGER PRIMARY KEY
            );
            """
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "Historical Analysis V1 "
                "schema is incompatible"
            ),
        ):
            analyze_historical_connection(
                conn,
                session_date=SESSION,
                run_ids=(1,),
                source="ARCHIVE",
                source_schema_version=1,
            )

    finally:
        conn.close()
