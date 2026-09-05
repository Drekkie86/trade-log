from src.research.settlement_policy import cash_settled_allowlist, classify_settlement


def test_xsp_requires_exact_contract_identity_and_expected_multiplier():
    assert cash_settled_allowlist() == ("SPX", "XSP")
    xsp = classify_settlement(
        "XSP", observed_exercise_style="EUROPEAN",
        reference_contract_id=8, shares_per_contract=100,
    )
    assert xsp.live_eligible is True
    assert xsp.contract_identity_state == "VERIFIED_REFERENCE_ID"
    assert xsp.multiplier_state == "VERIFIED"
    assert xsp.settlement_style == "PM"


def test_spx_product_family_alone_is_not_enough_because_series_settlement_differs():
    spx = classify_settlement(
        "SPX", observed_exercise_style="EUROPEAN",
        reference_contract_id=7, shares_per_contract=100,
    )
    assert spx.live_eligible is False
    assert spx.state == "BLOCKED_SERIES_IDENTITY_UNVERIFIED"


def test_exact_spx_and_spxw_roots_resolve_different_settlement_styles():
    am = classify_settlement(
        "SPX", series_root="SPX", observed_exercise_style="EUROPEAN",
        reference_contract_id=7, shares_per_contract=100,
    )
    pm = classify_settlement(
        "SPX", series_root="SPXW", observed_exercise_style="EUROPEAN",
        reference_contract_id=8, shares_per_contract=100,
    )
    assert am.live_eligible is True and am.settlement_style == "AM"
    assert pm.live_eligible is True and pm.settlement_style == "PM"


def test_cash_settled_family_without_exact_contract_identity_fails_closed():
    xsp = classify_settlement("XSP", observed_exercise_style="EUROPEAN")
    assert xsp.live_eligible is False
    assert xsp.state == "BLOCKED_CONTRACT_IDENTITY_UNVERIFIED"


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
