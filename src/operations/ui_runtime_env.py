from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from src.config import read_env_file


UI_RUNTIME_KEYS = (
    "CHRISTIANIA_DB_PATH",
    "CHRISTIANIA_BACKUP_DIR",
    "CHRISTIANIA_BURN_IN_LOG",
    "CHRISTIANIA_THETA_BASE_URL",
)

REQUIRED_UI_RUNTIME_KEYS = (
    "CHRISTIANIA_DB_PATH",
    "CHRISTIANIA_BACKUP_DIR",
)


def _validate_theta_base_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname
        not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "CHRISTIANIA_THETA_BASE_URL exposed to the UI "
            "must be an unauthenticated loopback HTTP endpoint."
        )


def select_ui_runtime_settings(
    values: dict[str, str],
) -> dict[str, str]:
    """Return the exact nonsecret runtime surface allowed into Streamlit."""
    selected: dict[str, str] = {}

    for key in UI_RUNTIME_KEYS:
        value = str(
            values.get(
                key,
                "",
            )
        ).strip()

        if not value:
            continue

        if "\n" in value or "\r" in value:
            raise ValueError(
                f"{key} contains a newline."
            )

        selected[key] = value

    missing = [
        key
        for key in REQUIRED_UI_RUNTIME_KEYS
        if key not in selected
    ]
    if missing:
        raise ValueError(
            "UI runtime environment is missing required setting(s): "
            + ", ".join(missing)
        )

    theta_url = selected.get(
        "CHRISTIANIA_THETA_BASE_URL"
    )
    if theta_url:
        _validate_theta_base_url(
            theta_url
        )

    return selected


def render_ui_runtime_env(
    values: dict[str, str],
) -> str:
    selected = (
        select_ui_runtime_settings(
            values
        )
    )

    return "".join(
        f"{key}={selected[key]}\n"
        for key in UI_RUNTIME_KEYS
        if key in selected
    )


def write_ui_runtime_env(
    *,
    source: str | Path,
    output: str | Path,
) -> Path:
    source_path = (
        Path(source)
        .expanduser()
    )
    output_path = (
        Path(output)
        .expanduser()
    )

    if not source_path.is_file():
        raise FileNotFoundError(
            "Christiania runtime environment "
            f"does not exist: {source_path}"
        )

    rendered = render_ui_runtime_env(
        read_env_file(
            source_path
        )
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = output_path.with_name(
        f".{output_path.name}.{os.getpid()}.tmp"
    )
    try:
        temp.write_text(
            rendered,
            encoding="utf-8",
        )
        os.chmod(
            temp,
            0o600,
        )
        os.replace(
            temp,
            output_path,
        )
    finally:
        if temp.exists():
            temp.unlink()

    return output_path
