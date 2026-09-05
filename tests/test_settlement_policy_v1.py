from src.research.settlement_policy import (
    cash_settled_allowlist,
    classify_settlement,
)


def test_explicit_cash_settled_products_are_tiny_and_fail_closed():
    assert cash_settled_allowlist() == ("SPX", "XSP")

    spx = classify_settlement("SPX", observed_exercise_style="EUROPEAN")
    xsp = classify_settlement("XSP", observed_exercise_style="EUROPEAN")

    assert spx.live_eligible is True
    assert xsp.live_eligible is True
    assert spx.settlement_type == "CASH"
    assert xsp.settlement_type == "CASH"


def test_equity_or_etf_style_contract_fails_closed():
    spy = classify_settlement("SPY", observed_exercise_style="AMERICAN")

    assert spy.live_eligible is False
    assert spy.state == "BLOCKED_ASSIGNMENT_OR_PHYSICAL_RISK"
    assert spy.settlement_type == "UNVERIFIED"


def test_unknown_contract_never_infers_cash_settlement():
    unknown = classify_settlement("SOMETHING_NEW")

    assert unknown.live_eligible is False
    assert unknown.state == "BLOCKED_UNVERIFIED_SETTLEMENT"


def test_verified_product_metadata_conflict_fails_closed():
    conflict = classify_settlement("XSP", observed_exercise_style="AMERICAN")

    assert conflict.live_eligible is False
    assert conflict.state == "BLOCKED_SETTLEMENT_METADATA_CONFLICT"
