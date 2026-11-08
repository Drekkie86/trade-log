from __future__ import annotations

from src.database.repository import get_connection
from src.research.local_surface_empirical_null_v1 import load_discovery_windows
from src.research.local_surface_residual_v2 import LocalSurfaceResidualV2Error, scan_local_surface_residual_v2


def discovery_completed_runs() -> list[int]:
    windows = load_discovery_windows()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, us_session_date FROM research_runs WHERE status = 'COMPLETED' ORDER BY id;"
        ).fetchall()
        already = {
            int(row["research_run_id"])
            for row in conn.execute(
                "SELECT research_run_id FROM local_surface_residual_v2_runs WHERE model_version = '0.1.0';"
            ).fetchall()
        }
    finally:
        conn.close()
    return [
        int(row["id"])
        for row in rows
        if str(row["us_session_date"] or "")
        and any(window.start <= str(row["us_session_date"]) <= window.end for window in windows)
        and int(row["id"]) not in already
    ]


def main() -> None:
    run_ids = discovery_completed_runs()
    if not run_ids:
        print("No missing V2 observations for registered discovery runs.")
        return
    print(f"Backfilling V2 for {len(run_ids)} registered discovery research runs...")
    for run_id in run_ids:
        try:
            result = scan_local_surface_residual_v2(research_run_id=run_id, persist=True)
        except LocalSurfaceResidualV2Error as exc:
            if "already persisted" in str(exc):
                print(f"run {run_id}: already present; skipped")
                continue
            raise
        print(f"run {run_id}: mapped={result.reference_mapped_count} evaluable={result.evaluable_count} surfaced=0")


if __name__ == "__main__":
    main()
