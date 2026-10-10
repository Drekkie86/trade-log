from __future__ import annotations

import argparse
import json
import pickle
import statistics
import tempfile
import time
from pathlib import Path

import src.dashboard.read_model as dashboard_read_model

from src.config import load_runtime_env_file
from src.dashboard.read_model import (
    export_prospective_summary_seed,
    load_command_deck,
)
from src.database.repository import resolve_db_path
from src.operations.sqlite_runtime import open_readonly_connection
from src.operations.release_manifest import build_release_manifest


OPS_RELEASE_MANIFEST_BUDGET_MS = 1000.0


def _measure_ops_release_manifest(path: Path, *, runs: int = 3) -> dict[str, object]:
    """Production-size read-only Ops Release manifest measurement.

    This covers the expensive path that normal read-model page benchmarks miss.
    Full integrity checks belong solely to explicit readiness and release gates.
    """
    if runs < 1:
        raise ValueError("runs must be positive")
    timings: list[float] = []
    for i in range(runs + 1):
        started = time.perf_counter()
        manifest = build_release_manifest(path, deep_integrity=False)
        elapsed = (time.perf_counter() - started) * 1000.0
        if manifest.schema_version != manifest.expected_schema_version:
            raise RuntimeError("Ops Release manifest schema does not match.")
        if i:
            timings.append(elapsed)
    median_ms = round(statistics.median(timings), 3)
    return {
        "median_ms": median_ms,
        "budget_ms": OPS_RELEASE_MANIFEST_BUDGET_MS,
        "within_budget": median_ms <= OPS_RELEASE_MANIFEST_BUDGET_MS,
        "deep_integrity": False,
        "runs": runs,
    }


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
        cache_size = int(
            connection.execute("PRAGMA cache_size;").fetchone()[0]
        )
        mmap_size = int(
            connection.execute("PRAGMA mmap_size;").fetchone()[0]
        )
        wal_autocheckpoint = int(
            connection.execute("PRAGMA wal_autocheckpoint;").fetchone()[0]
        )
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
        "cache_size": cache_size,
        "mmap_size": mmap_size,
        "wal_autocheckpoint": wal_autocheckpoint,
        "sqlite_stat1_exists": stat1_exists,
    }


