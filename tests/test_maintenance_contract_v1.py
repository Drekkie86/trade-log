from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (
        ROOT
        / path
    ).read_text(
        encoding="utf-8",
    )


def _array_members(
    script: str,
    name: str,
) -> tuple[str, ...]:
    match = re.search(
        rf"{name}=\(\n(?P<body>.*?)\n\)",
        script,
        flags=re.DOTALL,
    )
    assert match is not None

    return tuple(
        value
        for value
        in re.findall(
            r'"([^"]+)"',
            match.group("body"),
        )
    )


def test_maintenance_quiescence_matches_release_contract():
    maintenance = _read(
        "deploy/christiania-maintenance"
    )
    receiver = _read(
        "deploy/receive_release.sh"
    )

    for array_name in (
        "QUIESCE_TIMER_UNITS",
        "QUIESCE_ONESHOT_SERVICES",
    ):
        assert (
            _array_members(
                maintenance,
                array_name,
            )
            == _array_members(
                receiver,
                array_name,
            )
        )


def test_maintenance_records_and_restores_public_edge():
    script = _read(
        "deploy/christiania-maintenance"
    )

    assert (
        'SECURE_EDGE_SERVICE="christiania-oauth2-proxy.service"'
        in script
    )

    record = script.index(
        "record_state"
    )
    stop_edge = script.index(
        'stop_optional_unit "${SECURE_EDGE_SERVICE}"'
    )
    restore = script.index(
        'Restoring ${SECURE_EDGE_SERVICE}'
    )

    assert record < stop_edge
    assert restore > record


def test_maintenance_state_is_retained_on_incomplete_restore():
    script = _read(
        "deploy/christiania-maintenance"
    )

    assert (
        "runtime restore incomplete; maintenance state retained"
        in script
    )

    assert (
        'rm -f "${STATE_FILE}"'
        in script
    )


def test_maintenance_keeps_theta_running():
    script = _read(
        "deploy/christiania-maintenance"
    )

    assert (
        "christiania-theta.service must remain active "
        "during database maintenance"
        in script
    )

    assert (
        "systemctl stop christiania-theta.service"
        not in script
    )


def test_maintenance_quiescence_fails_closed():
    script = _read(
        "deploy/christiania-maintenance"
    )

    assert (
        'systemctl stop "${unit}" || true'
        not in script
    )
    assert (
        'systemctl stop "${SECURE_EDGE_SERVICE}" || true'
        not in script
    )
    assert (
        "remained active after maintenance quiescence"
        in script
    )


def test_maintenance_state_acquisition_is_atomic():
    script = _read(
        "deploy/christiania-maintenance"
    )

    assert (
        'ln "${temp}" "${STATE_FILE}"'
        in script
    )
    assert (
        'mv "${temp}" "${STATE_FILE}"'
        not in script
    )
    assert (
        "maintenance state was claimed concurrently"
        in script
    )



def test_maintenance_refuses_to_interrupt_active_one_shot_work():
    script = _read(
        "deploy/christiania-maintenance"
    )

    assert (
        "one-shot maintenance service is already active; "
        "refusing to interrupt it"
        in script
    )

    one_shot_loop = (
        'for unit in "${QUIESCE_ONESHOT_SERVICES[@]}"; do'
    )

    start = script.index(
        one_shot_loop,
        script.index(
            "enter_maintenance()"
        ),
    )

    end = script.index(
        "# Stop the edge explicitly",
        start,
    )

    block = script[
        start:end
    ]

    assert (
        'unit_is_active "${unit}"'
        in block
    )
    assert (
        'stop_optional_unit "${unit}"'
        not in block
    )


def test_maintenance_rehearsal_is_non_sql_and_restores_exact_runtime_state():
    script = _read(
        "deploy/christiania-maintenance"
    )

    start = script.index(
        "rehearse_maintenance()"
    )
    end = script.index(
        "show_status()",
        start,
    )

    block = script[
        start:end
    ]

    assert (
        "enter_maintenance"
        in block
    )
    assert (
        "exit_maintenance"
        in block
    )
    assert (
        'diff -u "${before}" "${after}"'
        in block
    )
    assert (
        "MAINTENANCE_REHEARSAL_PASS"
        in block
    )

    for forbidden in (
        "sqlite3",
        "archive-prune",
        "VACUUM",
        "wal_checkpoint",
    ):
        assert forbidden not in block



def test_maintenance_rehearsal_installs_cleanup_before_entry():
    script = _read(
        "deploy/christiania-maintenance"
    )

    start = script.index(
        "rehearse_maintenance()"
    )
    end = script.index(
        "show_status()",
        start,
    )
    block = script[
        start:end
    ]

    exit_trap = block.index(
        "trap cleanup_rehearsal_files EXIT"
    )
    enter = block.index(
        "enter_maintenance"
    )

    assert exit_trap < enter
    assert (
        "trap - EXIT"
        in block
    )


def test_maintenance_checks_one_shots_twice_around_quiescence():
    script = _read(
        "deploy/christiania-maintenance"
    )

    start = script.index(
        "enter_maintenance()"
    )
    end = script.index(
        "exit_maintenance()",
        start,
    )
    block = script[
        start:end
    ]

    assert (
        block.count(
            'for unit in "${QUIESCE_ONESHOT_SERVICES[@]}"; do'
        )
        == 2
    )

    assert (
        "one-shot maintenance service became active "
        "while entering maintenance"
        in block
    )


def test_rehearsal_state_snapshot_includes_substate_and_enablement():
    script = _read(
        "deploy/christiania-maintenance"
    )

    state_start = script.index(
        "unit_state()"
    )
    state_end = script.index(
        "stop_optional_unit()",
        state_start,
    )
    block = script[
        state_start:state_end
    ]

    assert (
        "--property=SubState"
        in block
    )
    assert (
        "systemctl is-enabled"
        in block
    )
