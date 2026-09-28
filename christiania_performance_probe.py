from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from src.config import load_runtime_env_file
from src.dashboard.read_model import load_command_deck
from src.database.repository import resolve_db_path
from src.operations.sqlite_runtime import open_readonly_connection


PAGES = (
    "Dashboard",
    "Decision Desk",
    "Research Runs",
    "Calibration",
    "Observations",
    "Shadow Lab",
    "Quant Models",
    "Storm Cellar / 0DTE Lab",
    "Ops",
)


def _sqlite_metadata(path: Path) -> dict[str, object]:
    connection = open_readonly_connection(path)
    try:
        page_size = int(connection.execute("PRAGMA page_size;").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count;").fetchone()[0])
        freelist_count = int(
            connection.execute("PRAGMA freelist_count;").fetchone()[0]
        )
        journal_mode = str(
            connection.execute("PRAGMA journal_mode;").fetchone()[0]
        ).lower()
        stat1_exists = bool(
            connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'sqlite_stat1'
                LIMIT 1;
                """
            ).fetchone()
        )
    finally:
        connection.close()

    wal_path = Path(str(path) + "-wal")
    shm_path = Path(str(path) + "-shm")

    return {
        "path": str(path),
        "database_bytes": path.stat().st_size if path.exists() else 0,
        "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
        "shm_bytes": shm_path.stat().st_size if shm_path.exists() else 0,
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist_count,
        "logical_bytes": page_size * page_count,
        "journal_mode": journal_mode,
        "sqlite_stat1_exists": stat1_exists,
    }


def _measure_page(
    path: Path,
    page: str,
    *,
    warmups: int,
    runs: int,
) -> dict[str, object]:
    for _ in range(warmups):
        warm = load_command_deck(
            path,
            include_provider_health=False,
            deep_integrity=False,
            page=page,
        )
        if warm.get("ready") is not True:
            raise RuntimeError(
                f"{page} warm-up failed: {warm.get('reason')}"
            )

    wall_ms: list[float] = []
    internal: list[dict[str, float]] = []

    for _ in range(runs):
        started = time.perf_counter()
        deck = load_command_deck(
            path,
            include_provider_health=False,
            deep_integrity=False,
            page=page,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        if deck.get("ready") is not True:
            raise RuntimeError(
                f"{page} measurement failed: {deck.get('reason')}"
            )

        wall_ms.append(elapsed_ms)
        internal.append(
            {
                key: float(value)
                for key, value in (
                    deck.get("read_model_timings_ms") or {}
                ).items()
            }
        )

    timing_keys = sorted(
        {
            key
            for sample in internal
            for key in sample
        }
    )
    section_medians = {
        key: round(
            statistics.median(
                sample[key]
                for sample in internal
                if key in sample
            ),
            3,
        )
        for key in timing_keys
    }

    return {
        "page": page,
        "warmups": warmups,
        "runs": runs,
        "wall_ms": {
            "min": round(min(wall_ms), 3),
            "median": round(statistics.median(wall_ms), 3),
            "max": round(max(wall_ms), 3),
        },
        "section_median_ms": section_medians,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Christiania page-read performance probe. "
            "It never performs provider writes, checkpoints, migrations, "
            "ANALYZE, VACUUM, or integrity scans."
        )
    )
    parser.add_argument(
        "--env-file",
        help=(
            "Optional deployed Christiania env file to load before resolving "
            "the database path. Values are parsed without shell evaluation."
        ),
    )
    parser.add_argument(
        "--db",
        help=(
            "Database path. Defaults to CHRISTIANIA_DB_PATH / "
            "Christiania runtime resolution."
        ),
    )
    parser.add_argument(
        "--page",
        action="append",
        choices=PAGES,
        help="Page to measure. Repeatable. Defaults to all pages.",
    )
    parser.add_argument(
        "--warmups",
        type=int,
        default=1,
        help="Warm-up reads per page before measurement (default: 1).",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Measured reads per page (default: 3).",
    )
    args = parser.parse_args()

    if args.warmups < 0:
        parser.error("--warmups must be >= 0")
    if args.runs < 1:
        parser.error("--runs must be >= 1")

    if args.env_file:
        values = load_runtime_env_file(
            args.env_file,
            overwrite=False,
        )
        if not values:
            raise SystemExit(
                f"Environment file missing or empty: {args.env_file}"
            )

    path = resolve_db_path(args.db)
    pages = tuple(args.page or PAGES)

    payload = {
        "probe_version": 1,
        "read_only": True,
        "database": _sqlite_metadata(path),
        "pages": [
            _measure_page(
                path,
                page,
                warmups=args.warmups,
                runs=args.runs,
            )
            for page in pages
        ],
    }

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
