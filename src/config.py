from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

ENV_FILE = PROJECT_ROOT / ".env"


def _read_local_settings() -> dict[str, str]:
    settings: dict[str, str] = {}

    if not ENV_FILE.exists():
        return settings

    for raw_line in ENV_FILE.read_text(
        encoding="utf-8"
    ).splitlines():

        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        key = key.strip()
        value = value.strip()

        if not key:
            continue

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        settings[key] = value

    return settings


def load_local_env() -> None:
    """
    Load local Christiania configuration.

    The .env file is Christiania's authoritative
    local persistent configuration.

    This deliberately replaces stale values left
    in the current PowerShell environment.
    """

    for key, value in (
        _read_local_settings().items()
    ):
        os.environ[key] = value


def get_required_setting(name: str) -> str:
    load_local_env()

    value = os.environ.get(name)

    if not value:
        raise RuntimeError(
            f"Required Christiania setting "
            f"{name} is not configured."
        )

    return value


def get_optional_setting(
    name: str,
) -> str | None:
    load_local_env()

    return os.environ.get(name)


def get_runtime_setting(
    name: str,
) -> str | None:
    """
    Resolve deployment/runtime configuration.

    Explicit process environment wins. If it is absent,
    fall back to the local .env file without mutating the
    current process environment.

    This is intended for host/runtime settings such as
    CHRISTIANIA_DB_PATH and CHRISTIANIA_BACKUP_DIR.
    """

    value = os.environ.get(name)

    if value:
        return value

    return _read_local_settings().get(name)


def set_local_settings(
    values: dict[str, str],
) -> None:
    """
    Persist local Christiania settings to .env.

    Existing unrelated settings and comments
    are preserved.
    """

    existing_lines: list[str] = []

    if ENV_FILE.exists():
        existing_lines = (
            ENV_FILE.read_text(
                encoding="utf-8"
            ).splitlines()
        )

    remaining = dict(values)

    output_lines: list[str] = []

    for raw_line in existing_lines:
        stripped = raw_line.strip()

        if (
            not stripped
            or stripped.startswith("#")
            or "=" not in stripped
        ):
            output_lines.append(
                raw_line
            )
            continue

        key, _ = stripped.split(
            "=",
            1,
        )

        key = key.strip()

        if key in remaining:
            output_lines.append(
                f"{key}={remaining.pop(key)}"
            )
        else:
            output_lines.append(
                raw_line
            )

    for key, value in (
        remaining.items()
    ):
        output_lines.append(
            f"{key}={value}"
        )

    ENV_FILE.write_text(
        "\n".join(output_lines) + "\n",
        encoding="utf-8",
    )

    for key, value in values.items():
        os.environ[key] = value