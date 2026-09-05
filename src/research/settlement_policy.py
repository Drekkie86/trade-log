from __future__ import annotations

from dataclasses import asdict, dataclass

from src.research.cash_settled_market_contract import resolve_contract_semantics


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
    series_root: str | None
    settlement_style: str
    settlement_reference_time_et: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def classify_settlement(
    underlying: str | None,
    *,
    observed_exercise_style: str | None = None,
    reference_contract_id: int | None = None,
    shares_per_contract: float | None = None,
    series_root: str | None = None,
) -> SettlementClassification:
    symbol = str(underlying or "").strip().upper()
    observed_style = str(observed_exercise_style or "").strip().upper()
    identity_state = "VERIFIED_REFERENCE_ID" if reference_contract_id is not None else "MISSING_REFERENCE_ID"
    semantics = resolve_contract_semantics(symbol, series_root=series_root)

    if semantics.state == "UNSUPPORTED_PRODUCT":
        reason = (
            "American-style contract is outside Christiania's explicit cash-settled registry."
            if observed_style == "AMERICAN"
            else "Contract is outside Christiania's explicit cash-settled registry."
        )
        return SettlementClassification(
            symbol or "UNKNOWN", "UNVERIFIED", observed_style or "UNVERIFIED", False,
            "BLOCKED_ASSIGNMENT_OR_PHYSICAL_RISK" if observed_style == "AMERICAN" else "BLOCKED_UNVERIFIED_SETTLEMENT",
            reason, "FAIL_CLOSED", identity_state, "UNVERIFIED", semantics.series_root,
            semantics.settlement_style, semantics.settlement_reference_time_et,
        )

    if not semantics.exact_series_identity:
        return SettlementClassification(
            symbol, semantics.settlement_type, semantics.exercise_style, False,
            "BLOCKED_SERIES_IDENTITY_UNVERIFIED",
            semantics.reason, semantics.source_url or "FAIL_CLOSED", identity_state,
            "UNVERIFIED", semantics.series_root, semantics.settlement_style,
            semantics.settlement_reference_time_et,
        )

    if observed_style and observed_style != semantics.exercise_style:
        return SettlementClassification(
            symbol, semantics.settlement_type, observed_style, False,
            "BLOCKED_SETTLEMENT_METADATA_CONFLICT",
            f"Stored exercise style {observed_style} conflicts with verified {semantics.exercise_style} product semantics.",
            semantics.source_url or "FAIL_CLOSED", identity_state, "UNVERIFIED",
            semantics.series_root, semantics.settlement_style, semantics.settlement_reference_time_et,
        )

    if reference_contract_id is None:
        return SettlementClassification(
            symbol, semantics.settlement_type, semantics.exercise_style, False,
            "BLOCKED_CONTRACT_IDENTITY_UNVERIFIED",
            "Cash-settled product semantics are verified, but the exact persisted contract identity is missing.",
            semantics.source_url or "FAIL_CLOSED", "MISSING_REFERENCE_ID", "UNVERIFIED",
            semantics.series_root, semantics.settlement_style, semantics.settlement_reference_time_et,
        )

    observed_multiplier = None if shares_per_contract is None else float(shares_per_contract)
    expected_multiplier = semantics.multiplier
    if observed_multiplier != expected_multiplier:
        return SettlementClassification(
            symbol, semantics.settlement_type, semantics.exercise_style, False,
            "BLOCKED_CONTRACT_MULTIPLIER_CONFLICT",
            f"Persisted contract multiplier {observed_multiplier!r} does not match verified product multiplier {expected_multiplier:g}.",
            semantics.source_url or "FAIL_CLOSED", "VERIFIED_REFERENCE_ID", "CONFLICT",
            semantics.series_root, semantics.settlement_style, semantics.settlement_reference_time_et,
        )

    return SettlementClassification(
        symbol, semantics.settlement_type, semantics.exercise_style, True,
        "VERIFIED_CASH_SETTLED",
        "Verified cash-settled series with persisted contract identity and expected multiplier; no delivery of underlying shares at settlement.",
        semantics.source_url or "CBOE_PRODUCT_CONTRACT", "VERIFIED_REFERENCE_ID", "VERIFIED",
        semantics.series_root, semantics.settlement_style, semantics.settlement_reference_time_et,
    )


def cash_settled_allowlist() -> tuple[str, ...]:
    return ("SPX", "XSP")
