from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _run(
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(
            env
        )

    return subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "christiania_ops.py"
            ),
            *args,
        ],
        cwd=ROOT,
        env=process_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def test_storage_bundle_cli_commands_are_exposed():
    completed = _run(
        "--help"
    )

    assert completed.returncode == 0

    for command in (
        "archive-profile",
        "archive-parity",
        "archive-prune-index-audit",
        "archive-prune-plan",
        "archive-prune-session",
    ):
        assert (
            command
            in completed.stdout
        )


def test_prune_index_audit_cli_passes_fully_migrated_database(
    db_path,
):
    completed = _run(
        "archive-prune-index-audit",
        "--json",
        env={
            "CHRISTIANIA_DB_PATH":
                str(db_path),
        },
    )

    assert (
        completed.returncode
        == 0
    ), (
        completed.stdout
        + completed.stderr
    )

    payload = json.loads(
        completed.stdout
    )

    assert payload[
        "passed"
    ] is True

    checks = payload[
        "checks"
    ]

    assert checks
    assert all(
        item[
            "supported"
        ]
        is True
        for item in checks
    )

    labels = {
        item[
            "label"
        ]
        for item in checks
    }

    assert (
        "shadow_candidates"
        "(reference_contract_id)"
        "->listing_reference_contracts"
        in labels
    )
    assert (
        "hypothesis_scanner_evaluations"
        "(option_quote_id)"
        "->option_quotes"
        in labels
    )
