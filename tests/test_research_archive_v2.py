from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

import src.operations.archive_analytics as archive_analytics
import src.operations.research_archive as research_archive

from src.database.repository import (
    create_market_snapshot,
)
from src.operations.archive_analytics import (
    ARCHIVE_PARITY_STATE,
    open_verified_archive_session,
    parity_receipt_path,
    read_archived_session_profile,
    validate_archive_parity_receipt,
    verify_archive_session_parity,
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



def test_verified_archive_session_is_read_only_and_analytically_queryable(
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

    manifest = (
        create_research_archive(
            "2026-09-01",
            db_path=db_path,
            archive_dir=archive_dir,
            keep_hot_runs=50,
        )
    )

    with open_verified_archive_session(
        "2026-09-01",
        archive_dir=archive_dir,
    ) as archive:
        assert (
            archive.manifest
            == manifest
        )

        count = int(
            archive.connection.execute(
                """
                SELECT COUNT(*)
                FROM option_quotes;
                """
            ).fetchone()[0]
        )

        assert count == 1

        with pytest.raises(
            sqlite3.OperationalError,
        ):
            archive.connection.execute(
                """
                DELETE FROM option_quotes;
                """
            )


def test_hot_cold_full_content_parity_writes_bound_receipt(
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

    manifest = (
        create_research_archive(
            "2026-09-01",
            db_path=db_path,
            archive_dir=archive_dir,
            keep_hot_runs=50,
        )
    )

    progress = []

    receipt = (
        verify_archive_session_parity(
            "2026-09-01",
            db_path=db_path,
            archive_dir=archive_dir,
            progress=progress.append,
        )
    )

    assert (
        receipt.state
        == ARCHIVE_PARITY_STATE
    )
    assert receipt.content_parity is True
    assert receipt.run_ids == (
        old_run,
    )
    assert (
        receipt.archive_source_schema_version
        == manifest.source_schema_version
    )
    assert (
        receipt.current_schema_version
        == 34
    )

    assert set(
        receipt.hot_fingerprints
    ) == set(
        receipt.archive_fingerprints
    )

    for table_name in (
        receipt.hot_fingerprints
    ):
        assert (
            receipt.hot_fingerprints[
                table_name
            ]
            == receipt.archive_fingerprints[
                table_name
            ]
        )

    manifest_path = (
        archive_dir
        / manifest.manifest_filename
    )

    receipt_path = (
        parity_receipt_path(
            manifest_path
        )
    )

    assert receipt_path.is_file()

    validated = (
        validate_archive_parity_receipt(
            "2026-09-01",
            db_path=db_path,
            archive_dir=archive_dir,
        )
    )

    assert validated == receipt

    assert any(
        "hot option_quotes complete"
        in message
        for message in progress
    )
    assert any(
        "archive option_quotes complete"
        in message
        for message in progress
    )
    assert any(
        "receipt written"
        in message
        for message in progress
    )


def test_parity_receipt_fails_closed_when_tampered(
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

    manifest = (
        create_research_archive(
            "2026-09-01",
            db_path=db_path,
            archive_dir=archive_dir,
            keep_hot_runs=50,
        )
    )

    verify_archive_session_parity(
        "2026-09-01",
        db_path=db_path,
        archive_dir=archive_dir,
    )

    receipt_path = (
        parity_receipt_path(
            archive_dir
            / manifest.manifest_filename
        )
    )

    payload = json.loads(
        receipt_path.read_text(
            encoding="utf-8",
        )
    )

    payload[
        "hot_fingerprints"
    ][
        "option_quotes"
    ][
        "content_sha256"
    ] = "0" * 64

    receipt_path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="non-matching fingerprints",
    ):
        validate_archive_parity_receipt(
            "2026-09-01",
            db_path=db_path,
            archive_dir=archive_dir,
        )


def test_archive_session_profile_exposes_replayable_universe_summary(
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

    create_research_archive(
        "2026-09-01",
        db_path=db_path,
        archive_dir=archive_dir,
        keep_hot_runs=50,
    )

    profile = (
        read_archived_session_profile(
            "2026-09-01",
            archive_dir=archive_dir,
        )
    )

    assert profile.run_ids == (
        old_run,
    )
    assert (
        profile.table_counts[
            "option_quotes"
        ]
        == 1
    )
    assert (
        profile.option_quote_universe[
            "row_count"
        ]
        == 1
    )
    assert (
        profile.option_quote_universe[
            "underlying_count"
        ]
        == 1
    )
    assert (
        profile.option_quote_universe[
            "bid_rows"
        ]
        == 1
    )



def test_verified_archive_materialization_preserves_runtime_free_space_reserve(
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

    create_research_archive(
        "2026-09-01",
        db_path=db_path,
        archive_dir=archive_dir,
        keep_hot_runs=50,
    )

    monkeypatch.setattr(
        archive_analytics.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(
            total=100 * 1024**3,
            free=1,
        ),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Insufficient temporary "
            "filesystem headroom"
        ),
    ):
        with open_verified_archive_session(
            "2026-09-01",
            archive_dir=archive_dir,
        ):
            raise AssertionError(
                "archive session must not "
                "open without capacity"
            )


def test_parity_receipt_row_counts_are_bound_to_manifest(
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

    manifest = (
        create_research_archive(
            "2026-09-01",
            db_path=db_path,
            archive_dir=archive_dir,
            keep_hot_runs=50,
        )
    )

    verify_archive_session_parity(
        "2026-09-01",
        db_path=db_path,
        archive_dir=archive_dir,
    )

    receipt_path = (
        parity_receipt_path(
            archive_dir
            / manifest.manifest_filename
        )
    )

    payload = json.loads(
        receipt_path.read_text(
            encoding="utf-8",
        )
    )

    for side in (
        "hot_fingerprints",
        "archive_fingerprints",
    ):
        payload[
            side
        ][
            "option_quotes"
        ][
            "row_count"
        ] = 999

    receipt_path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "row count does not "
            "match manifest"
        ),
    ):
        validate_archive_parity_receipt(
            "2026-09-01",
            db_path=db_path,
            archive_dir=archive_dir,
        )



def test_v33_archive_remains_readable_and_parity_valid_after_v34_index_migration(
    db_path,
    tmp_path,
    monkeypatch,
):
    legacy_db = (
        tmp_path
        / "legacy-v33.db"
    )

    source = sqlite3.connect(
        db_path
    )
    target = sqlite3.connect(
        legacy_db
    )
    try:
        source.backup(
            target
        )
        target.commit()
    finally:
        target.close()
        source.close()

    conn = sqlite3.connect(
        legacy_db
    )
    try:
        for index_name in (
            "idx_shadow_candidates_reference_contract",
            "idx_shadow_candidates_entry_quote_observation",
            "idx_shadow_candidates_entry_greek_observation",
            "idx_hypothesis_scanner_evaluations_reference_contract",
            "idx_hypothesis_scanner_evaluations_option_quote",
            "idx_surface_v2_reference_contract",
        ):
            conn.execute(
                f'DROP INDEX IF EXISTS "{index_name}";'
            )

        conn.execute(
            """
            DELETE FROM schema_version
            WHERE version = 34;
            """
        )
        conn.commit()

        version = int(
            conn.execute(
                """
                SELECT MAX(version)
                FROM schema_version;
                """
            ).fetchone()[0]
        )
        assert version == 33
    finally:
        conn.close()

    _seed_sessions(
        legacy_db
    )

    archive_dir = (
        tmp_path
        / "legacy-archives"
    )

    monkeypatch.setenv(
        "CHRISTIANIA_EVIDENCE_ARCHIVE_MIN_FREE_BYTES",
        "0",
    )

    monkeypatch.setattr(
        research_archive,
        "EXPECTED_SCHEMA_VERSION",
        33,
    )

    manifest = (
        create_research_archive(
            "2026-09-01",
            db_path=legacy_db,
            archive_dir=archive_dir,
            keep_hot_runs=50,
        )
    )

    assert (
        manifest.source_schema_version
        == 33
    )

    monkeypatch.setattr(
        research_archive,
        "EXPECTED_SCHEMA_VERSION",
        34,
    )

    migration = (
        Path(__file__).resolve()
        .parents[1]
        / "migrations"
        / "034_prune_parent_fk_indexes.sql"
    )

    conn = sqlite3.connect(
        legacy_db
    )
    try:
        conn.executescript(
            migration.read_text(
                encoding="utf-8",
            )
        )
        conn.commit()

        assert int(
            conn.execute(
                """
                SELECT MAX(version)
                FROM schema_version;
                """
            ).fetchone()[0]
        ) == 34
    finally:
        conn.close()

    verified = verify_research_archive(
        archive_dir
        / manifest.manifest_filename,
        deep_payload=True,
    )

    assert (
        verified.source_schema_version
        == 33
    )

    profile = (
        read_archived_session_profile(
            "2026-09-01",
            archive_dir=archive_dir,
        )
    )

    assert (
        profile.archive_source_schema_version
        == 33
    )

    receipt = (
        verify_archive_session_parity(
            "2026-09-01",
            db_path=legacy_db,
            archive_dir=archive_dir,
        )
    )

    assert (
        receipt.archive_source_schema_version
        == 33
    )
    assert (
        receipt.current_schema_version
        == 34
    )
    assert receipt.content_parity is True



def test_archive_materialization_capacity_reserves_full_sort_workspace(
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

    manifest = (
        create_research_archive(
            "2026-09-01",
            db_path=db_path,
            archive_dir=archive_dir,
            keep_hot_runs=50,
        )
    )

    observed = {}

    def required_free(
        *,
        source_size_bytes,
        filesystem_total_bytes,
    ):
        observed[
            "source_size_bytes"
        ] = source_size_bytes
        observed[
            "filesystem_total_bytes"
        ] = filesystem_total_bytes
        return 0

    monkeypatch.setattr(
        archive_analytics,
        "backup_required_free_bytes",
        required_free,
    )

    with open_verified_archive_session(
        "2026-09-01",
        archive_dir=archive_dir,
    ) as archive:
        assert (
            archive.manifest
            == manifest
        )

    assert (
        observed[
            "source_size_bytes"
        ]
        == (
            manifest.uncompressed_size_bytes
            * 2
        )
    )
