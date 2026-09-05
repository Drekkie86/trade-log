from src.research.settlement_policy import cash_settled_allowlist, classify_settlement


def test_explicit_cash_settled_products_require_exact_contract_identity():
    assert cash_settled_allowlist() == ("SPX", "XSP")
    spx = classify_settlement("SPX", observed_exercise_style="EUROPEAN", reference_contract_id=7, shares_per_contract=100)
    xsp = classify_settlement("XSP", observed_exercise_style="EUROPEAN", reference_contract_id=8, shares_per_contract=100)
    assert spx.live_eligible is True
    assert xsp.live_eligible is True
    assert spx.contract_identity_state == "VERIFIED_REFERENCE_ID"
    assert spx.multiplier_state == "VERIFIED"


def test_cash_settled_family_without_exact_contract_identity_fails_closed():
    spx = classify_settlement("SPX", observed_exercise_style="EUROPEAN")
    assert spx.live_eligible is False
    assert spx.state == "BLOCKED_CONTRACT_IDENTITY_UNVERIFIED"


def test_equity_or_etf_style_contract_fails_closed():
    spy = classify_settlement("SPY", observed_exercise_style="AMERICAN", reference_contract_id=1, shares_per_contract=100)
    assert spy.live_eligible is False
    assert spy.state == "BLOCKED_ASSIGNMENT_OR_PHYSICAL_RISK"


def test_unknown_contract_never_infers_cash_settlement():
    unknown = classify_settlement("SOMETHING_NEW", reference_contract_id=1, shares_per_contract=100)
    assert unknown.live_eligible is False
    assert unknown.state == "BLOCKED_UNVERIFIED_SETTLEMENT"


def test_verified_product_metadata_conflict_fails_closed():
    conflict = classify_settlement("XSP", observed_exercise_style="AMERICAN", reference_contract_id=1, shares_per_contract=100)
    assert conflict.live_eligible is False
    assert conflict.state == "BLOCKED_SETTLEMENT_METADATA_CONFLICT"


def test_verified_product_multiplier_conflict_fails_closed():
    conflict = classify_settlement("XSP", observed_exercise_style="EUROPEAN", reference_contract_id=1, shares_per_contract=10)
    assert conflict.live_eligible is False
    assert conflict.state == "BLOCKED_CONTRACT_MULTIPLIER_CONFLICT"
