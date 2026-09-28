from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_navigation_is_resolved_before_expensive_runtime_snapshot():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert app.index('page = st.radio(') < app.index(
        'snapshot, backup_inventory = _load_runtime_state()'
    )


def test_normal_runtime_snapshot_does_not_probe_theta_inline():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    runtime_start = app.index("def _load_runtime_state")
    runtime_end = app.index("def _cached_deep_ops_readiness", runtime_start)
    runtime = app[runtime_start:runtime_end]

    assert "include_provider_health=False" in runtime
    assert 'refresh_mode="background"' in app
    assert "def _cached_theta_health()" in app


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


def test_deployment_preflight_matches_python_313_runtime():
    source = (
        ROOT / "christiania_deploy_preflight.py"
    ).read_text(encoding="utf-8")

    assert 'sys.version_info[:2] == (3, 13)' in source
    assert "Python 3.13 is required" in source
    assert "Python 3.10 or newer is required" not in source
