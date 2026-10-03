from __future__ import annotations

import pytest

import src.dashboard.read_model as read_model


def _trace_page(monkeypatch, db_path, page):
    statements: list[str] = []
    original = read_model.open_readonly_connection

    def traced(path):
        connection = original(path)
        connection.set_trace_callback(statements.append)
        return connection

    with monkeypatch.context() as scoped:
        scoped.setattr(
            read_model,
            "open_readonly_connection",
            traced,
        )
        deck = read_model.load_command_deck(
            db_path,
            include_provider_health=False,
            deep_integrity=False,
            page=page,
        )

    assert deck["ready"] is True

    sql = [
        statement.strip()
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
    ]
    return deck, sql


@pytest.mark.slow
def test_dashboard_sql_work_is_materially_smaller_than_full_deck(
    monkeypatch,
    db_path,
):
    _, dashboard_sql = _trace_page(
        monkeypatch,
        db_path,
        "Dashboard",
    )
    _, full_sql = _trace_page(
        monkeypatch,
        db_path,
        None,
    )

    assert full_sql
    assert dashboard_sql
    assert len(dashboard_sql) <= int(len(full_sql) * 0.60)

    dashboard_text = "\n".join(dashboard_sql)
    assert "historical_replay_marks_v1" not in dashboard_text
    assert "shadow_state_events" not in dashboard_text
    assert "v_shadow_risk_current" not in dashboard_text


@pytest.mark.slow
def test_quant_models_page_does_not_run_research_population_queries(
    monkeypatch,
    db_path,
):
    deck, sql = _trace_page(
        monkeypatch,
        db_path,
        "Quant Models",
    )

    assert deck["read_model_page"] == "Quant Models"
    assert sql == []
    assert set(deck["read_model_timings_ms"]) == {
        "database_health_ms",
        "market_clock_ms",
        "total_ms",
    }
