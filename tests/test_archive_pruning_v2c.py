from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from src.database.repository import (
    create_market_snapshot,
)
from src.operations.archive_pruning import (
    DELETE_TRIGGER_BY_TABLE,
    plan_prune_session,
    prune_research_session,
)
from src.operations.remote_archive import (
    load_remote_archive_proof,
)
from src.operations.research_archive import (
    create_research_archive,
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
            'COHORT_PRUNE_TEST',
            'prune-test-prereg',
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
        "provider_contract_id": symbol,
        "option_symbol": symbol,
        "right": "C",
        "strike": strike,
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


def _seed_prunable_session(
    db_path: Path,
) -> int:
    conn = sqlite3.connect(
        db_path
    )
    try:
        old_run = _insert_completed_run(
            conn,
            session_date="2026-09-01",
            minute=0,
        )

        for index in range(50):
            day = (
                2
                + index // 25
            )
            minute = index % 25
            _insert_completed_run(
                conn,
                session_date=(
                    f"2026-09-{day:02d}"
                ),
                minute=minute,
            )

        conn.commit()
    finally:
        conn.close()

    create_market_snapshot(
        {
            "captured_at":
                "2026-09-01T14:00:00Z",
            "underlying": "TEST",
            "provider": "MASSIVE",
            "provider_snapshot_id":
                "prune-test-snapshot",
            "research_run_id": old_run,
            "us_session_date":
                "2026-09-01",
            "us_session_state":
                "INTRADAY",
            "underlying_price": 100.0,
            "underlying_source":
                "FETCHED",
            "underlying_at":
                "2026-09-01T14:00:00Z",
            "fx_to_eur": None,
            "fx_source": "UNKNOWN",
            "fx_at": None,
            "notes": "prune test",
        },
        [
            _quote(
                "TEST-C-100",
                100.0,
            ),
            _quote(
                "TEST-C-105",
                105.0,
            ),
        ],
        db_path=db_path,
    )

    conn = sqlite3.connect(
        db_path
    )
    try:
        quote_ids = [
            int(row[0])
            for row in conn.execute(
                """
                SELECT oq.id
                FROM option_quotes AS oq
                JOIN market_snapshots AS ms
                  ON ms.id = oq.snapshot_id
                WHERE ms.research_run_id = ?
                ORDER BY oq.id;
                """,
                (old_run,),
            ).fetchall()
        ]
        assert len(quote_ids) == 2

        conn.execute(
            """
            INSERT INTO research_selections(
                run_id,
                option_quote_id,
                selected_at,
                selection_rule,
                dte_stratum,
                delta_stratum,
                option_right,
                resolution_sequence,
                preregistration_hash,
                code_git_sha
            )
            VALUES(
                ?,
                ?,
                '2026-09-01T14:00:10Z',
                'PRUNE_TEST',
                'DTE_TEST',
                'DELTA_TEST',
                'C',
                1,
                'prune-test-prereg',
                'deadbeef'
            );
            """,
            (
                old_run,
                quote_ids[0],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return old_run


def _sha256_file(
    path: Path,
) -> str:
    digest = hashlib.sha256()
    digest.update(
        path.read_bytes()
    )
    return digest.hexdigest()


def _write_remote_proof(
    manifest_path: Path,
) -> Path:
    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    archive_name = str(
        manifest["archive_filename"]
    )
    session_date = str(
        manifest["session_date"]
    )
    suffix = ".manifest.json"
    proof_path = (
        manifest_path.with_name(
            manifest_path.name[
                :-len(suffix)
            ]
            + ".remote-proof.json"
        )
    )

    object_template = {
        "version_id": "test-version",
        "retention_mode":
            "COMPLIANCE",
        "retain_until":
            "2027-09-21T00:00:00Z",
    }

    payload = {
        "format_version": 1,
        "verified_at":
            "2026-09-21T00:00:00Z",
        "session_date":
            session_date,
        "local_manifest_filename":
            manifest_path.name,
        "local_manifest_sha256":
            _sha256_file(
                manifest_path
            ),
        "local_archive_filename":
            archive_name,
        "local_archive_compressed_sha256":
            manifest[
                "compressed_sha256"
            ],
        "local_archive_uncompressed_sha256":
            manifest[
                "uncompressed_sha256"
            ],
        "bucket":
            "christiania-test",
        "endpoint_url":
            "https://hel1.your-objectstorage.com",
        "region": "hel1",
        "prefix":
            "christiania/research-evidence/v1",
        "retention_days": 365,
        "archive_object": {
            **object_template,
            "key":
                f"archive/{archive_name}",
            "size_bytes":
                manifest[
                    "compressed_size_bytes"
                ],
            "sha256":
                manifest[
                    "compressed_sha256"
                ],
        },
        "manifest_object": {
            **object_template,
            "key":
                f"archive/{manifest_path.name}",
            "size_bytes":
                manifest_path.stat().st_size,
            "sha256":
                _sha256_file(
                    manifest_path
                ),
        },
        "receipt_object": {
            **object_template,
            "key":
                "archive/receipt.json",
            "size_bytes": 1,
            "sha256": "0" * 64,
        },
        "remote_restore_compressed_sha256":
            manifest[
                "compressed_sha256"
            ],
        "remote_restore_uncompressed_sha256":
            manifest[
                "uncompressed_sha256"
            ],
        "pruning_gate_state":
            "OFFHOST_IMMUTABLE_RESTORE_VERIFIED",
    }

    proof_path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return proof_path


def _prepare_archive_and_proof(
    db_path: Path,
    archive_dir: Path,
    monkeypatch,
):
    _seed_prunable_session(
        db_path
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
    proof_path = _write_remote_proof(
        manifest_path
    )
    return (
        manifest,
        manifest_path,
        proof_path,
    )


def test_prune_plan_preserves_referenced_quote(
    db_path,
    tmp_path,
    monkeypatch,
):
    archive_dir = (
        tmp_path
        / "archives"
    )
    (
        manifest,
        _,
        _,
    ) = _prepare_archive_and_proof(
        db_path,
        archive_dir,
        monkeypatch,
    )

    progress = []

    plan = plan_prune_session(
        manifest.session_date,
        db_path=db_path,
        archive_dir=archive_dir,
        progress=progress.append,
    )

    assert plan.apply_eligible is True
    assert plan.blockers == ()
    assert plan.outside_hot_window is True
    assert plan.remote_gate_state == (
        "OFFHOST_IMMUTABLE_RESTORE_VERIFIED"
    )
    assert any(
        "scope option_quotes complete"
        in message
        for message in progress
    )
    assert any(
        "references quotes -> surviving consumers complete"
        in message
        for message in progress
    )

    by_table = {
        item.table_name: item
        for item in plan.tables
    }

    quotes = by_table[
        "option_quotes"
    ]
    assert quotes.archived_rows == 2
    assert quotes.deletable_rows == 1
    assert quotes.preserved_rows == 1

    for table_name in (
        "local_surface_residual_v2_observations",
        "hypothesis_scanner_evaluations",
        "provider_model_observations",
        "provider_observation_availability",
        "listing_reference_contracts",
    ):
        assert (
            by_table[
                table_name
            ].archived_rows
            == 0
        )


def test_prune_apply_revalidates_archive_restores_triggers_and_fk(
    db_path,
    tmp_path,
    monkeypatch,
):
    archive_dir = (
        tmp_path
        / "archives"
    )
    (
        manifest,
        manifest_path,
        proof_path,
    ) = _prepare_archive_and_proof(
        db_path,
        archive_dir,
        monkeypatch,
    )

    proof = load_remote_archive_proof(
        proof_path
    )

    monkeypatch.setattr(
        "src.operations.archive_pruning.verify_remote_archive_proof",
        lambda path, **kwargs: proof,
    )

    progress = []

    receipt = prune_research_session(
        manifest.session_date,
        db_path=db_path,
        archive_dir=archive_dir,
        confirm_session=
            manifest.session_date,
        progress=progress.append,
    )

    assert any(
        "delete option_quotes complete"
        in message
        for message in progress
    )
    assert any(
        "transaction committed"
        in message
        for message in progress
    )
    assert any(
        "receipt written"
        in message
        for message in progress
    )

    assert (
        receipt.state
        == "REFERENCE_AWARE_HOT_PRUNE_COMMITTED"
    )
    assert (
        receipt.remote_gate_state
        == "OFFHOST_IMMUTABLE_RESTORE_VERIFIED"
    )
    assert (
        receipt.rows_deleted[
            "option_quotes"
        ]
        == 1
    )
    assert (
        receipt.rows_preserved[
            "option_quotes"
        ]
        == 1
    )
    assert (
        receipt.foreign_key_check
        == "ok"
    )

    conn = sqlite3.connect(
        db_path
    )
    try:
        remaining = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM option_quotes AS oq
                JOIN market_snapshots AS ms
                  ON ms.id = oq.snapshot_id
                WHERE ms.research_run_id = ?;
                """,
                (
                    manifest.run_ids[0],
                ),
            ).fetchone()[0]
        )
        assert remaining == 1

        fk = conn.execute(
            "PRAGMA foreign_key_check;"
        ).fetchall()
        assert fk == []

        for (
            table_name,
            trigger_name,
        ) in DELETE_TRIGGER_BY_TABLE.items():
            row = conn.execute(
                """
                SELECT tbl_name
                FROM sqlite_master
                WHERE type = 'trigger'
                  AND name = ?;
                """,
                (trigger_name,),
            ).fetchone()
            assert row is not None
            assert row[0] == table_name

        selected_quote_exists = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM research_selections AS rs
                JOIN option_quotes AS oq
                  ON oq.id = rs.option_quote_id
                WHERE rs.run_id = ?;
                """,
                (
                    manifest.run_ids[0],
                ),
            ).fetchone()[0]
        )
        assert (
            selected_quote_exists
            == 1
        )
    finally:
        conn.close()

    receipt_path = (
        archive_dir
        / manifest_path.name.replace(
            ".manifest.json",
            ".prune-receipt.json",
        )
    )
    assert receipt_path.is_file()


def test_prune_requires_matching_destructive_confirmation(
    db_path,
    tmp_path,
    monkeypatch,
):
    archive_dir = (
        tmp_path
        / "archives"
    )
    (
        manifest,
        _,
        _,
    ) = _prepare_archive_and_proof(
        db_path,
        archive_dir,
        monkeypatch,
    )

    try:
        prune_research_session(
            manifest.session_date,
            db_path=db_path,
            archive_dir=archive_dir,
            confirm_session="wrong-session",
        )
    except RuntimeError as exc:
        assert (
            "confirmation"
            in str(exc).lower()
        )
    else:
        raise AssertionError(
            "Expected destructive confirmation guard."
        )