def _runtime_activity_metadata(path: Path) -> dict[str, object]:
    connection = open_readonly_connection(path)
    try:
        latest_iteration_row = connection.execute(
            """
            SELECT
                id,
                scheduled_for,
                started_at,
                completed_at,
                status,
                research_run_id
            FROM research_daemon_iterations
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()
        daemon_lock_row = connection.execute(
            """
            SELECT
                owner_token,
                acquired_at,
                heartbeat_at
            FROM research_daemon_lock
            WHERE singleton_id = 1;
            """
        ).fetchone()
    finally:
        connection.close()

    latest_iteration = (
        None
        if latest_iteration_row is None
        else dict(latest_iteration_row)
    )
    daemon_lock = (
        None
        if daemon_lock_row is None
        else dict(daemon_lock_row)
    )
    cycle_active = bool(
        latest_iteration
        and latest_iteration.get("started_at")
        and not latest_iteration.get("completed_at")
    )

    return {
        "cycle_active": cycle_active,
        "latest_iteration": latest_iteration,
        "daemon_lock": daemon_lock,
    }


def _measure_page(
    path: Path,
    page: str | None,
    *,
    warmups: int,
    runs: int,
) -> dict[str, object]:
    cold_started = time.perf_counter()
    cold_deck = load_command_deck(
        path,
        include_provider_health=False,
        deep_integrity=False,
        page=page,
        allow_persisted_prospective_seed=False,
    )
    cold_wall_ms = (time.perf_counter() - cold_started) * 1000.0
    if cold_deck.get("ready") is not True:
        raise RuntimeError(
            f"{page} cold measurement failed: {cold_deck.get('reason')}"
        )

    for _ in range(warmups):
        warm = load_command_deck(
            path,
            include_provider_health=False,
            deep_integrity=False,
            page=page,
            allow_persisted_prospective_seed=False,
        )
        if warm.get("ready") is not True:
            raise RuntimeError(
                f"{page} warm-up failed: {warm.get('reason')}"
            )

    wall_ms: list[float] = []
    internal: list[dict[str, float]] = []
    last_deck: dict[str, object] | None = None

    for _ in range(runs):
        started = time.perf_counter()
        deck = load_command_deck(
            path,
            include_provider_health=False,
            deep_integrity=False,
            page=page,
            allow_persisted_prospective_seed=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        if deck.get("ready") is not True:
            raise RuntimeError(
                f"{page} measurement failed: {deck.get('reason')}"
            )

        wall_ms.append(elapsed_ms)
        last_deck = deck
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

    if last_deck is None:
        raise RuntimeError("No page measurement was produced.")

    pickle_started = time.perf_counter()
    cached_payload = pickle.dumps(
        last_deck,
        protocol=pickle.HIGHEST_PROTOCOL,
    )
    pickle_dump_ms = (
        time.perf_counter() - pickle_started
    ) * 1000.0

    pickle_load_samples = []
    for _ in range(3):
        pickle_started = time.perf_counter()
        pickle.loads(cached_payload)
        pickle_load_samples.append(
            (time.perf_counter() - pickle_started) * 1000.0
        )

    return {
        "page": page or "FULL",
        "warmups": warmups,
        "runs": runs,
        "cold_wall_ms": round(cold_wall_ms, 3),
        "cache_payload_bytes": len(cached_payload),
        "pickle_dump_ms": round(pickle_dump_ms, 3),
        "pickle_load_ms": {
            "median": round(statistics.median(pickle_load_samples), 3),
            "max": round(max(pickle_load_samples), 3),
        },
        "wall_ms": {
            "min": round(min(wall_ms), 3),
            "median": round(statistics.median(wall_ms), 3),
            "max": round(max(wall_ms), 3),
        },
        "section_median_ms": section_medians,
    }


def _measure_seeded_dashboard_cold(
    path: Path,
    *,
    release_commit: str,
    seed: dict[str, object],
) -> dict[str, object]:
    """Measure a fresh-process-equivalent Dashboard read from persisted seed."""
    history_rebuild_attempted = False
    original_range_part = dashboard_read_model._prospective_range_part
    original_commit_path = dashboard_read_model._DEPLOYED_COMMIT_PATH
    original_probe_dir = dashboard_read_model._PERFORMANCE_PROBE_DIR

    def traced_range_part(conn, **kwargs):
        nonlocal history_rebuild_attempted
        if (
            kwargs.get("include_ids") is None
            and kwargs.get("low_exclusive") in (None, 0)
        ):
            history_rebuild_attempted = True
        return original_range_part(conn, **kwargs)

    with tempfile.TemporaryDirectory(prefix="christiania-seeded-cold-") as temp_root:
        root = Path(temp_root)
        marker = root / "DEPLOYED_COMMIT"
        report_dir = root / "performance-probes"
        report_dir.mkdir()
        marker.write_text(release_commit + "\n", encoding="utf-8")
        report = report_dir / f"{release_commit}-seeded-cold.json"
        report.write_text(
            json.dumps(
                {
                    "probe_version": 5,
                    "release_commit": release_commit,
                    "read_only": True,
                    "deployment_lock_held": True,
                    "prospective_cache_seed": seed,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            dashboard_read_model._clear_prospective_summary_cache()
            dashboard_read_model._DEPLOYED_COMMIT_PATH = marker
            dashboard_read_model._PERFORMANCE_PROBE_DIR = report_dir
            dashboard_read_model._prospective_range_part = traced_range_part

            started = time.perf_counter()
            deck = load_command_deck(
                path,
                include_provider_health=False,
                deep_integrity=False,
                page="Dashboard",
                allow_persisted_prospective_seed=True,
            )
            wall_ms = (time.perf_counter() - started) * 1000.0
        finally:
            dashboard_read_model._prospective_range_part = original_range_part
            dashboard_read_model._DEPLOYED_COMMIT_PATH = original_commit_path
            dashboard_read_model._PERFORMANCE_PROBE_DIR = original_probe_dir
            dashboard_read_model._clear_prospective_summary_cache()

    if deck.get("ready") is not True:
        raise RuntimeError(
            "Seeded Dashboard cold measurement failed: "
            f"{deck.get('reason')}"
        )

    return {
        "wall_ms": round(wall_ms, 3),
        "history_rebuild_avoided": not history_rebuild_attempted,
        "section_ms": {
            key: float(value)
            for key, value in (
                deck.get("read_model_timings_ms") or {}
            ).items()
        },
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
        "--release-commit",
        help=(
            "Optional 40-character release SHA to bind this production "
            "measurement to an exact candidate."
        ),
    )
    parser.add_argument(
        "--deployment-lock-held",
        action="store_true",
        help=(
            "Assert that the caller holds the Christiania deployment lock "
            "for the complete measurement window."
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
        "--include-full",
        action="store_true",
        help=(
            "Also measure the legacy full command deck on the same database "
            "as a relative production-scale baseline."
        ),
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
    if (
        args.release_commit is not None
        and (
            len(args.release_commit) != 40
            or any(
                value not in "0123456789abcdefABCDEF"
                for value in args.release_commit
            )
        )
    ):
        parser.error("--release-commit must be a 40-character hexadecimal SHA")

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
    pages: tuple[str | None, ...] = tuple(args.page or PAGES)
    if args.include_full:
        pages = (*pages, None)

    database_before = _sqlite_metadata(path)
    runtime_activity_before = _runtime_activity_metadata(path)
    measurements = [
        _measure_page(
            path,
            page,
            warmups=args.warmups,
            runs=args.runs,
        )
        for page in pages
    ]
    ops_release_manifest = _measure_ops_release_manifest(path, runs=args.runs)
    if not ops_release_manifest["within_budget"]:
        raise RuntimeError(
            "Ops Release manifest exceeded interactive performance budget: "
            f"{ops_release_manifest['median_ms']}ms > "
            f"{ops_release_manifest['budget_ms']}ms"
        )
    runtime_activity_after = _runtime_activity_metadata(path)
    database_after = _sqlite_metadata(path)
    prospective_cache_seed = export_prospective_summary_seed(path)
    if prospective_cache_seed is None:
        raise RuntimeError(
            "Performance probe did not produce a prospective cache seed."
        )
    if args.release_commit is None:
        raise RuntimeError(
            "Release-bound performance probe is required for seeded cold proof."
        )
    seeded_cold_dashboard = _measure_seeded_dashboard_cold(
        path,
        release_commit=args.release_commit.lower(),
        seed=prospective_cache_seed,
    )
    if not seeded_cold_dashboard["history_rebuild_avoided"]:
        raise RuntimeError(
            "Persisted prospective seed did not avoid the historical rebuild."
        )

    medians = {
        str(item["page"]): float(item["wall_ms"]["median"])
        for item in measurements
    }
    full_median = medians.get("FULL")
    relative_to_full = {}
    if full_median and full_median > 0:
        relative_to_full = {
            page: round(value / full_median, 4)
            for page, value in medians.items()
            if page != "FULL"
        }

    payload = {
        "probe_version": 5,
        "release_commit": (
            None
            if args.release_commit is None
            else args.release_commit.lower()
        ),
        "read_only": True,
        "deployment_lock_held": bool(args.deployment_lock_held),
        "prospective_cache_seed": prospective_cache_seed,
        "seeded_cold_dashboard": seeded_cold_dashboard,
        "database_before": database_before,
        "database_after": database_after,
        "runtime_activity_before": runtime_activity_before,
        "runtime_activity_after": runtime_activity_after,
        "wal_delta_bytes": (
            int(database_after["wal_bytes"])
            - int(database_before["wal_bytes"])
        ),
        "pages": measurements,
        "ops_release_manifest": ops_release_manifest,
        "relative_median_to_full": relative_to_full,
    }

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
