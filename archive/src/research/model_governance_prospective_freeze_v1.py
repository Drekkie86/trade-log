from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from src.database.repository import DB_PATH, get_connection

VERSION = "1.0.0"

MODELS = [
    ("LOCAL_SURFACE_QUADRATIC_V2", "2.0.0", "LOCAL_IV_SURFACE", "FROZEN_PRIMARY_OBSERVATIONAL", "src/research/local_surface_residual_v2.py", 1,
     "Frozen observational V2 LOO quadratic residual. No admission or trading use."),
    ("NEAREST_BRACKET_LINEAR_V1", "1.0.0", "LOCAL_IV_SURFACE", "CHALLENGER_OBSERVATIONAL", "src/research/local_surface_calibration_validity_v1.py", 1,
     "Independent local-linear comparator introduced for model-form challenge. Observational only."),
    ("BLACK_SCHOLES_MERTON_BENCHMARK", "RESERVED", "PARAMETRIC_OPTION_PRICING", "RESERVED_NOT_IMPLEMENTED", None, 0,
     "Reserved for a future validated benchmark implementation. Produces no evidence yet."),
    ("BAYESIAN_PERSISTENCE_MODEL", "RESERVED", "BAYESIAN_EVIDENCE_UPDATE", "RESERVED_NOT_IMPLEMENTED", None, 0,
     "Reserved for future posterior updating after sufficient independent dates. Produces no evidence yet."),
]

HYPOTHESES = [
    (
        "H1_DTE_14_20_TRANSFER_STABILITY",
        "Retest whether the observed DTE 14-20 cross-date transfer instability persists on new independent session dates.",
        "CONTRACT_SESSION_EPISODE",
        "two-sided empirical transfer tail fraction by independent train/test date",
        5,
        {"freeze_behavior": "no threshold retuning from pre-freeze data", "review_at_dates": [5, 20], "decision": False},
    ),
    (
        "H2_MODEL_FORM_GENERALIZATION",
        "Compare frozen quadratic V2 with nearest-bracket local-linear V1 on prospective dates without automatic model switching.",
        "OPTION_OBSERVATION_AND_CONTRACT_SESSION_EPISODE",
        "median/q95 absolute residual plus cross-date episode transfer stability",
        5,
        {"models": ["LOCAL_SURFACE_QUADRATIC_V2", "NEAREST_BRACKET_LINEAR_V1"], "auto_select_winner": False, "decision": False},
    ),
    (
        "H3_MARKET_QUALITY_CONDITIONING",
        "Retest whether spread and timing quality explain residual scale and tail behavior prospectively.",
        "CONTRACT_SESSION_EPISODE",
        "residual scale/tails by frozen spread and timing quality buckets",
        5,
        {"metrics": ["SPREAD_TO_MID", "GREEK_AGE_ABS", "QUOTE_GREEK_SKEW_ABS", "UNDERLYING_GREEK_SKEW_ABS"], "decision": False},
    ),
    (
        "H4_PERSISTENT_EPISODE_RECURRENCE",
        "Track whether persistent same-sign residual episodes recur across independent dates rather than appearing as isolated intraday spikes.",
        "CONTRACT_SESSION_EPISODE",
        "persistence ratio, sign consistency, and cross-date recurrence descriptors",
        5,
        {"no_candidate_creation": True, "decision": False},
    ),
]


def _hash_config(config: dict) -> tuple[str, str]:
    text = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest(), text


