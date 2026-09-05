from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SettlementClassification:
    underlying: str
    settlement_type: str
    exercise_style: str
    live_eligible: bool
    state: str
    reason: str
    provenance: str
    contract_identity_state: str
    multiplier_state: str

    def as_dict(self) -> dict:
        return asdict(self)


_CASH_SETTLED_PRODUCTS = {
    "SPX": {
        "settlement_type": "CASH",
        "exercise_style": "EUROPEAN",
        "multiplier": 100.0,
        "provenance": "CBOE_SPX_PRODUCT_PAGE_VERIFIED_2026-09-05",
    },
    "XSP": {
        "settlement_type": "CASH",
        "exercise_style": "EUROPEAN",
        "multiplier": 100.0,
        "provenance": "CBOE_XSP_PRODUCT_PAGE_VERIFIED_2026-09-05",
    },
}


def classify_settlement(
    underlying: str | None,
    *,
    observed_exercise_style: str | None = None,
    reference_contract_id: int | None = None,
    shares_per_contract: float | None = None,
) -> SettlementClassification:
    symbol = str(underlying or "").strip().upper()
    observed_style = str(observed_exercise_style or "").strip().upper()
    contract_identity_state = "VERIFIED_REFERENCE_ID" if reference_contract_id is not None else "MISSING_REFERENCE_ID"

    if not symbol:
        return SettlementClassification(
            underlying="UNKNOWN",
            settlement_type="UNVERIFIED",
            exercise_style=observed_style or "UNVERIFIED",
            live_eligible=False,
            state="BLOCKED_UNVERIFIED_SETTLEMENT",
            reason="Contract underlying is missing; cash settlement cannot be verified.",
            provenance="FAIL_CLOSED",
            contract_identity_state=contract_identity_state,
            multiplier_state="UNVERIFIED",
        )

    policy = _CASH_SETTLED_PRODUCTS.get(symbol)
    if policy is None:
        reason = (
            "American-style contract is not on Christiania's explicit cash-settled allow-list."
            if observed_style == "AMERICAN"
            else "Contract is not on Christiania's explicit cash-settled allow-list."
        )
        return SettlementClassification(
            underlying=symbol,
            settlement_type="UNVERIFIED",
            exercise_style=observed_style or "UNVERIFIED",
            live_eligible=False,
            state=("BLOCKED_ASSIGNMENT_OR_PHYSICAL_RISK" if observed_style == "AMERICAN" else "BLOCKED_UNVERIFIED_SETTLEMENT"),
            reason=reason,
            provenance="FAIL_CLOSED",
            contract_identity_state=contract_identity_state,
            multiplier_state="UNVERIFIED",
        )

    expected_style = policy["exercise_style"]
    if observed_style and observed_style != expected_style:
        return SettlementClassification(
            underlying=symbol,
            settlement_type=policy["settlement_type"],
            exercise_style=observed_style,
            live_eligible=False,
            state="BLOCKED_SETTLEMENT_METADATA_CONFLICT",
            reason=f"Stored exercise style {observed_style} conflicts with the verified {expected_style} product policy.",
            provenance=policy["provenance"],
            contract_identity_state=contract_identity_state,
            multiplier_state="UNVERIFIED",
        )

    if reference_contract_id is None:
        return SettlementClassification(
            underlying=symbol,
            settlement_type=policy["settlement_type"],
            exercise_style=expected_style,
            live_eligible=False,
            state="BLOCKED_CONTRACT_IDENTITY_UNVERIFIED",
            reason="Cash-settled product family is verified, but the exact persisted contract identity is missing.",
            provenance=policy["provenance"],
            contract_identity_state="MISSING_REFERENCE_ID",
            multiplier_state="UNVERIFIED",
        )

    observed_multiplier = None if shares_per_contract is None else float(shares_per_contract)
    expected_multiplier = float(policy["multiplier"])
    if observed_multiplier != expected_multiplier:
        return SettlementClassification(
            underlying=symbol,
            settlement_type=policy["settlement_type"],
            exercise_style=expected_style,
            live_eligible=False,
            state="BLOCKED_CONTRACT_MULTIPLIER_CONFLICT",
            reason=f"Persisted contract multiplier {observed_multiplier!r} does not match verified product multiplier {expected_multiplier:g}.",
            provenance=policy["provenance"],
            contract_identity_state="VERIFIED_REFERENCE_ID",
            multiplier_state="CONFLICT",
        )

    return SettlementClassification(
        underlying=symbol,
        settlement_type=policy["settlement_type"],
        exercise_style=expected_style,
        live_eligible=True,
        state="VERIFIED_CASH_SETTLED",
        reason="Verified cash-settled product with persisted contract identity and expected multiplier; no delivery of underlying shares at settlement.",
        provenance=policy["provenance"],
        contract_identity_state="VERIFIED_REFERENCE_ID",
        multiplier_state="VERIFIED",
    )


def cash_settled_allowlist() -> tuple[str, ...]:
    return tuple(sorted(_CASH_SETTLED_PRODUCTS))
