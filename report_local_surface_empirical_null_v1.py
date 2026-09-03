from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.database.repository import get_connection


def main() -> None:
    conn = get_connection()
    try:
        run = conn.execute("SELECT * FROM local_surface_null_v1_runs ORDER BY id DESC LIMIT 1;").fetchone()
        if run is None:
            raise SystemExit("No persisted empirical-null run. Fit one first.")
        null_run_id = int(run["id"])
        strata = [dict(row) for row in conn.execute(
            "SELECT * FROM local_surface_null_v1_strata WHERE null_run_id = ? ORDER BY right, dte_bucket, abs_delta_bucket;",
            (null_run_id,),
        ).fetchall()]
        dependence = [dict(row) for row in conn.execute(
            "SELECT * FROM local_surface_null_v1_dependence WHERE null_run_id = ? ORDER BY id;",
            (null_run_id,),
        ).fetchall()]
        largest = [dict(row) for row in conn.execute(
            """
            SELECT research_run_id, session_date, underlying, expiration, strike, right,
                   abs_delta, dte, spread_to_mid, loo_residual, centered_residual,
                   abs_centered_residual, stratum_key, stratum_observation_count,
                   stratum_shrunk_location, stratum_shrunk_scale
            FROM v_local_surface_null_v1_discovery_membership
            WHERE null_run_id = ?
            ORDER BY abs_centered_residual DESC, observation_id
            LIMIT 50;
            """,
            (null_run_id,),
        ).fetchall()]
    finally:
        conn.close()

    payload = {
        "null_run": dict(run),
        "strata": strata,
        "dependence": dependence,
        "largest_absolute_centered_residuals": largest,
        "interpretation_guardrail": (
            "Discovery-only descriptive statistics. No p-values, no FDR/BH decisions, "
            "no candidate/admission decision, and no edge claim."
        ),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path.home() / "Downloads"
    json_path = out_dir / f"Christiania_Local_Surface_Null_V1_{stamp}.json"
    md_path = out_dir / f"Christiania_Local_Surface_Null_V1_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Christiania LOCAL_SURFACE_EMPIRICAL_NULL_V1 — Discovery Report",
        "",
        f"- Null run: **{null_run_id}**",
        f"- Source dates: **{run['source_first_session_date']} → {run['source_last_session_date']}**",
        f"- Observations: **{run['observation_count']}**",
        f"- Strata: **{run['stratum_count']}**",
        "- p-values: **disabled**",
        "- FDR/BH: **disabled**",
        "- decision/admission: **disabled**",
        "",
        "## Dependence diagnostics",
        "",
        "| dimension | N | clusters | repeated clusters | mean size | ICC-like | design effect proxy | effective N proxy | state |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in dependence:
        lines.append(
            f"| {item['cluster_dimension']} | {item['raw_observation_count']} | {item['cluster_count']} | "
            f"{item['repeated_cluster_count']} | {item['mean_cluster_size']:.3f} | "
            f"{'' if item['icc_oneway'] is None else f'{item['icc_oneway']:.4f}'} | "
            f"{'' if item['design_effect_proxy'] is None else f'{item['design_effect_proxy']:.3f}'} | "
            f"{'' if item['effective_n_proxy'] is None else f'{item['effective_n_proxy']:.1f}'} | {item['estimator_state']} |"
        )
    lines.extend(["", "## Strata", "", "| stratum | N | median | robust scale | shrunk location | shrunk scale | q2.5% | q97.5% |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for item in strata:
        lines.append(
            f"| {item['stratum_key']} | {item['observation_count']} | {item['raw_median']:.6f} | "
            f"{item['raw_robust_scale']:.6f} | {item['shrunk_location']:.6f} | {item['shrunk_scale']:.6f} | "
            f"{item['q025']:.6f} | {item['q975']:.6f} |"
        )
    lines.extend([
        "",
        "## Guardrail",
        "",
        "These are discovery-only descriptive statistics. The largest residuals are not discoveries, signals, or p-values. "
        "No multiple-testing decision is made here.",
    ])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")


if __name__ == "__main__":
    main()
