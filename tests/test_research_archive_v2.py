from __future__ import annotations

import sqlite3
from pathlib import Path

from src.database.repository import (
    create_market_snapshot,
)
from src.operations.research_archive import (
    create_research_archive,
    find_archive_for_run,
    inventory_research_archives,
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
