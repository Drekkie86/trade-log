"""Results must not confuse market-data coverage with prospective evidence.

A market snapshot date can be historical or recovered. It is not an
independent prospective research session and never counts as a result.
"""
from __future__ import annotations

import src.dashboard.read_model as read_model
from src.database.repository import get_connection


def test_results_market_days_use_distinct_snapshots_not_prospective_runs(db_path):
    conn = get_connection(db_path)
    try:
        with conn:
            for day, underlying in (
                ("2026-10-06", "AAPL"),
                ("2026-10-06", "MSFT"),
                ("2026-10-07", "AAPL"),
                ("2026-10-09", "AAPL"),
            ):
                conn.execute(
                    """INSERT INTO market_snapshots
                       (captured_at, underlying, provider, underlying_source,
                        fx_source, us_session_date, us_session_state)
                       VALUES (?, ?, 'TEST', 'UNKNOWN', 'UNKNOWN', ?, 'INTRADAY')""",
                    (day + "T15:00:00Z", underlying, day),
                )
    finally:
        conn.close()

    results = read_model.load_command_deck(
        db_path, deep_integrity=False, include_provider_health=False,
        page="Results",
    )
    assert results["ready"] is True
    assert results["research_counts"]["market_snapshot_days"] == 3
    assert results["prospective"]["independent_dates"] == 0

    # The additional aggregation belongs ONLY on Results, not on hot pages
    # or the full read model used by older tests and tooling.
    dashboard = read_model.load_command_deck(
        db_path, deep_integrity=False, include_provider_health=False,
        page="Dashboard",
    )
    assert dashboard["research_counts"]["market_snapshot_days"] == 0


def test_dashboard_skips_market_day_distinct_scan(monkeypatch, db_path):
    statements = []
    open_connection = read_model.open_readonly_connection

    def traced(path):
        conn = open_connection(path)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(read_model, "open_readonly_connection", traced)
    read_model.load_command_deck(
        db_path, deep_integrity=False, include_provider_health=False,
        page="Dashboard",
    )
    assert not any(
        "COUNT(DISTINCT us_session_date)" in sql
        for sql in statements
    )


def test_results_ui_uses_two_explicit_date_populations(monkeypatch):
    from src.ui import home_pages

    metrics = []
    captions = []

    class Column:
        def metric(self, label, value, *args, **kwargs):
            metrics.append((label, value))

    monkeypatch.setattr(home_pages.st, "columns", lambda n: [Column() for _ in range(n)])
    monkeypatch.setattr(home_pages.st, "caption", captions.append)
    monkeypatch.setattr(home_pages, "section_heading", lambda *args: None)
    monkeypatch.setattr(home_pages, "banner", lambda *args: None)

    class Expander:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    monkeypatch.setattr(home_pages.st, "expander", lambda *args, **kwargs: Expander())
    monkeypatch.setattr(home_pages.st, "markdown", lambda *args, **kwargs: None)
    home_pages.render_results_page({
        "shadow_expiry_outcomes": {"resolved": 0, "unresolved": 0},
        "research_counts": {
            "surfaced_total": 0, "shadow_candidates": 0,
            "market_snapshot_days": 26,
        },
        "prospective": {"independent_dates": 17},
    })
    assert ("Market-data days", "26") in metrics
    assert all(label != "Days of data" for label, _ in metrics)
    assert any("17" in line and "Prospective" in line for line in captions)
