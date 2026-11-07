from __future__ import annotations

from pathlib import Path

from src.dashboard.read_model import load_command_deck


ROOT = Path(__file__).resolve().parents[1]










def test_dashboard_loader_skips_unrelated_populations(db_path):
    deck = load_command_deck(
        db_path,
        include_provider_health=False,
        deep_integrity=False,
        page="Dashboard",
    )

    assert deck["ready"] is True
    assert deck["read_model_page"] == "Dashboard"
    assert deck["decision_desk_candidates"] == []
    assert deck["shadow_candidate_followup"] == []
    assert deck["recent_anomalies"] == []
    assert deck["checkpoint_evaluations"] == []

    timings = deck["read_model_timings_ms"]
    assert "runtime_ms" in timings
    assert "prospective_ms" in timings
    assert "counts_ms" in timings
    assert "governance_ms" in timings
    assert "runs_ms" in timings
    assert "decision_ms" not in timings
    assert "shadow_detail_ms" not in timings
    assert "observations_ms" not in timings


def test_decision_desk_loader_skips_dashboard_and_shadow_history(db_path):
    deck = load_command_deck(
        db_path,
        include_provider_health=False,
        deep_integrity=False,
        page="Decision Desk",
    )

    assert deck["ready"] is True
    assert deck["read_model_page"] == "Decision Desk"
    assert deck["recent_iterations"] == []
    assert deck["shadow_candidate_followup"] == []
    assert deck["historical_replay_latest"] == []

    timings = deck["read_model_timings_ms"]
    assert "governance_ms" in timings
    assert "decision_ms" in timings
    assert "decision_risk_ms" in timings
    assert "runtime_ms" not in timings
    assert "replay_ms" not in timings
    assert "data_quality_ms" not in timings


def test_non_database_heavy_quant_page_uses_minimal_read_model(db_path):
    deck = load_command_deck(
        db_path,
        include_provider_health=False,
        deep_integrity=False,
        page="Quant Models",
    )

    assert deck["ready"] is True
    assert deck["read_model_page"] == "Quant Models"
    assert deck["decision_desk_candidates"] == []
    assert deck["recent_iterations"] == []
    assert deck["data_quality"] == {}
    assert set(deck["read_model_timings_ms"]) == {
        "database_health_ms",
        "market_clock_ms",
        "total_ms",
    }


def test_candidate_window_queries_are_bounded_before_history_ranking():
    source = (
        ROOT / "src/dashboard/read_model.py"
    ).read_text(encoding="utf-8")

    decision_start = source.index(
        "decision_desk_candidates = _rows_to_dicts"
    )
    follow_start = source.index(
        "shadow_candidate_followup = _rows_to_dicts"
    )

    decision = source[decision_start:follow_start]
    follow = source[follow_start:]

    assert "WITH recent_candidates AS" in decision
    assert "LIMIT 100" in decision
    assert "JOIN recent_candidates AS rc" in decision
    assert "FROM recent_candidates AS sc" in decision
    assert decision.index("LIMIT 100") < decision.index("ROW_NUMBER() OVER")

    assert "WITH recent_candidates AS" in follow
    assert "LIMIT 100" in follow
    assert follow.count("JOIN recent_candidates AS rc") >= 4
    assert "FROM recent_candidates AS sc" in follow
    assert follow.index("LIMIT 100") < follow.index("ROW_NUMBER() OVER")


# test_prospective_recovered_sample_count_avoids_string_distinct was a source-
# substring check. Its invariant (recovered samples are distinct run/underlying
# pairs, counted without string DISTINCT) is now verified behaviourally against
# the legacy query in tests/test_prospective_summary_incremental_v1.py.


def test_replay_latest_mark_uses_indexable_correlated_lookup():
    source = (
        ROOT / "src/dashboard/read_model.py"
    ).read_text(encoding="utf-8")

    replay_start = source.index('if _needs("replay")')
    lifecycle_start = source.index('if _needs("lifecycle")', replay_start)
    replay = source[replay_start:lifecycle_start]

    assert "ROW_NUMBER() OVER" not in replay
    assert "WHERE hrm.policy_replay_id = hpr.id" in replay
    assert "ORDER BY hrm.observed_at DESC, hrm.id DESC" in replay
    assert "LIMIT 1" in replay




def test_deployment_preflight_matches_python_313_runtime():
    source = (
        ROOT / "christiania_deploy_preflight.py"
    ).read_text(encoding="utf-8")

    assert 'sys.version_info[:2] == (3, 13)' in source
    assert "Python 3.13 is required" in source
    assert "Python 3.10 or newer is required" not in source






