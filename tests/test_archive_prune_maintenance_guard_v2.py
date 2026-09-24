from __future__ import annotations

from pathlib import Path

import pytest

from src.operations.archive_pruning import (
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
