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


def test_maintenance_rehearsal_contract():
    script = _read(
        "deploy/christiania-maintenance"
    )

    assert (
        "rehearse_maintenance()"
        in script
    )
    assert (
        "MAINTENANCE_QUIESCENCE_PASS"
        in script
    )
    assert (
        "MAINTENANCE_RESTORE_PASS"
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

    assert (
        "enter_maintenance"
        in rehearsal
    )
    assert (
        "exit_maintenance"
        in rehearsal
    )
    assert (
        "christiania-theta.service"
        in rehearsal
    )
    assert (
        "christiania-status"
        in rehearsal
    )


def test_maintenance_rehearsal_restores_on_failure():
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
        "trap rehearsal_restore ERR INT TERM HUP"
        in rehearsal
    )
    assert (
        'if [[ -f "${STATE_FILE}" ]]'
        in rehearsal
    )
    assert (
        "exit_maintenance"
        in rehearsal
    )
