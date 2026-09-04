from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.config import get_runtime_setting


def theta_command() -> list[str]:
    configured = get_runtime_setting(
        "CHRISTIANIA_THETA_JAR"
    )

    if not configured:
        raise RuntimeError(
            "CHRISTIANIA_THETA_JAR is not configured."
        )

    jar = Path(configured).expanduser()

    if not jar.is_file():
        raise RuntimeError(
            f"Theta Terminal jar not found: {jar}"
        )

    java = shutil.which("java")

    if java is None:
        raise RuntimeError(
            "Java executable was not found on PATH."
        )

    return [
        java,
        "-jar",
        str(jar),
    ]


def main() -> int:
    command = theta_command()

    print(
        "Starting Theta Terminal for Christiania."
    )
    print(
        "No undocumented Theta Terminal flags are used."
    )

    return subprocess.call(
        command
    )


if __name__ == "__main__":
    raise SystemExit(main())