def freeze_model_governance_v1(db_path: str | Path = DB_PATH) -> dict:
    conn = get_connection(db_path)
    try:
        validity = conn.execute(
            "SELECT * FROM local_surface_calibration_validity_v1_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if validity is None:
            raise RuntimeError("No v23 calibration-validity run exists.")

        last_date = conn.execute(
            "SELECT MAX(session_date) FROM local_surface_calibration_readiness_v1_episodes WHERE calibration_run_id=?",
            (validity["source_calibration_run_id"],),
        ).fetchone()[0]
        if not last_date:
            raise RuntimeError("Cannot determine last discovery session date.")

        prospective_start = (date.fromisoformat(last_date) + timedelta(days=1)).isoformat()
        config = {
            "version": VERSION,
            "source_validity_run_id": int(validity["id"]),
            "frozen_through_session_date": last_date,
            "prospective_start_session_date": prospective_start,
            "models": [m[0] for m in MODELS],
            "hypotheses": [h[0] for h in HYPOTHESES],
            "review_at_independent_dates": [5, 20],
            "p_values": False,
            "fdr": False,
            "admission": False,
            "decision": False,
        }
        config_hash, config_json = _hash_config(config)

        with conn:
            for row in MODELS:
                conn.execute(
                    """INSERT INTO research_model_registry_v1(
                    model_key,model_version,model_family,governance_role,implementation_ref,evidence_use_enabled,
                    admission_enabled,decision_enabled,notes) VALUES(?,?,?,?,?,?,0,0,?)
                    ON CONFLICT(model_key) DO NOTHING""",
                    row,
                )

            existing = conn.execute(
                "SELECT id FROM prospective_research_freeze_v1_runs WHERE protocol_version=? AND source_validity_run_id=? AND config_hash=?",
                (VERSION, validity["id"], config_hash),
            ).fetchone()
            if existing:
                run_id = int(existing["id"])
            else:
                cur = conn.execute(
                    """INSERT INTO prospective_research_freeze_v1_runs(
                    protocol_version,source_validity_run_id,frozen_at,frozen_through_session_date,prospective_start_session_date,
                    timestamp_confidence_state,source_readiness_state,source_dte_14_20_state,protocol_state,config_hash,config_json,
                    p_values_enabled,fdr_enabled,admission_enabled,decision_enabled)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,0,0,0,0)""",
                    (
                        VERSION, validity["id"], datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        last_date, prospective_start, validity["timestamp_confidence_state"], validity["readiness_state"],
                        validity["dte_14_20_instability_state"], "FROZEN_PROSPECTIVE_OBSERVATION_ONLY", config_hash, config_json,
                    ),
                )
                run_id = int(cur.lastrowid)

            for key, desc, unit, metric, min_dates, rule in HYPOTHESES:
                conn.execute(
                    """INSERT OR IGNORE INTO prospective_research_hypotheses_v1(
                    freeze_run_id,hypothesis_key,description,primary_unit,primary_metric,minimum_independent_dates,
                    evaluation_rule_json,hypothesis_state,decision_enabled) VALUES(?,?,?,?,?,?,?,'UNTESTED_PROSPECTIVE',0)""",
                    (run_id, key, desc, unit, metric, min_dates, json.dumps(rule, sort_keys=True)),
                )

            comparisons = conn.execute(
                "SELECT * FROM local_surface_calibration_validity_v1_model_comparison WHERE validity_run_id=? ORDER BY dte_bucket",
                (validity["id"],),
            ).fetchall()
            for cmp_row in comparisons:
                dte = cmp_row["dte_bucket"]
                raw = conn.execute(
                    "SELECT MAX(tail_inflation_ratio) FROM local_surface_calibration_validity_v1_dte_transfer WHERE validity_run_id=? AND dte_bucket=?",
                    (validity["id"], dte),
                ).fetchone()[0]
                tails = conn.execute(
                    "SELECT MIN(test_tail_fraction),MAX(test_tail_fraction) FROM local_surface_calibration_validity_v1_episode_transfer WHERE validity_run_id=? AND dte_bucket=?",
                    (validity["id"], dte),
                ).fetchone()
                review_state = (
                    "KNOWN_INSTABILITY_PROSPECTIVE_RETEST_REQUIRED"
                    if dte == "DTE_14_20" and validity["dte_14_20_instability_state"] == "OBSERVED_UNSTABLE"
                    else "PROSPECTIVE_COMPARISON_REQUIRED"
                )
                conn.execute(
                    """INSERT OR IGNORE INTO prospective_model_dte_baseline_v1(
                    freeze_run_id,dte_bucket,quadratic_median_abs_residual,local_linear_median_abs_residual,
                    quadratic_q95_abs_residual,local_linear_q95_abs_residual,local_linear_better_fraction,
                    raw_transfer_max_inflation,episode_transfer_min_tail,episode_transfer_max_tail,review_state)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id,dte,cmp_row["quadratic_median_abs_residual"],cmp_row["local_linear_median_abs_residual"],
                        cmp_row["quadratic_q95_abs_residual"],cmp_row["local_linear_q95_abs_residual"],cmp_row["local_linear_better_fraction"],
                        raw,tails[0],tails[1],review_state,
                    ),
                )

        return {
            "freeze_run_id": run_id,
            "frozen_through_session_date": last_date,
            "prospective_start_session_date": prospective_start,
            "source_validity_run_id": int(validity["id"]),
            "source_readiness_state": validity["readiness_state"],
            "dte_14_20_state": validity["dte_14_20_instability_state"],
            "model_count": len(MODELS),
            "hypothesis_count": len(HYPOTHESES),
            "firewall": "p-values/FDR/admission/decision disabled",
        }
    finally:
        conn.close()
