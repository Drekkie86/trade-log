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
        'systemctl stop "\${SECURE_EDGE_SERVICE}"'
    )
    restore = script.index(
        'Restoring \${SECURE_EDGE_SERVICE}'
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
        'rm -f "\${STATE_FILE}"'
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
