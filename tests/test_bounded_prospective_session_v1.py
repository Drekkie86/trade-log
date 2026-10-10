"""A session audit cannot inflate prospective evidence or run an unrestricted scan."""
from __future__ import annotations

import json
import sqlite3

import pytest

from src.research.bounded_prospective_session_v1 import (
    BoundedScienceError,
    combine_completed_sessions,
    evaluate_one_session,
)
from src.research.prospective_hypothesis_checkpoint_v1 import (
    _h1_metrics,
    _h2_metrics,
    _h3_metrics,
    _h4_metrics,
)
from test_prospective_hypothesis_checkpoint_v1 import _build_db


DATES = [
    "2026-09-04",
    "2026-09-11",
    "2026-09-14",
    "2026-09-15",
    "2026-09-16",
    "2026-09-17",
]


def _data(tmp_path):
    db = tmp_path / "readonly_science.db"
    _build_db(db, session_dates=DATES)
    with sqlite3.connect(db) as c:
        c.execute(
            "ALTER TABLE prospective_research_freeze_v1_runs "
            "ADD COLUMN frozen_through_session_date TEXT;"
        )
        c.execute(
            "UPDATE prospective_research_freeze_v1_runs "
            "SET frozen_through_session_date='2026-09-03';"
        )
        c.execute(
            "CREATE TABLE research_runs "
            "(id INTEGER PRIMARY KEY, us_session_date TEXT NOT NULL);"
        )
        c.execute(
            "INSERT INTO research_runs "
            "SELECT DISTINCT research_run_id, us_session_date "
            "FROM prospective_surface;"
        )
    return db


def test_daily_h1_h2_h3_agree_with_existing_frozen_six_date_evaluator(tmp_path):
    db = _data(tmp_path)
    original_h1 = _h1_metrics(null_run_id=7, db_path=db)
    original_h2 = _h2_metrics(null_run_id=7, db_path=db)
    original_h3 = _h3_metrics(null_run_id=7, db_path=db)
    global_h2 = original_h2["comparison_by_dte"][0]
    original_spread = original_h3["spread_to_mid"][0]
    original_age = original_h3["greek_age"][0]
    assert original_h1["per_date"]
    results = []
    for day in DATES:
        result = evaluate_one_session(
            day, db_path=db, include_contract_episodes=True
        )
        assert result["complete"] is True
        assert result["decision_enabled"] is False
        assert result["trading_edge_claimed"] is False
        assert result["read_only"] is True
        assert result["observation_count"] == 3
        assert result["research_run_count"] == 1
        assert result["frozen_null_run_id"] == 7
        assert result["h4_contract_session_episode_count"] == 3
        assert result["h4_episode_sha256"]
        assert result["h1_dte_14_20"]["observation_count"] == 3
        expected_h1 = next(
            row for row in original_h1["per_date"]
            if row["us_session_date"] == day
        )
        assert result["h1_dte_14_20"]["mean_abs_centered_residual"] == pytest.approx(
            expected_h1["mean_abs_centered_residual"]
        )
        assert result["h1_dte_14_20"]["positive_count"] == expected_h1["positive_count"]
        assert result["h1_dte_14_20"]["negative_count"] == expected_h1["negative_count"]
        h2 = result["h2_comparison_by_dte"][0]
        assert h2["observation_count"] == 1
        assert h2["dte_bucket"] == global_h2["dte_bucket"]
        for key in (
            "local_linear_better_fraction",
            "quadratic_median_abs_residual",
            "local_linear_median_abs_residual",
            "quadratic_q95_abs_residual",
            "local_linear_q95_abs_residual",
        ):
            assert h2[key] == pytest.approx(global_h2[key])
        assert result["h3_spread_to_mid"][original_spread["quality_bucket"]][
            "mean_abs_centered_residual"
        ] == pytest.approx(original_spread["mean_abs_centered_residual"])
        assert result["h3_greek_age"][original_age["quality_bucket"]][
            "mean_abs_centered_residual"
        ] == pytest.approx(original_age["mean_abs_centered_residual"])
        json.dumps(result)
        results.append(result)
    assert len(results) == 6


def test_same_date_is_deterministic_and_no_checkpoint_rows_created(tmp_path):
    db = _data(tmp_path)
    first = evaluate_one_session(DATES[0], db_path=db, include_contract_episodes=False)
    second = evaluate_one_session(DATES[0], db_path=db, include_contract_episodes=False)
    assert first["h4_episode_sha256"] == second["h4_episode_sha256"]
    assert first["h2_comparison_by_dte"] == second["h2_comparison_by_dte"]
    assert first["h4_contract_session_episodes"] is None
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM prospective_research_hypothesis_evaluations_v1"
        ).fetchone()[0] == 0


def test_row_limit_fails_closed_instead_of_returning_partial_science(tmp_path):
    db = _data(tmp_path)
    with pytest.raises(BoundedScienceError, match="Row budget"):
        evaluate_one_session(DATES[0], db_path=db, max_rows=2)


def test_wrong_date_and_unfrozen_dates_fail_closed(tmp_path):
    db = _data(tmp_path)
    for day in ("2026-09-01", "2026-9-04", "not-a-date"):
        with pytest.raises(BoundedScienceError):
            evaluate_one_session(day, db_path=db)
    with pytest.raises(BoundedScienceError, match="No genuine research runs"):
        evaluate_one_session("2026-09-18", db_path=db)


