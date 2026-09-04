from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Launch the Christiania V1 web command deck."
        )
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8501,
    )
    args = parser.parse_args()

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ROOT / "app.py"),
        "--server.address",
        args.host,
        "--server.port",
        str(args.port),
    ]

    raise SystemExit(
        subprocess.call(
            command,
            cwd=ROOT,
        )
    )


if __name__ == "__main__":
    main()
