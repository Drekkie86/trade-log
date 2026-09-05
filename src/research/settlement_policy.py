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

    def as_dict(self) -> dict:
        return asdict(self)


# V1 intentionally uses a tiny, explicit allow-list. Unknown contracts fail
# closed. These product-level facts were checked against Cboe product pages on
# 2026-09-05; runtime code does not fetch the web or infer settlement from a
# ticker pattern.
_CASH_SETTLED_PRODUCTS = {
    "SPX": {
        "settlement_type": "CASH",
        "exercise_style": "EUROPEAN",
        "provenance": "CBOE_SPX_PRODUCT_PAGE_VERIFIED_2026-09-05",
    },
    "XSP": {
        "settlement_type": "CASH",
        "exercise_style": "EUROPEAN",
        "provenance": "CBOE_XSP_PRODUCT_PAGE_VERIFIED_2026-09-05",
    },
}


def classify_settlement(
    underlying: str | None,
    *,
    observed_exercise_style: str | None = None,
) -> SettlementClassification:
    symbol = str(underlying or "").strip().upper()
    observed_style = str(observed_exercise_style or "").strip().upper()

    if not symbol:
        return SettlementClassification(
            underlying="UNKNOWN",
            settlement_type="UNVERIFIED",
            exercise_style=observed_style or "UNVERIFIED",
            live_eligible=False,
            state="BLOCKED_UNVERIFIED_SETTLEMENT",
            reason="Contract underlying is missing; cash settlement cannot be verified.",
            provenance="FAIL_CLOSED",
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
            state=(
                "BLOCKED_ASSIGNMENT_OR_PHYSICAL_RISK"
                if observed_style == "AMERICAN"
                else "BLOCKED_UNVERIFIED_SETTLEMENT"
            ),
            reason=reason,
            provenance="FAIL_CLOSED",
        )

    expected_style = policy["exercise_style"]
    if observed_style and observed_style != expected_style:
        return SettlementClassification(
            underlying=symbol,
            settlement_type=policy["settlement_type"],
            exercise_style=observed_style,
            live_eligible=False,
            state="BLOCKED_SETTLEMENT_METADATA_CONFLICT",
            reason=(
                f"Stored exercise style {observed_style} conflicts with the verified "
                f"{expected_style} product policy."
            ),
            provenance=policy["provenance"],
        )

    return SettlementClassification(
        underlying=symbol,
        settlement_type=policy["settlement_type"],
        exercise_style=expected_style,
        live_eligible=True,
        state="VERIFIED_CASH_SETTLED",
        reason="Verified cash-settled product; no delivery of underlying shares at settlement.",
        provenance=policy["provenance"],
    )


def cash_settled_allowlist() -> tuple[str, ...]:
    return tuple(sorted(_CASH_SETTLED_PRODUCTS))
