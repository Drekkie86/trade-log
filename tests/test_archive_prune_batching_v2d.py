from __future__ import annotations

import sqlite3

import pytest

from src.operations.archive_pruning import (
    _delete_temp_id_set_in_batches,
)


def _seed() -> sqlite3.Connection:
    conn = sqlite3.connect(
        ":memory:",
        isolation_level=None,
    )

    conn.executescript(
        """
        CREATE TABLE target (
            id INTEGER PRIMARY KEY,
            payload TEXT NOT NULL
        );

        CREATE TEMP TABLE delete_ids (
            id INTEGER PRIMARY KEY
        ) WITHOUT ROWID;
        """
    )

    conn.executemany(
        """
        INSERT INTO target(
            id,
            payload
        )
        VALUES(?, ?);
        """,
        [
            (
                value,
                f"row-{value}",
            )
            for value
            in range(
                1,
                9,
            )
        ],
    )

    conn.executemany(
        """
        INSERT INTO delete_ids(id)
        VALUES(?);
        """,
        [
            (1,),
            (2,),
            (3,),
            (5,),
            (7,),
        ],
    )

    return conn


def test_chunked_delete_reports_exact_progress_and_is_transactional():
    conn = _seed()
    progress: list[str] = []

    try:
        conn.execute(
            "BEGIN IMMEDIATE;"
        )

        deleted = (
            _delete_temp_id_set_in_batches(
                conn,
                table_name="target",
                temp_table="delete_ids",
                batch_rows=2,
                progress=progress.append,
            )
        )

        assert deleted == 5

        assert conn.execute(
            """
            SELECT id
            FROM target
            ORDER BY id;
            """
        ).fetchall() == [
            (4,),
            (6,),
            (8,),
        ]

        assert any(
            "total=2/5"
            in message
            for message
            in progress
        )
        assert any(
            "total=4/5"
            in message
            for message
            in progress
        )
        assert any(
            "total=5/5"
            in message
            for message
            in progress
        )
        assert any(
            "complete rows=5 batches=3"
            in message
            for message
            in progress
        )

        conn.rollback()

        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM target;
            """
        ).fetchone()[0] == 8
    finally:
        conn.close()


def test_chunked_delete_can_roll_back_prior_batches_after_later_error():
    conn = _seed()

    try:
        conn.executescript(
            """
            CREATE TRIGGER fail_delete_five
            BEFORE DELETE ON target
            WHEN OLD.id = 5
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'synthetic later-batch failure'
                );
            END;
            """
        )

        conn.execute(
            "BEGIN IMMEDIATE;"
        )

        with pytest.raises(
            sqlite3.IntegrityError,
            match=(
                "synthetic later-batch failure"
            ),
        ):
            _delete_temp_id_set_in_batches(
                conn,
                table_name="target",
                temp_table="delete_ids",
                batch_rows=2,
            )

        # Batch 1 executed before batch 2 failed. The outer transaction
        # remains the atomicity boundary and can still restore everything.
        assert conn.in_transaction is True

        conn.rollback()

        assert conn.execute(
            """
            SELECT id
            FROM target
            ORDER BY id;
            """
        ).fetchall() == [
            (1,),
            (2,),
            (3,),
            (4,),
            (5,),
            (6,),
            (7,),
            (8,),
        ]
    finally:
        conn.close()


def test_chunked_delete_rejects_invalid_batch_size():
    conn = _seed()

    try:
        with pytest.raises(
            ValueError,
            match="batch_rows",
        ):
            _delete_temp_id_set_in_batches(
                conn,
                table_name="target",
                temp_table="delete_ids",
                batch_rows=0,
            )
    finally:
        conn.close()
