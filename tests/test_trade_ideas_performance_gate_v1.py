"""Release must time the actual default Trade Ideas model queries."""
from __future__ import annotations

from pathlib import Path

import christiania_performance_probe as probe
from src.database.repository import get_connection
from tests.test_trade_ideas import seed_scenario


def test_trade_ideas_production_gate_measures_scoring_and_track_record(db_path):
    seed_scenario(db_path, with_v2=True)
    conn = get_connection(db_path)
    try:
        before = conn.execute("PRAGMA data_version").fetchone()[0]
    finally:
        conn.close()
    result = probe._measure_trade_ideas(Path(db_path), warmups=0, runs=1)
    assert result["within_budget"], result
    assert result["cached"] is False
    assert result["proposals_scored"] == 1
    assert result["proposals_unscorable"] == 0
    assert result["latest_session"] == "2026-09-01"
    assert result["expiry_track_record_available"] is True
    assert result["resolved_expiry_bets"] == 0
    conn = get_connection(db_path)
    try:
        assert before == conn.execute("PRAGMA data_version").fetchone()[0]
    finally:
        conn.close()


def test_trade_ideas_gate_blocks_excessive_page_latency(db_path, monkeypatch):
    monkeypatch.setattr(probe, "TRADE_IDEAS_COLD_BUDGET_MS", 0.0)
    monkeypatch.setattr(probe, "TRADE_IDEAS_MEDIAN_BUDGET_MS", 0.0)
    result = probe._measure_trade_ideas(Path(db_path), warmups=0, runs=1)
    assert result["within_budget"] is False


def test_release_scripts_require_actual_trade_ideas_perf_evidence():
    root = Path(__file__).resolve().parents[1]
    for filename in (
        "deploy/deploy_release.ps1",
        "deploy/probe_release_performance.ps1",
    ):
        script = (root / filename).read_text(encoding="utf-8")
        assert "trade_ideas.within_budget" in script
        assert "trade_ideas.cached" in script
        assert "Trade Ideas" in script
        assert "probe_version -lt 7" in script
    source = (root / "christiania_performance_probe.py").read_text(encoding="utf-8")
    assert '"probe_version": 7' in source
    assert '"dataset_provenance": dataset_provenance' in source
    assert '"trade_ideas": trade_ideas' in source
    probe_runner = (root / "deploy/probe_release_performance.sh").read_text(encoding="utf-8")
    assert "christiania-backup*" in probe_runner
    assert "christiania-volume*" in probe_runner
    assert "transient recovery/backup maintenance is active" in probe_runner
