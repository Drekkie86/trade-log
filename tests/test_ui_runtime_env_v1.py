from __future__ import annotations

from pathlib import Path

import pytest

from src.operations.ui_runtime_env import (
    UI_RUNTIME_KEYS,
    render_ui_runtime_env,
    select_ui_runtime_settings,
    write_ui_runtime_env,
)


def _full_runtime() -> dict[str, str]:
    return {
        "CHRISTIANIA_DB_PATH":
            "/var/lib/christiania/data/trade_log.db",
        "CHRISTIANIA_BACKUP_DIR":
            "/var/lib/christiania/backups",
        "CHRISTIANIA_BURN_IN_LOG":
            "/var/lib/christiania/audit/v1_burn_in.jsonl",
        "CHRISTIANIA_THETA_BASE_URL":
            "http://127.0.0.1:25503/v3",
        "MASSIVE_API_KEY":
            "massive-secret",
        "THETADATA_API_KEY":
            "theta-secret",
        "CHRISTIANIA_EVIDENCE_REMOTE_ACCESS_KEY_ID":
            "archive-access",
        "CHRISTIANIA_EVIDENCE_REMOTE_SECRET_ACCESS_KEY":
            "archive-secret",
        "CHRISTIANIA_ALERT_WEBHOOK_URL":
            "https://secret.invalid/webhook",
    }


def test_ui_runtime_environment_is_an_exact_allowlist():
    selected = (
        select_ui_runtime_settings(
            _full_runtime()
        )
    )

    assert tuple(
        selected
    ) == UI_RUNTIME_KEYS
    assert "MASSIVE_API_KEY" not in selected
    assert "THETADATA_API_KEY" not in selected
    assert (
        "CHRISTIANIA_EVIDENCE_REMOTE_SECRET_ACCESS_KEY"
        not in selected
    )
    assert (
        "CHRISTIANIA_ALERT_WEBHOOK_URL"
        not in selected
    )


def test_ui_runtime_theta_endpoint_must_be_loopback():
    values = _full_runtime()
    values[
        "CHRISTIANIA_THETA_BASE_URL"
    ] = "https://user:pass@theta.example.com/v3"

    with pytest.raises(
        ValueError,
        match="loopback",
    ):
        select_ui_runtime_settings(
            values
        )


def test_ui_runtime_requires_database_and_backup_paths():
    values = _full_runtime()
    values.pop(
        "CHRISTIANIA_DB_PATH"
    )

    with pytest.raises(
        ValueError,
        match="CHRISTIANIA_DB_PATH",
    ):
        render_ui_runtime_env(
            values
        )


def test_ui_runtime_writer_does_not_copy_secrets(
    tmp_path: Path,
):
    source = (
        tmp_path
        / "christiania.env"
    )
    output = (
        tmp_path
        / "christiania-ui.env"
    )

    source.write_text(
        "".join(
            f"{key}={value}\n"
            for key, value
            in _full_runtime().items()
        ),
        encoding="utf-8",
    )

    write_ui_runtime_env(
        source=source,
        output=output,
    )

    rendered = output.read_text(
        encoding="utf-8"
    )
    assert "massive-secret" not in rendered
    assert "theta-secret" not in rendered
    assert "archive-secret" not in rendered
    assert "secret.invalid" not in rendered
    assert (
        "CHRISTIANIA_DB_PATH="
        in rendered
    )
