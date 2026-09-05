from src.research.cash_settled_universe import cash_settled_research_universe


def test_cash_universe_is_explicit_and_not_silently_enabled_before_provider_probe():
    state = cash_settled_research_universe()
    assert state.symbols == ("SPX", "XSP")
    assert state.provider_compatibility_state == "NOT_LIVE_PROBED"
    assert state.live_collection_enabled is False
