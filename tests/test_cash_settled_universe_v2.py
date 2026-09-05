import json

from src.research.cash_settled_universe import cash_settled_research_universe


def test_cash_universe_is_explicit_and_not_silently_enabled_before_provider_probe(tmp_path):
    state = cash_settled_research_universe(evidence_path=tmp_path / "missing.json")
    assert state.symbols == ("SPX", "XSP")
    assert state.provider_compatibility_state == "NOT_LIVE_PROBED"
    assert state.live_collection_enabled is False
    assert state.live_symbols == ()
    assert state.primary_v1_symbol == "XSP"


def test_cash_universe_enables_only_symbols_with_recorded_live_proof(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({
        "contract_version": "CASH_SETTLED_MARKET_CONTRACT_V1",
        "overall_state": "LIVE_VALIDATED_XSP_ONLY",
        "live_symbols": ["XSP"],
    }), encoding="utf-8")
    state = cash_settled_research_universe(evidence_path=path)
    assert state.live_collection_enabled is True
    assert state.live_symbols == ("XSP",)
    assert state.provider_compatibility_state == "LIVE_VALIDATED_XSP_ONLY"