def test_unsafe_limits_rejected_without_database_read(tmp_path):
    db = _data(tmp_path)
    for kwargs in (
        {"max_rows":500_001},
        {"max_seconds":121.0},
        {"max_steps":1_000},
    ):
        with pytest.raises(ValueError):
            evaluate_one_session(DATES[0], db_path=db, **kwargs)



def test_combined_daily_h4_recovers_frozen_checkpoint_top_contracts(tmp_path):
    db = _data(tmp_path)
    days = [
        evaluate_one_session(day, db_path=db, include_contract_episodes=True)
        for day in DATES
    ]
    combined = combine_completed_sessions(days)
    legacy = _h4_metrics(null_run_id=7, db_path=db)
    assert combined["independent_dates"] == 6
    assert combined["observation_rows"] == 18
    assert combined["h4_recurring_contract_count"] == 3
    assert combined["classification"] == "BOUNDED_FROZEN_PROSPECTIVE_DESCRIPTIVE_ONLY"
    by_key = lambda x: (
        x["underlying"], x["expiration"], x["strike"], x["right"]
    )
    frozen = {by_key(item):item for item in legacy["top_recurring_contracts"]}
    replay = {by_key(item):item for item in combined["h4_top_recurring_contracts"]}
    assert frozen.keys() == replay.keys()
    for key in frozen:
        for field in (
            "session_date_count",
            "total_observation_count",
            "positive_episode_dates",
            "negative_episode_dates",
        ):
            assert frozen[key][field] == replay[key][field]
        for field in (
            "mean_abs_episode_location",
            "max_peak_abs_residual",
            "cross_date_sign_agreement",
        ):
            assert frozen[key][field] == pytest.approx(replay[key][field])


def test_combiner_refuses_omitted_episodes_tampering_and_mixed_protocol(tmp_path):
    db = _data(tmp_path)
    import copy
    first = evaluate_one_session(DATES[0], db_path=db, include_contract_episodes=True)
    second = evaluate_one_session(DATES[1], db_path=db, include_contract_episodes=True)
    with pytest.raises(BoundedScienceError, match="sorted and distinct"):
        combine_completed_sessions([second, first])
    with pytest.raises(BoundedScienceError, match="Contract episodes required"):
        combine_completed_sessions([
            evaluate_one_session(DATES[0], db_path=db),
        ])
    different = copy.deepcopy(second)
    different["frozen_null_run_id"] = 999
    with pytest.raises(BoundedScienceError, match="Frozen protocol changed"):
        combine_completed_sessions([first, different])
    tampered = copy.deepcopy(second)
    tampered["h4_contract_session_episodes"][0]["mean_centered_residual"] = 999.0
    with pytest.raises(BoundedScienceError, match="digest mismatch"):
        combine_completed_sessions([first, tampered])



def test_plan_only_does_not_execute_science_or_write_checkpoints(tmp_path):
    db = _data(tmp_path)
    from src.research.bounded_prospective_session_v1 import preview_session_plan

    plan = preview_session_plan(DATES[0], db_path=db)
    assert plan["classification"] == "SESSION_QUERY_PLAN_ONLY"
    assert plan["query_executed"] is False
    assert plan["read_only"] is True
    assert plan["real_production_surface"] is False
    assert plan["sample_research_run_id"] == 100

    absent = preview_session_plan("2026-09-18", db_path=db)
    assert absent["classification"] == "NO_GENUINE_RESEARCH_RUN"
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM prospective_research_hypothesis_evaluations_v1"
        ).fetchone()[0] == 0


def test_prod_shaped_unindexed_source_blocks_before_scanning_any_rows(tmp_path):
    db = _data(tmp_path)
    # If a real production-style source table exists, do not allow the
    # expensive scan shape to slip through because the view lacks an index.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE local_surface_residual_v2_observations (id INTEGER)"
        )
    with pytest.raises(BoundedScienceError, match="lacks indexed per-run access"):
        evaluate_one_session(DATES[0], db_path=db)


def test_multiple_research_runs_same_day_keep_h2_group_and_h4_episode_parity(tmp_path):
    db = _data(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO research_runs(id, us_session_date) VALUES(300, ?)",
            (DATES[0],)
        )
        conn.execute("""
            INSERT INTO prospective_surface(
                research_run_id, underlying, expiration, strike, right,
                implied_volatility, dte, loo_residual, abs_delta,
                spread_to_mid, greek_age_seconds, us_session_date,
                evidence_phase, observation_state
            )
            SELECT 300, underlying, expiration, strike, right,
                implied_volatility, dte, loo_residual, abs_delta,
                spread_to_mid, greek_age_seconds, us_session_date,
                evidence_phase, observation_state
            FROM prospective_surface WHERE research_run_id=100
        """)
    bounded = evaluate_one_session(DATES[0], db_path=db, include_contract_episodes=True)
    assert bounded["research_run_count"] == 2
    assert bounded["observation_count"] == 6
    assert bounded["h2_comparison_by_dte"][0]["observation_count"] == 2
    assert bounded["h4_contract_session_episode_count"] == 3
    assert all(
        ep["observation_count"] == 2
        for ep in bounded["h4_contract_session_episodes"]
    )
    frozen_h1 = _h1_metrics(null_run_id=7, db_path=db)
    target = next(x for x in frozen_h1["per_date"] if x["us_session_date"] == DATES[0])
    assert target["observation_count"] == bounded["h1_dte_14_20"]["observation_count"]
    assert target["mean_abs_centered_residual"] == pytest.approx(
        bounded["h1_dte_14_20"]["mean_abs_centered_residual"]
    )
