from __future__ import annotations

from pathlib import Path

from src.dashboard.read_model import load_command_deck


ROOT = Path(__file__).resolve().parents[1]


def test_navigation_is_resolved_before_expensive_runtime_snapshot():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert app.index('page = st.radio(') < app.index(
        'snapshot, backup_inventory = _load_runtime_state(page)'
    )


def test_interactive_runtime_is_page_scoped_and_background_refreshed():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    cache_start = app.index("def _cached_page_runtime_state")
    cache_end = app.index("def _load_runtime_state", cache_start)
    cache_block = app[cache_start:cache_end]

    assert 'refresh_mode="background"' in app
    assert "page=page" in cache_block
    assert "include_provider_health=False" in cache_block
    assert "inventory_backups_fast().as_dict()" in cache_block
    assert 'if page == "Dashboard"' in cache_block


def test_normal_runtime_snapshot_does_not_probe_theta_inline():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "def _cached_theta_health()" in app
    assert 'refresh_mode="background"' in app
    assert "include_provider_health=False" in app


def test_decision_desk_model_dossier_is_explicitly_requested():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    dossier_section = app.index('section_heading("Full model dossier"')
    arguments_section = app.index(
        'section_heading("Arguments for / against")',
        dossier_section,
    )
    block = app[dossier_section:arguments_section]

    assert 'st.button(' in block
    assert '"Run model dossier"' in block
    assert "_cached_candidate_model_dossier(full_selected)" in block
    assert block.index('"Run model dossier"') < block.index(
        "_cached_candidate_model_dossier(full_selected)"
    )


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


def test_deep_ops_readiness_is_scoped_instead_of_loading_every_page():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    start = app.index("def _cached_deep_ops_readiness")
    end = app.index("with st.sidebar:", start)
    block = app[start:end]

    assert 'page="Ops Readiness"' in block


def test_deployment_preflight_matches_python_313_runtime():
    source = (
        ROOT / "christiania_deploy_preflight.py"
    ).read_text(encoding="utf-8")

    assert 'sys.version_info[:2] == (3, 13)' in source
    assert "Python 3.13 is required" in source
    assert "Python 3.10 or newer is required" not in source


def test_decision_desk_is_fragmented_for_row_interactions():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    page_start = app.index('elif page == "Decision Desk":')
    next_page = app.index('elif page == "Research Runs":', page_start)
    block = app[page_start:next_page]

    assert "@st.fragment" in block
    assert "def _render_decision_desk_page():" in block
    assert '_show_selectable_table(' in block
    assert '_render_decision_desk_page()' in block


def test_other_interactive_pages_are_fragmented():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    expected = {
        "Research Runs": "_render_research_runs_page",
        "Calibration": "_render_calibration_page",
        "Observations": "_render_observations_page",
        "Shadow Lab": "_render_shadow_lab_page",
        "Ops": "_render_ops_page",
    }

    for page, function_name in expected.items():
        start = app.index(f'elif page == "{page}":')
        next_page = app.find('elif page == "', start + 1)
        block = app[start:] if next_page == -1 else app[start:next_page]

        assert "@st.fragment" in block
        assert f"def {function_name}():" in block
        assert f"{function_name}()" in block


def test_observation_cross_filter_reruns_only_its_fragment():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    start = app.index('elif page == "Observations":')
    end = app.index('elif page == "Shadow Lab":', start)
    block = app[start:end]

    assert 'st.rerun(scope="fragment")' in block
    assert "st.rerun()" not in block
