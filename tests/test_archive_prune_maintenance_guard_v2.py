from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlite3

from src.operations.archive_pruning import (
    _checkpoint_clean_wal,
    _prune_capacity_preflight,
    _require_managed_maintenance_state,
    _require_no_database_holders,
    plan_prune_session,
)


def _states(
    *,
    daemon: str = "inactive",
    app: str = "inactive",
    oauth: str = "inactive",
    theta: str = "active",
):
    values = {
        "christiania-daemon.service":
            daemon,
        "christiania-app.service":
            app,
        "christiania-oauth2-proxy.service":
            oauth,
        "christiania-theta.service":
            theta,
    }

    return lambda unit: values[
        unit
    ]


def test_production_prune_guard_requires_canonical_maintenance_state(
    tmp_path: Path,
):
    missing = (
        tmp_path
        / "maintenance.state"
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "requires the canonical "
            "Christiania maintenance state"
        ),
    ):
        _require_managed_maintenance_state(
            state_path=missing,
            service_state=_states(),
        )


@pytest.mark.parametrize(
    (
        "unit_state",
        "expected_unit",
    ),
    (
        (
            {
                "app": "active",
            },
            "christiania-app.service",
        ),
        (
            {
                "daemon": "active",
            },
            "christiania-daemon.service",
        ),
        (
            {
                "oauth": "active",
            },
            "christiania-oauth2-proxy.service",
        ),
    ),
)
def test_production_prune_guard_requires_runtime_quiescence(
    tmp_path: Path,
    unit_state,
    expected_unit,
):
    state_path = (
        tmp_path
        / "maintenance.state"
    )
    state_path.write_text(
        "ENTERED_AT=2026-09-25T00:00:00Z\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match=expected_unit.replace(
            ".",
            r"\.",
        ),
    ):
        _require_managed_maintenance_state(
            state_path=state_path,
            service_state=_states(
                **unit_state
            ),
        )


def test_production_prune_guard_requires_theta_to_remain_active(
    tmp_path: Path,
):
    state_path = (
        tmp_path
        / "maintenance.state"
    )
    state_path.write_text(
        "ENTERED_AT=2026-09-25T00:00:00Z\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="theta",
    ):
        _require_managed_maintenance_state(
            state_path=state_path,
            service_state=_states(
                theta="inactive",
            ),
        )


def test_production_prune_guard_accepts_valid_managed_maintenance(
    tmp_path: Path,
):
    state_path = (
        tmp_path
        / "maintenance.state"
    )
    state_path.write_text(
        "ENTERED_AT=2026-09-25T00:00:00Z\n",
        encoding="utf-8",
    )

    _require_managed_maintenance_state(
        state_path=state_path,
        service_state=_states(),
    )


def test_production_holder_guard_fails_on_any_db_wal_shm_holder(
    tmp_path: Path,
):
    database = (
        tmp_path
        / "trade_log.db"
    )
    database.touch()

    with pytest.raises(
        RuntimeError,
        match="zero DB/WAL/SHM holders",
    ):
        _require_no_database_holders(
            database,
            holder_probe=lambda path: (
                1234,
                5678,
            ),
        )


def test_production_holder_guard_accepts_zero_holders(
    tmp_path: Path,
):
    database = (
        tmp_path
        / "trade_log.db"
    )
    database.touch()

    _require_no_database_holders(
        database,
        holder_probe=lambda path: (),
    )


def test_production_prune_plan_is_refused_during_active_maintenance(
    tmp_path: Path,
    monkeypatch,
):
    state_path = (
        tmp_path
        / "maintenance.state"
    )
    state_path.write_text(
        "ENTERED_AT=2026-09-25T00:00:00Z\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.operations.archive_pruning.DEFAULT_MAINTENANCE_STATE_PATH",
        state_path,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "planning is refused while "
            "canonical maintenance is active"
        ),
    ):
        plan_prune_session(
            "2026-09-16",
        )


def test_checkpoint_clean_wal_requires_wal_mode(
    tmp_path: Path,
):
    database = (
        tmp_path
        / "not_wal.db"
    )

    conn = sqlite3.connect(
        database,
        isolation_level=None,
    )

    try:
        conn.execute(
            "CREATE TABLE probe(id INTEGER PRIMARY KEY);"
        )

        with pytest.raises(
            RuntimeError,
            match="requires SQLite WAL mode",
        ):
            _checkpoint_clean_wal(
                conn,
                database,
            )
    finally:
        conn.close()


def test_checkpoint_clean_wal_truncates_wal(
    tmp_path: Path,
):
    database = (
        tmp_path
        / "wal.db"
    )

    conn = sqlite3.connect(
        database,
        isolation_level=None,
    )

    progress: list[str] = []

    try:
        assert (
            str(
                conn.execute(
                    "PRAGMA journal_mode = WAL;"
                ).fetchone()[0]
            ).lower()
            == "wal"
        )

        conn.execute(
            "CREATE TABLE probe(id INTEGER PRIMARY KEY, payload TEXT);"
        )

        conn.executemany(
            "INSERT INTO probe(payload) VALUES(?);",
            [
                (
                    "x" * 1000,
                )
                for _ in range(
                    100
                )
            ],
        )

        _checkpoint_clean_wal(
            conn,
            database,
            progress=progress.append,
        )

        wal_path = Path(
            str(database)
            + "-wal"
        )

        assert (
            not wal_path.exists()
            or wal_path.stat().st_size
            == 0
        )

        assert any(
            "WAL checkpoint PASS"
            in message
            for message
            in progress
        )
    finally:
        conn.close()


def test_prune_capacity_preflight_fails_closed_when_headroom_is_short(
    tmp_path: Path,
):
    database = (
        tmp_path
        / "capacity.db"
    )

    conn = sqlite3.connect(
        database
    )

    try:
        conn.execute(
            "CREATE TABLE probe(id INTEGER PRIMARY KEY);"
        )
        conn.commit()

        with pytest.raises(
            RuntimeError,
            match="Insufficient filesystem headroom",
        ):
            _prune_capacity_preflight(
                conn,
                database,
                enforce=True,
                disk_usage=lambda path: (
                    SimpleNamespace(
                        total=1_000,
                        free=499,
                    )
                ),
                required_free_bytes=lambda **kwargs: 500,
            )
    finally:
        conn.close()


def test_prune_capacity_preflight_records_exact_evidence(
    tmp_path: Path,
):
    database = (
        tmp_path
        / "capacity_pass.db"
    )

    conn = sqlite3.connect(
        database
    )
    progress: list[str] = []

    try:
        conn.execute(
            "CREATE TABLE probe(id INTEGER PRIMARY KEY);"
        )
        conn.commit()

        (
            logical_bytes,
            free_bytes,
            required_bytes,
        ) = _prune_capacity_preflight(
            conn,
            database,
            enforce=True,
            disk_usage=lambda path: (
                SimpleNamespace(
                    total=10_000,
                    free=7_000,
                )
            ),
            required_free_bytes=lambda **kwargs: 6_000,
            progress=progress.append,
        )

        assert logical_bytes > 0
        assert free_bytes == 7_000
        assert required_bytes == 6_000

        assert any(
            "capacity PASS"
            in message
            for message
            in progress
        )
    finally:
        conn.close()
