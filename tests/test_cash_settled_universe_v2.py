from datetime import UTC, datetime

from src.research.cash_settled_market_contract import write_probe_evidence
from src.research.cash_settled_universe import cash_settled_research_universe


def test_cash_universe_is_explicit_and_not_silently_enabled_before_provider_probe(tmp_path):
    state = cash_settled_research_universe(evidence_path=tmp_path/"missing.json")
    assert state.symbols == ("SPX","XSP")
    assert state.provider_compatibility_state == "NOT_LIVE_PROBED"
    assert state.live_collection_enabled is False


def test_cash_universe_enables_only_integrity_checked_nonexpired_live_proof(tmp_path):
    now = datetime.now(UTC)
    evidence = {
      "contract_version":"CASH_SETTLED_MARKET_CONTRACT_V1","probe_mode":"live",
      "generated_at":now.isoformat(timespec="milliseconds").replace("+00:00","Z"),
      "provider":"THETADATA","provider_base_url":"http://127.0.0.1:25503/v3",
      "overall_state":"LIVE_DATA_CONTRACT_VALIDATED_XSP_ONLY","live_symbols":["XSP"],
      "symbols":{},"decision_enabled":False,"broker_order_path":False,
    }
    path = write_probe_evidence(evidence, tmp_path/"evidence.json")
    state = cash_settled_research_universe(evidence_path=path)
    assert state.live_collection_enabled is True
    assert state.live_symbols == ("XSP",)
    assert state.provider_compatibility_state == "LIVE_DATA_CONTRACT_VALIDATED_XSP_ONLY"
