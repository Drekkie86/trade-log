from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.repository import (
    create_market_snapshot,
)
from src.operations.historical_research import (
    PARITY_STATE_FAIL,
    PARITY_STATE_PASS,
    compare_hot_archive_session,
    profile_archived_session,
    profile_hot_session,
)
from src.operations.research_archive import (
    create_research_archive,
    find_archive_for_run,
    inventory_research_archives,
    open_verified_archive_connection,
    plan_archive_sessions,
    read_archived_run_evidence,
    verify_research_archive,
)


def _insert_completed_run(
    conn: sqlite3.Connection,
    *,
    session_date: str,
    minute: int,
) -> int:
    started = (
        f"{session_date}T14:{minute:02d}:00Z"
    )
    ended = (
        f"{session_date}T14:{minute:02d}:30Z"
    )
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
            'COHORT_TEST',
            'test-preregistration',
            'deadbeef',
            ?,
            ?,
            ?,
            'INTRADAY',
            'COMPLETED'
        );
        """,
        (
            started,
            ended,
            session_date,
        ),
    )
    return int(cursor.lastrowid)


def _quote() -> dict:
    timestamp = "2026-09-01T14:00:00Z"
    return {
        "provider_contract_id": "TEST-C-100",
        "option_symbol": "TEST-C-100",
        "right": "C",
        "strike": 100.0,
        "expiration": "2026-10-16",
        "quote_at": timestamp,
        "bid": 1.0,
        "bid_source": "FETCHED",
        "bid_at": timestamp,
        "ask": 1.2,
        "ask_source": "FETCHED",
        "ask_at": timestamp,
        "last": None,
        "last_source": "UNKNOWN",
        "last_at": None,
        "implied_volatility": None,
        "iv_source": "UNKNOWN",
        "iv_at": None,
        "delta": None,
        "delta_source": "UNKNOWN",
        "delta_at": None,
        "gamma": None,
        "gamma_source": "UNKNOWN",
        "gamma_at": None,
        "theta": None,
        "theta_source": "UNKNOWN",
        "theta_at": None,
        "vega": None,
        "vega_source": "UNKNOWN",
        "vega_at": None,
        "volume": None,
        "volume_source": "UNKNOWN",
        "volume_at": None,
        "open_interest": None,
        "open_interest_source": "UNKNOWN",
        "open_interest_at": None,
    }


def _seed_sessions(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        old_run = _insert_completed_run(
            conn,
            session_date="2026-09-01",
            minute=0,
        )

        # Fifty newer completed runs fill the hot retention window.
        for index in range(50):
            day = 2 + (index // 25)
            minute = index % 25
            _insert_completed_run(
                conn,
                session_date=f"2026-09-{day:02d}",
                minute=minute,
            )

        conn.commit()
    finally:
        conn.close()

    create_market_snapshot(
        {
            "captured_at": "2026-09-01T14:00:00Z",
            "underlying": "TEST",
            "provider": "MASSIVE",
            "provider_snapshot_id": "old-run-snapshot",
            "research_run_id": old_run,
            "us_session_date": "2026-09-01",
            "us_session_state": "INTRADAY",
            "underlying_price": 100.0,
            "underlying_source": "FETCHED",
            "underlying_at": "2026-09-01T14:00:00Z",
            "fx_to_eur": None,
            "fx_source": "UNKNOWN",
            "fx_at": None,
            "notes": "archive test",
        },
        [_quote()],
        db_path=db_path,
    )

    return old_run


def test_archive_plan_keeps_newest_fifty_completed_runs_hot(
    db_path,
    tmp_path,
):
    old_run = _seed_sessions(db_path)

    plan = plan_archive_sessions(
        db_path=db_path,
        archive_dir=tmp_path / "archives",
        keep_hot_runs=50,
    )

    old = next(
        item
        for item in plan
        if item.session_date == "2026-09-01"
    )
    newer = [
        item
        for item in plan
        if item.session_date != "2026-09-01"
    ]

    assert old.run_ids == (old_run,)
    assert old.eligible is True
    assert old.reason == "ELIGIBLE"
    assert all(
        item.eligible is False
        and item.reason == "WITHIN_HOT_RUN_WINDOW"
        for item in newer
    )


def test_create_verify_inventory_and_find_archive(
    db_path,
    tmp_path,
    monkeypatch,
):
    old_run = _seed_sessions(db_path)
    archive_dir = tmp_path / "archives"

    monkeypatch.setenv(
        "CHRISTIANIA_EVIDENCE_ARCHIVE_MIN_FREE_BYTES",
        "0",
    )

    progress = []

    manifest = create_research_archive(
        "2026-09-01",
        db_path=db_path,
        archive_dir=archive_dir,
        keep_hot_runs=50,
        progress=progress.append,
    )

    assert manifest.session_date == "2026-09-01"
    assert manifest.run_ids == (old_run,)
    assert manifest.table_counts["research_runs"] == 1
    assert manifest.table_counts["market_snapshots"] == 1
    assert manifest.table_counts["option_quotes"] == 1
    assert manifest.integrity_check == "ok"
    assert manifest.prune_eligible is False
    assert (
        manifest.prune_block_reason
        == "OFFHOST_IMMUTABLE_COPY_NOT_CONFIRMED"
    )

    archive_path = (
        archive_dir
        / manifest.archive_filename
    )
    manifest_path = (
        archive_dir
        / manifest.manifest_filename
    )

    assert archive_path.is_file()
    assert manifest_path.is_file()
    assert not any(
        path.name.endswith(".db.tmp")
        for path in archive_dir.iterdir()
    )

    verified = verify_research_archive(
        manifest_path,
        deep_payload=True,
    )
    assert verified.compressed_sha256 == manifest.compressed_sha256

    inventory = inventory_research_archives(
        archive_dir
    )
    assert inventory.archive_count == 1
    assert inventory.invalid_manifests == ()

    found = find_archive_for_run(
        old_run,
        archive_dir=archive_dir,
    )
    assert found is not None
    assert found.session_date == "2026-09-01"

    readback = read_archived_run_evidence(
        old_run,
        archive_dir=archive_dir,
    )
    assert readback.run_id == old_run
    assert readback.table_counts["research_runs"] == 1
    assert readback.table_counts["market_snapshots"] == 1
    assert readback.table_counts["option_quotes"] == 1

    assert any(
        "option_quotes=1" in message
        for message in progress
    )
    assert any(
        "archive: promoted" in message
        for message in progress
    )


def test_archive_plan_is_idempotent_after_verified_archive(
    db_path,
    tmp_path,
    monkeypatch,
):
    _seed_sessions(db_path)
    archive_dir = tmp_path / "archives"

    monkeypatch.setenv(
        "CHRISTIANIA_EVIDENCE_ARCHIVE_MIN_FREE_BYTES",
        "0",
    )

    create_research_archive(
        "2026-09-01",
        db_path=db_path,
        archive_dir=archive_dir,
        keep_hot_runs=50,
    )

    plan = plan_archive_sessions(
        db_path=db_path,
        archive_dir=archive_dir,
        keep_hot_runs=50,
    )

    old = next(
        item
        for item in plan
        if item.session_date == "2026-09-01"
    )

    assert old.eligible is False
    assert old.already_archived is True
    assert old.reason == "ALREADY_ARCHIVED"



def test_archive_is_read_only_query_source_and_matches_hot_analytics(
    db_path,
    tmp_path,
    monkeypatch,
):
    old_run = _seed_sessions(
        db_path
    )
    archive_dir = (
        tmp_path
        / "archives"
    )

    monkeypatch.setenv(
        "CHRISTIANIA_EVIDENCE_ARCHIVE_MIN_FREE_BYTES",
        "0",
    )

    manifest = create_research_archive(
        "2026-09-01",
        db_path=db_path,
        archive_dir=archive_dir,
        keep_hot_runs=50,
    )

    manifest_path = (
        archive_dir
        / manifest.manifest_filename
    )

    with open_verified_archive_connection(
        manifest_path
    ) as (
        archive_conn,
        verified,
    ):
        assert (
            verified.run_ids
            == (
                old_run,
            )
        )

        quote_count = int(
            archive_conn.execute(
                """
                SELECT COUNT(*)
                FROM option_quotes;
                """
            ).fetchone()[0]
        )

        assert quote_count == 1

        with pytest.raises(
            sqlite3.OperationalError,
        ):
            archive_conn.execute(
                """
                UPDATE option_quotes
                SET bid = 999.0;
                """
            )

    hot = profile_hot_session(
        manifest.session_date,
        run_ids=
            manifest.run_ids,
        db_path=db_path,
    )

    cold = profile_archived_session(
        manifest.session_date,
        archive_dir=archive_dir,
    )

    assert (
        hot.analytical_sha256
        == cold.analytical_sha256
    )

    parity = (
        compare_hot_archive_session(
            manifest.session_date,
            db_path=db_path,
            archive_dir=archive_dir,
        )
    )

    assert (
        parity.state
        == PARITY_STATE_PASS
    )
    assert parity.passed is True
    assert (
        parity.differing_sections
        == ()
    )


def test_hot_archive_analytics_detect_same_count_value_drift(
    db_path,
    tmp_path,
    monkeypatch,
):
    _seed_sessions(
        db_path
    )
    archive_dir = (
        tmp_path
        / "archives"
    )

    monkeypatch.setenv(
        "CHRISTIANIA_EVIDENCE_ARCHIVE_MIN_FREE_BYTES",
        "0",
    )

    manifest = create_research_archive(
        "2026-09-01",
        db_path=db_path,
        archive_dir=archive_dir,
        keep_hot_runs=50,
    )

    before = (
        compare_hot_archive_session(
            manifest.session_date,
            db_path=db_path,
            archive_dir=archive_dir,
        )
    )

    assert before.passed is True

    conn = sqlite3.connect(
        db_path
    )
    try:
        trigger_rows = (
            conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'trigger'
                  AND tbl_name = 'option_quotes'
                  AND UPPER(sql)
                      LIKE '%BEFORE UPDATE%';
                """
            ).fetchall()
        )

        for row in trigger_rows:
            trigger_name = str(
                row[0]
            )

            assert (
                trigger_name.replace(
                    "_",
                    "",
                ).isalnum()
            )

            conn.execute(
                f'DROP TRIGGER "{trigger_name}";'
            )

        quote_id = int(
            conn.execute(
                """
                SELECT oq.id
                FROM option_quotes AS oq
                JOIN market_snapshots AS ms
                  ON ms.id = oq.snapshot_id
                WHERE ms.research_run_id = ?
                LIMIT 1;
                """,
                (
                    manifest.run_ids[0],
                ),
            ).fetchone()[0]
        )

        conn.execute(
            """
            UPDATE option_quotes
            SET bid = bid + 0.5
            WHERE id = ?;
            """,
            (
                quote_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    after = (
        compare_hot_archive_session(
            manifest.session_date,
            db_path=db_path,
            archive_dir=archive_dir,
        )
    )

    assert (
        after.state
        == PARITY_STATE_FAIL
    )
    assert after.passed is False
    assert (
        "scalar_metrics"
        in after.differing_sections
    )
    assert (
        after.hot_analytical_sha256
        != after.archive_analytical_sha256
    )
