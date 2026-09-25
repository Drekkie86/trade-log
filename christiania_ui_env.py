from __future__ import annotations

import argparse

from src.operations.ui_runtime_env import (
    write_ui_runtime_env,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render Christiania's minimal nonsecret "
            "Streamlit runtime environment."
        )
    )
    parser.add_argument(
        "--source",
        required=True,
    )
    parser.add_argument(
        "--output",
        required=True,
    )
    args = parser.parse_args()

    path = write_ui_runtime_env(
        source=args.source,
        output=args.output,
    )
    print(path)


if __name__ == "__main__":
    main()
