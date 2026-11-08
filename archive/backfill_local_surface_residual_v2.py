from __future__ import annotations

import argparse

from src.database.repository import get_connection
from src.research.local_surface_residual_v2 import LocalSurfaceResidualV2Error, scan_local_surface_residual_v2


def completed_runs(start_run: int, end_run: int) -> list[int]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM research_runs WHERE id BETWEEN ? AND ? AND status = 'COMPLETED' ORDER BY id;",
            (start_run, end_run),
        ).fetchall()
        return [int(row["id"]) for row in rows]
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill observational V2 residuals for already-burned discovery research runs.")
    parser.add_argument("--start-run", type=int, required=True)
    parser.add_argument("--end-run", type=int, required=True)
    args = parser.parse_args()
    if args.end_run < args.start_run:
        raise SystemExit("--end-run must be >= --start-run")

    for run_id in completed_runs(args.start_run, args.end_run):
        try:
            result = scan_local_surface_residual_v2(research_run_id=run_id, persist=True)
        except LocalSurfaceResidualV2Error as exc:
            if "already persisted" in str(exc):
                print(f"run {run_id}: already present; skipped")
                continue
            raise
        print(
            f"run {run_id}: mapped={result.reference_mapped_count} "
            f"evaluable={result.evaluable_count} surfaced=0"
        )


if __name__ == "__main__":
    main()
