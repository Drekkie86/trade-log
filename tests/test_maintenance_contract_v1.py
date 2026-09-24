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


def test_maintenance_rehearsal_uses_canonical_enter_exit_and_recovery():
    script = _read(
        "deploy/christiania-maintenance"
    )

    assert (
        "rehearse_maintenance()"
        in script
    )
    assert (
        "CHRISTIANIA_MAINTENANCE_REHEARSAL_START"
        in script
    )
    assert (
        "CHRISTIANIA_MAINTENANCE_REHEARSAL_QUIESCE_PASS"
        in script
    )
    assert (
        "CHRISTIANIA_MAINTENANCE_REHEARSAL_PASS"
        in script
    )

    rehearsal = script[
        script.index(
            "rehearse_maintenance()"
        ):
        script.index(
            "show_status()"
        )
    ]

    assert "enter_maintenance" in rehearsal
    assert "exit_maintenance" in rehearsal
    assert (
        "rehearsal_restore_on_failure"
        in rehearsal
    )
    assert (
        "trap rehearsal_restore_on_failure ERR INT TERM HUP"
        in rehearsal
    )


def test_maintenance_rehearsal_checks_theta_and_all_quiesced_classes():
    script = _read(
        "deploy/christiania-maintenance"
    )

    rehearsal = script[
        script.index(
            "rehearse_maintenance()"
        ):
        script.index(
            "show_status()"
        )
    ]

    assert (
        'for unit in "${DB_CONSUMER_SERVICES[@]}"; do'
        in rehearsal
    )
    assert (
        '"${QUIESCE_TIMER_UNITS[@]}" "${QUIESCE_ONESHOT_SERVICES[@]}"'
        in rehearsal
    )
    assert (
        'unit_is_active "${SECURE_EDGE_SERVICE}"'
        in rehearsal
    )
    assert (
        "christiania-theta.service"
        in rehearsal
    )



def test_maintenance_entry_proves_zero_database_holders():
    script = _read(
        "deploy/christiania-maintenance"
    )

    assert (
        "assert_no_database_holders()"
        in script
    )
    assert (
        "CHRISTIANIA_MAINTENANCE_DB_HOLDERS=0"
        in script
    )
    assert (
        "fuser"
        in script
    )
    assert (
        "lsof"
        in script
    )

    enter = script[
        script.index(
            "enter_maintenance()"
        ):
        script.index(
            "exit_maintenance()"
        )
    ]

    assert (
        "assert_no_database_holders"
        in enter
    )

    assert (
        enter.index(
            "assert_no_database_holders"
        )
        > enter.index(
            'systemctl stop "${unit}"'
        )
    )

    assert (
        "neither fuser nor lsof "
        "is installed"
        in script
    )


def test_maintenance_refuses_to_interrupt_active_oneshots():
    script = _read(
        "deploy/christiania-maintenance"
    )

    assert (
        "assert_optional_unit_inactive()"
        in script
    )
    assert (
        "maintenance refuses to interrupt active one-shot unit"
        in script
    )

    enter = script[
        script.index(
            "enter_maintenance()"
        ):
        script.index(
            "exit_maintenance()"
        )
    ]

    assert (
        'for unit in "${QUIESCE_ONESHOT_SERVICES[@]}"; do'
        in enter
    )
    assert (
        'assert_optional_unit_inactive "${unit}"'
        in enter
    )

    one_shot_loop = enter[
        enter.index(
            'for unit in "${QUIESCE_ONESHOT_SERVICES[@]}"; do'
        ):
        enter.index(
            "# Stop the edge explicitly"
        )
    ]

    assert (
        'stop_optional_unit "${unit}"'
        not in one_shot_loop
    )
