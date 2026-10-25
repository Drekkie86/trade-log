from __future__ import annotations

import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

ENV_FILE = PROJECT_ROOT / ".env"


def _local_env_fallback_disabled() -> bool:
    raw = str(
        os.environ.get(
            "CHRISTIANIA_DISABLE_LOCAL_ENV_FALLBACK",
            "",
        )
    ).strip().lower()
    return raw in {
        "1",
        "true",
        "yes",
        "on",
    }


def read_env_file(path: str | Path) -> dict[str, str]:
    """Parse Christiania KEY=VALUE configuration without shell evaluation."""

    env_path = Path(path).expanduser()
    settings: dict[str, str] = {}

    if not env_path.exists():
        return settings

    for raw_line in env_path.read_text(
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


def _read_local_settings() -> dict[str, str]:
    return read_env_file(ENV_FILE)


def load_runtime_env_file(
    path: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, str]:
    """Load an explicit deployment env file without invoking a shell."""

    values = read_env_file(path)
    for key, value in values.items():
        if overwrite or key not in os.environ:
            os.environ[key] = value
    return values


def load_local_env() -> None:
    """
    Load local Christiania configuration.

    The .env file is Christiania's authoritative
    local persistent configuration.

    This deliberately replaces stale values left
    in the current PowerShell environment.
    """

    if _local_env_fallback_disabled():
        return

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

    if _local_env_fallback_disabled():
        return None

    return _read_local_settings().get(name)


@contextmanager
def _settings_file_lock(path: str | Path | None = None):
    """Serialize token read, refresh and write using one interprocess lock."""
    target = Path(path) if path is not None else ENV_FILE
    lock_path = target.with_name(target.name + ".lock")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(lock_fd, "r+b") as lock:
        if os.name == "nt":
            import msvcrt

            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b"0")
                lock.flush()
            locked = False
            for _ in range(100):
                try:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    time.sleep(0.1)
            if not locked:
                raise TimeoutError("Timed out waiting for local settings lock.")
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def set_local_settings(values: dict[str, str]) -> None:
    """Atomically replace the local config under an interprocess lock."""
    with _settings_file_lock():
        _set_local_settings_unlocked(values)


def _set_local_settings_unlocked(
    values: dict[str, str],
    path: str | Path | None = None,
) -> None:
    """
    Persist local Christiania settings to .env.

    Existing unrelated settings and comments
    are preserved.
    """

    target = Path(path) if path is not None else ENV_FILE
    existing_lines: list[str] = []

    if target.exists():
        existing_lines = (
            target.read_text(
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

    # Same-directory temp + fsync + atomic replace. Restrict new files to
    # owner-only even when the containing directory has wider permissions.
    fd, temp_name = tempfile.mkstemp(
        prefix=".christiania_env_", dir=str(target.parent)
    )
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.write("\n".join(output_lines) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_name, target)
        if os.name != "nt":
            os.chmod(target, 0o600)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    # Dedicated broker stores are read directly when needed; avoid copying
    # their secrets into the process-wide environment during rotation.
    if target == ENV_FILE:
        for key, value in values.items():
            os.environ[key] = value