"""Opt-in export of Saxo-only credentials to an owner-only transfer file.

The user's authenticated desktop is the *source*; never copy the whole
Christiania .env (which may contain unrelated secrets). Nothing is sent
or logged by this tool. Operator transfers through authenticated SSH.
"""
from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

from src.config import ENV_FILE, PROJECT_ROOT, read_env_file
from src.providers.saxo_auth import _token_is_usable

FIELDS = (
    "SAXO_LIVE_APP_KEY", "SAXO_LIVE_CODE_VERIFIER",
    "SAXO_LIVE_ACCESS_TOKEN", "SAXO_LIVE_ACCESS_EXPIRES_AT",
    "SAXO_LIVE_REFRESH_TOKEN", "SAXO_LIVE_REFRESH_EXPIRES_AT",
)


def export_saxo_credentials(destination: str | Path, *,
                            source: str | Path = ENV_FILE) -> Path:
    destination = Path(destination).expanduser()
    if not destination.is_absolute():
        raise ValueError("Choose an absolute destination outside the repository.")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError("Transfer destination directory does not exist or is unsafe.")
    if destination.is_symlink() or destination.exists():
        raise FileExistsError("Refusing to overwrite an existing Saxo export.")
    if destination.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError("Do not export broker credentials into the Git checkout.")

    src = read_env_file(source)
    missing = [key for key in FIELDS if not src.get(key)]
    if missing:
        raise ValueError(
            "The local Saxo OAuth setup is incomplete; "
            "complete a fresh interactive Saxo LIVE login."
        )

    if not _token_is_usable(src["SAXO_LIVE_REFRESH_EXPIRES_AT"]):
        raise ValueError(
            "Saxo refresh token is expired; authorize a fresh LIVE login "
            "before exporting to the server."
        )

    # O_EXCL prevents a competing process from replacing another file.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            for key in FIELDS:
                out.write(f"{key}={src[key]}\n")
            out.flush()
            os.fsync(out.fileno())
        if os.name != "nt":
            os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Saxo LIVE OAuth settings only.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export_saxo_credentials(args.output)
    print("Saxo-only secure transfer file created. No credentials were printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
