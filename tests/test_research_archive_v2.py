from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.database.repository import (
    create_market_snapshot,
)
from src.operations.historical_evidence import (
    open_verified_archive_session,
    read_historical_session_profile,
    verify_hot_archive_parity,
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



def _create_old_session_archive(
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

    return (
        old_run,
        archive_dir,
        manifest,
    )


def test_verified_archive_session_is_read_only(
    db_path,
    tmp_path,
    monkeypatch,
):
    (
        _,
        archive_dir,
        manifest,
    ) = _create_old_session_archive(
        db_path,
        tmp_path,
        monkeypatch,
    )

    with open_verified_archive_session(
        manifest.session_date,
        archive_dir=archive_dir,
    ) as (
        opened_manifest,
        conn,
    ):
        assert (
            opened_manifest.archive_filename
            == manifest.archive_filename
        )

        assert (
            conn.execute(
                "PRAGMA query_only;"
            ).fetchone()[0]
            == 1
        )

        with pytest.raises(
            sqlite3.OperationalError
        ):
            conn.execute(
                "CREATE TABLE forbidden_write("
                "id INTEGER"
                ");"
            )


def test_historical_profile_reads_cold_evidence(
    db_path,
    tmp_path,
    monkeypatch,
):
    (
        old_run,
        archive_dir,
        manifest,
    ) = _create_old_session_archive(
        db_path,
        tmp_path,
        monkeypatch,
    )

    profile = (
        read_historical_session_profile(
            manifest.session_date,
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
        profile.quote_metrics[
            "quote_count"
        ]
        == 1
    )
    assert (
        profile.quote_metrics[
            "underlying_count"
        ]
        == 1
    )
    assert (
        profile.archive_source_schema_version
        == 34
    )


def test_hot_archive_parity_is_value_exact(
    db_path,
    tmp_path,
    monkeypatch,
):
    (
        _,
        archive_dir,
        manifest,
    ) = _create_old_session_archive(
        db_path,
        tmp_path,
        monkeypatch,
    )

    progress: list[str] = []

    parity = verify_hot_archive_parity(
        manifest.session_date,
        db_path=db_path,
        archive_dir=archive_dir,
        progress=progress.append,
    )

    assert parity.passed is True
    assert all(
        item.matches
        for item in parity.tables
    )
    assert any(
        "option_quotes PASS"
        in message
        for message in progress
    )

    conn = sqlite3.connect(
        db_path
    )
    try:
        conn.execute(
            "DROP TRIGGER "
            "trg_option_quotes_no_update;"
        )
        conn.execute(
            """
            UPDATE option_quotes
            SET bid = bid + 0.01
            WHERE id = (
                SELECT MIN(id)
                FROM option_quotes
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    changed = verify_hot_archive_parity(
        manifest.session_date,
        db_path=db_path,
        archive_dir=archive_dir,
    )

    assert changed.passed is False

    option_quotes = next(
        item
        for item in changed.tables
        if item.table_name
        == "option_quotes"
    )

    assert option_quotes.hot.row_count == (
        option_quotes.archive.row_count
    )
    assert (
        option_quotes.hot.sha256
        != option_quotes.archive.sha256
    )


def _sha256_path(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as handle:
        while True:
            chunk = handle.read(
                1024 * 1024
            )
            if not chunk:
                break
            digest.update(
                chunk
            )

    return digest.hexdigest()


def _rewrite_archive_source_schema_version(
    *,
    archive_dir: Path,
    manifest,
    temp_dir: Path,
    source_schema_version: int,
) -> None:
    manifest_path = (
        archive_dir
        / manifest.manifest_filename
    )
    archive_path = (
        archive_dir
        / manifest.archive_filename
    )
    restored = (
        temp_dir
        / "compat-archive.db"
    )

    with gzip.open(
        archive_path,
        "rb",
    ) as src:
        with restored.open(
            "wb"
        ) as dst:
            shutil.copyfileobj(
                src,
                dst,
            )

    conn = sqlite3.connect(
        restored
    )
    try:
        conn.execute(
            """
            UPDATE archive_metadata
            SET value = ?
            WHERE key = 'source_schema_version';
            """,
            (
                str(
                    source_schema_version
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    uncompressed_sha = (
        _sha256_path(
            restored
        )
    )

    with restored.open(
        "rb"
    ) as src:
        with gzip.open(
            archive_path,
            "wb",
        ) as dst:
            shutil.copyfileobj(
                src,
                dst,
            )

    payload = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )
    payload[
        "source_schema_version"
    ] = source_schema_version
    payload[
        "uncompressed_size_bytes"
    ] = restored.stat().st_size
    payload[
        "compressed_size_bytes"
    ] = archive_path.stat().st_size
    payload[
        "uncompressed_sha256"
    ] = uncompressed_sha
    payload[
        "compressed_sha256"
    ] = _sha256_path(
        archive_path
    )

    manifest_path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_v33_archive_remains_readable_under_v34_runtime(
    db_path,
    tmp_path,
    monkeypatch,
):
    (
        _,
        archive_dir,
        manifest,
    ) = _create_old_session_archive(
        db_path,
        tmp_path,
        monkeypatch,
    )

    _rewrite_archive_source_schema_version(
        archive_dir=archive_dir,
        manifest=manifest,
        temp_dir=tmp_path,
        source_schema_version=33,
    )

    profile = (
        read_historical_session_profile(
            manifest.session_date,
            archive_dir=archive_dir,
        )
    )

    assert (
        profile.archive_source_schema_version
        == 33
    )

    parity = verify_hot_archive_parity(
        manifest.session_date,
        db_path=db_path,
        archive_dir=archive_dir,
    )

    assert parity.passed is True
    assert (
        parity.archive_source_schema_version
        == 33
    )


def test_cold_reader_rejects_manifest_internal_metadata_mismatch(
    db_path,
    tmp_path,
    monkeypatch,
):
    (
        _,
        archive_dir,
        manifest,
    ) = _create_old_session_archive(
        db_path,
        tmp_path,
        monkeypatch,
    )

    manifest_path = (
        archive_dir
        / manifest.manifest_filename
    )
    payload = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )
    payload[
        "source_schema_version"
    ] = 33
    manifest_path.write_text(
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
            "internal metadata mismatch "
            "for source_schema_version"
        ),
    ):
        read_historical_session_profile(
            manifest.session_date,
            archive_dir=archive_dir,
        )



def test_hot_parity_does_not_create_literal_uri_database(
    db_path,
    tmp_path,
    monkeypatch,
):
    (
        _,
        archive_dir,
        manifest,
    ) = _create_old_session_archive(
        db_path,
        tmp_path,
        monkeypatch,
    )

    before = {
        path.name
        for path in db_path.parent.iterdir()
    }

    result = verify_hot_archive_parity(
        manifest.session_date,
        db_path=db_path,
        archive_dir=archive_dir,
    )

    after = {
        path.name
        for path in db_path.parent.iterdir()
    }

    assert result.passed is True
    assert after == before
