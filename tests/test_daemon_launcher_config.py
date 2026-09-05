import json

import pytest

from run_christiania_daemon import LOCAL_FALLBACK_SYMBOLS, configured_symbols
from src.research.research_daemon import ResearchDaemonError


def test_configured_symbols_uses_local_fallback(monkeypatch):
    monkeypatch.delenv("CHRISTIANIA_SYMBOLS", raising=False)
    monkeypatch.delenv("CHRISTIANIA_ENABLE_CASH_SETTLED_RESEARCH", raising=False)
    assert configured_symbols() == LOCAL_FALLBACK_SYMBOLS


def test_configured_symbols_parses_cloud_universe(monkeypatch):
    monkeypatch.setenv("CHRISTIANIA_SYMBOLS", "aapl, msft, spy")
    assert configured_symbols() == ["AAPL", "MSFT", "SPY"]


def test_configured_symbols_rejects_duplicates(monkeypatch):
    monkeypatch.setenv("CHRISTIANIA_SYMBOLS", "AAPL,aapl")
    with pytest.raises(ResearchDaemonError, match="duplicates"):
        configured_symbols()


def test_cash_settled_symbol_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("CHRISTIANIA_SYMBOLS", "XSP")
    monkeypatch.delenv("CHRISTIANIA_ENABLE_CASH_SETTLED_RESEARCH", raising=False)
    with pytest.raises(ResearchDaemonError, match="explicit"):
        configured_symbols()


def test_cash_settled_symbol_requires_live_proof_even_after_opt_in(monkeypatch, tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({
        "contract_version": "CASH_SETTLED_MARKET_CONTRACT_V1",
        "overall_state": "REFERENCE_PROVEN",
        "live_symbols": [],
    }), encoding="utf-8")
    monkeypatch.setenv("CHRISTIANIA_SYMBOLS", "XSP")
    monkeypatch.setenv("CHRISTIANIA_ENABLE_CASH_SETTLED_RESEARCH", "1")
    monkeypatch.setenv("CHRISTIANIA_CASH_SETTLED_EVIDENCE_PATH", str(path))
    with pytest.raises(ResearchDaemonError, match="not live-provider validated"):
        configured_symbols()


def test_cash_settled_symbol_can_run_only_after_opt_in_and_live_proof(monkeypatch, tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({
        "contract_version": "CASH_SETTLED_MARKET_CONTRACT_V1",
        "overall_state": "LIVE_VALIDATED_XSP_ONLY",
        "live_symbols": ["XSP"],
    }), encoding="utf-8")
    monkeypatch.setenv("CHRISTIANIA_SYMBOLS", "XSP")
    monkeypatch.setenv("CHRISTIANIA_ENABLE_CASH_SETTLED_RESEARCH", "1")
    monkeypatch.setenv("CHRISTIANIA_CASH_SETTLED_EVIDENCE_PATH", str(path))
    assert configured_symbols() == ["XSP"]
