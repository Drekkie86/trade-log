from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.database.repository import get_connection

UTC = ZoneInfo("UTC")

BUILDER_FAMILY_ID = "LOCAL_IV_BUTTERFLY_EXPRESSION_V1"
BUILDER_VERSION = "1.0.0"
BUILDER_RULE_VERSION = "LOCAL_IV_BUTTERFLY_RULES_V1"
STRUCTURE_VERSION = "1.0.0"

RISK_CURRENCY = "USD"


class ShadowStructureBridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class StructureLeg:
    reference_contract_id: int
    option_quote_id: int
    strike: float
    right: str
    quantity: int
    side: str
    entry_price: float
    shares_per_contract: float


@dataclass(frozen=True)
class ShadowStructureProposal:
    hypothesis_evaluation_id: int
    research_run_id: int
    target_reference_contract_id: int
    underlying: str
    expiration: str
    right: str
    target_strike: float
    anomaly_direction: str
    proposal_state: str
    reason_code: str
    structure_id: str | None
    legs: tuple[StructureLeg, ...]
    net_debit_per_share: float | None
    max_theoretical_loss_minor: int | None
    risk_currency: str | None
    risk_basis: str | None
    persisted_proposal_id: int | None = None


@dataclass(frozen=True)
class ShadowStructureBridgeResult:
    hypothesis_scanner_run_id: int
    surfaced_count: int
    proposed_count: int
    blocked_count: int
    proposals: tuple[ShadowStructureProposal, ...]


def _now_utc() -> str:
    return datetime.now(
        UTC
    ).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _entry_price(
    *,
    side: str,
    bid: float | None,
    ask: float | None,
) -> float | None:
    if side == "BUY":
        return (
            None
            if ask is None
            else float(ask)
        )

    if side == "SELL":
        return (
            None
            if bid is None
            else float(bid)
        )

    raise ValueError(
        f"Unsupported side: {side}"
    )


def _intrinsic(
    *,
    right: str,
    strike: float,
    underlying_price: float,
) -> float:
    if right == "C":
        return max(
            underlying_price - strike,
            0.0,
        )

    if right == "P":
        return max(
            strike - underlying_price,
            0.0,
        )

    raise ValueError(
        f"Unsupported right: {right}"
    )


def _terminal_payoff_bounds(
    *,
    legs: tuple[StructureLeg, ...],
) -> tuple[int, float, float]:
    if not legs:
        raise ValueError(
            "At least one leg is required."
        )

    multipliers = {
        float(
            leg.shares_per_contract
        )
        for leg in legs
    }

    if len(multipliers) != 1:
        raise ShadowStructureBridgeError(
            "Leg contract multipliers differ."
        )

    multiplier = multipliers.pop()

    if multiplier <= 0:
        raise ShadowStructureBridgeError(
            "Invalid contract multiplier."
        )

    net_debit_per_share = sum(
        (
            leg.entry_price
            if leg.side == "BUY"
            else -leg.entry_price
        )
        * abs(leg.quantity)
        for leg in legs
    )

    strikes = sorted(
        {
            leg.strike
            for leg in legs
        }
    )

    width = max(strikes) - min(strikes)

    # Piecewise-linear option payoff reaches extrema at strike breakpoints
    # or in the constant tails. These probe points cover those regions.
    probe_prices = [
        0.0,
        *strikes,
        max(strikes) + max(width, 1.0),
    ]

    pnl_per_share = []

    for spot in probe_prices:
        terminal_payoff = sum(
            (
                1
                if leg.side == "BUY"
                else -1
            )
            * abs(leg.quantity)
            * _intrinsic(
                right=leg.right,
                strike=leg.strike,
                underlying_price=spot,
            )
            for leg in legs
        )

        pnl_per_share.append(
            terminal_payoff
            - net_debit_per_share
        )

    worst = min(
        pnl_per_share
    )
    best = max(
        pnl_per_share
    )

    max_loss = max(
        0.0,
        -worst,
    ) * multiplier

    minor = int(
        round(
            max_loss * 100
        )
    )

    return (
        minor,
        net_debit_per_share,
        best,
    )


def _load_surfaced(
    *,
    hypothesis_scanner_run_id: int,
    db_path=None,
) -> list[dict[str, Any]]:
    conn = get_connection(db_path)

    try:
        rows = conn.execute(
            """
            SELECT
                hse.id AS hypothesis_evaluation_id,
                hsr.research_run_id,
                hse.reference_contract_id
                    AS target_reference_contract_id,
                hse.option_quote_id
                    AS target_option_quote_id,
                hse.underlying,
                hse.expiration,
                hse.right,
                hse.strike AS target_strike,
                hse.lower_strike,
                hse.upper_strike,
                hse.surfaced_direction,
                ms.id AS market_snapshot_id
            FROM hypothesis_scanner_evaluations AS hse
            JOIN hypothesis_scanner_runs AS hsr
              ON hsr.id = hse.scanner_run_id
            JOIN option_quotes AS oq
              ON oq.id = hse.option_quote_id
            JOIN market_snapshots AS ms
              ON ms.id = oq.snapshot_id
            WHERE hse.scanner_run_id = ?
              AND hse.evaluation_state = 'SURFACED'
            ORDER BY
                hse.underlying,
                hse.expiration,
                hse.right,
                hse.strike;
            """,
            (
                hypothesis_scanner_run_id,
            ),
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]
    finally:
        conn.close()


def _load_leg(
    *,
    research_run_id: int,
    market_snapshot_id: int,
    underlying: str,
    expiration: str,
    right: str,
    strike: float,
    db_path=None,
) -> dict[str, Any] | None:
    conn = get_connection(db_path)

    try:
        rows = conn.execute(
            """
            SELECT
                lrc.id AS reference_contract_id,
                lrc.shares_per_contract,
                oq.id AS option_quote_id,
                oq.bid,
                oq.ask
            FROM listing_reference_contracts AS lrc
            JOIN option_quotes AS oq
              ON oq.snapshot_id = ?
             AND oq.expiration = lrc.expiration
             AND oq.strike = lrc.strike
             AND oq.right = lrc.right
            WHERE lrc.research_run_id = ?
              AND lrc.provider = 'MASSIVE'
              AND lrc.underlying = ?
              AND lrc.expiration = ?
              AND lrc.right = ?
              AND lrc.strike = ?;
            """,
            (
                market_snapshot_id,
                research_run_id,
                underlying,
                expiration,
                right,
                strike,
            ),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return None

    if len(rows) != 1:
        raise ShadowStructureBridgeError(
            "Ambiguous leg identity for "
            f"{underlying} {expiration} {right} {strike}."
        )

    return dict(
        rows[0]
    )


def _blocked(
    row: dict[str, Any],
    *,
    reason_code: str,
) -> ShadowStructureProposal:
    return ShadowStructureProposal(
        hypothesis_evaluation_id=
            int(
                row[
                    "hypothesis_evaluation_id"
                ]
            ),
        research_run_id=
            int(
                row["research_run_id"]
            ),
        target_reference_contract_id=
            int(
                row[
                    "target_reference_contract_id"
                ]
            ),
        underlying=
            str(row["underlying"]),
        expiration=
            str(row["expiration"]),
        right=
            str(row["right"]),
        target_strike=
            float(
                row["target_strike"]
            ),
        anomaly_direction=
            str(
                row["surfaced_direction"]
            ),
        proposal_state=
            "BLOCKED",
        reason_code=
            reason_code,
        structure_id=
            None,
        legs=(),
        net_debit_per_share=
            None,
        max_theoretical_loss_minor=
            None,
        risk_currency=
            None,
        risk_basis=
            None,
    )


def _build_one(
    row: dict[str, Any],
    *,
    db_path=None,
) -> ShadowStructureProposal:
    lower = row["lower_strike"]
    target = row["target_strike"]
    upper = row["upper_strike"]

    if (
        lower is None
        or upper is None
    ):
        return _blocked(
            row,
            reason_code=
                "BRACKETING_STRIKES_MISSING",
        )

    lower = float(lower)
    target = float(target)
    upper = float(upper)

    left_width = target - lower
    right_width = upper - target

    if (
        left_width <= 0
        or right_width <= 0
    ):
        return _blocked(
            row,
            reason_code=
                "INVALID_STRIKE_ORDER",
        )

    if abs(
        left_width - right_width
    ) > 1e-9:
        return _blocked(
            row,
            reason_code=
                "UNEQUAL_WING_WIDTHS",
        )

    if row["surfaced_direction"] == "IV_RICH_LOCAL":
        # Express local richness by selling two target contracts and buying
        # one equal-distance wing on each side: a bounded long butterfly.
        leg_specs = (
            (
                lower,
                1,
                "BUY",
            ),
            (
                target,
                2,
                "SELL",
            ),
            (
                upper,
                1,
                "BUY",
            ),
        )
        structure_id = (
            "LONG_1_2_1_BUTTERFLY"
        )

    elif row["surfaced_direction"] == "IV_CHEAP_LOCAL":
        # Reverse the same bounded structure to express local cheapness.
        leg_specs = (
            (
                lower,
                1,
                "SELL",
            ),
            (
                target,
                2,
                "BUY",
            ),
            (
                upper,
                1,
                "SELL",
            ),
        )
        structure_id = (
            "REVERSE_1_2_1_BUTTERFLY"
        )

    else:
        return _blocked(
            row,
            reason_code=
                "UNSUPPORTED_ANOMALY_DIRECTION",
        )

    legs = []

    for strike, quantity, side in leg_specs:
        source = _load_leg(
            research_run_id=
                int(
                    row["research_run_id"]
                ),
            market_snapshot_id=
                int(
                    row[
                        "market_snapshot_id"
                    ]
                ),
            underlying=
                str(row["underlying"]),
            expiration=
                str(row["expiration"]),
            right=
                str(row["right"]),
            strike=
                float(strike),
            db_path=db_path,
        )

        if source is None:
            return _blocked(
                row,
                reason_code=
                    "STRUCTURE_LEG_NOT_FOUND",
            )

        multiplier = source[
            "shares_per_contract"
        ]

        if multiplier is None:
            return _blocked(
                row,
                reason_code=
                    "CONTRACT_MULTIPLIER_MISSING",
            )

        price = _entry_price(
            side=side,
            bid=source["bid"],
            ask=source["ask"],
        )

        if price is None:
            return _blocked(
                row,
                reason_code=
                    "EXECUTABLE_SIDE_PRICE_MISSING",
            )

        if price < 0:
            return _blocked(
                row,
                reason_code=
                    "NEGATIVE_ENTRY_PRICE",
            )

        legs.append(
            StructureLeg(
                reference_contract_id=
                    int(
                        source[
                            "reference_contract_id"
                        ]
                    ),
                option_quote_id=
                    int(
                        source[
                            "option_quote_id"
                        ]
                    ),
                strike=
                    float(strike),
                right=
                    str(row["right"]),
                quantity=
                    int(quantity),
                side=
                    side,
                entry_price=
                    float(price),
                shares_per_contract=
                    float(multiplier),
            )
        )

    leg_tuple = tuple(
        legs
    )

    try:
        (
            max_loss_minor,
            net_debit_per_share,
            best_terminal_pnl_per_share,
        ) = _terminal_payoff_bounds(
            legs=leg_tuple
        )
    except ShadowStructureBridgeError:
        return _blocked(
            row,
            reason_code=
                "LEG_MULTIPLIER_MISMATCH",
        )

    # A defined-risk structure is not economically meaningful if the
    # conservative entry prices leave no terminal spot at which pre-cost
    # P&L can be positive. Preserve the surfaced anomaly, but block the
    # structure from shadow admission rather than manufacturing a
    # guaranteed-loss research candidate.
    if best_terminal_pnl_per_share <= 0.0:
        return _blocked(
            row,
            reason_code=
                "NON_POSITIVE_TERMINAL_UPSIDE",
        )

    return ShadowStructureProposal(
        hypothesis_evaluation_id=
            int(
                row[
                    "hypothesis_evaluation_id"
                ]
            ),
        research_run_id=
            int(
                row["research_run_id"]
            ),
        target_reference_contract_id=
            int(
                row[
                    "target_reference_contract_id"
                ]
            ),
        underlying=
            str(row["underlying"]),
        expiration=
            str(row["expiration"]),
        right=
            str(row["right"]),
        target_strike=
            target,
        anomaly_direction=
            str(
                row["surfaced_direction"]
            ),
        proposal_state=
            "PROPOSED",
        reason_code=
            "DEFINED_RISK_STRUCTURE_CONSTRUCTED",
        structure_id=
            structure_id,
        legs=
            leg_tuple,
        net_debit_per_share=
            net_debit_per_share,
        max_theoretical_loss_minor=
            max_loss_minor,
        risk_currency=
            RISK_CURRENCY,
        risk_basis=
            (
                "THEORETICAL_EXPIRY_PAYOFF_USING_"
                "CONSERVATIVE_BID_ASK_ENTRY"
            ),
    )


def _persist_one(
    proposal: ShadowStructureProposal,
    *,
    db_path=None,
) -> int:
    structure_json = None
    entry_pricing_json = None

    if proposal.proposal_state == "PROPOSED":
        structure_json = json.dumps(
            {
                "structure_id":
                    proposal.structure_id,
                "structure_version":
                    STRUCTURE_VERSION,
                "legs": [
                    {
                        "reference_contract_id":
                            leg.reference_contract_id,
                        "option_quote_id":
                            leg.option_quote_id,
                        "strike":
                            leg.strike,
                        "right":
                            leg.right,
                        "quantity":
                            leg.quantity,
                        "side":
                            leg.side,
                        "shares_per_contract":
                            leg.shares_per_contract,
                    }
                    for leg in proposal.legs
                ],
            },
            sort_keys=True,
        )

        entry_pricing_json = json.dumps(
            {
                "pricing_basis":
                    "BUY_AT_ASK_SELL_AT_BID",
                "net_debit_per_share":
                    proposal.net_debit_per_share,
                "legs": [
                    {
                        "option_quote_id":
                            leg.option_quote_id,
                        "side":
                            leg.side,
                        "quantity":
                            leg.quantity,
                        "entry_price":
                            leg.entry_price,
                    }
                    for leg in proposal.legs
                ],
            },
            sort_keys=True,
        )

    conn = get_connection(db_path)

    try:
        existing = conn.execute(
            """
            SELECT id
            FROM shadow_structure_proposals
            WHERE hypothesis_evaluation_id = ?
              AND builder_family_id = ?
              AND builder_version = ?;
            """,
            (
                proposal.hypothesis_evaluation_id,
                BUILDER_FAMILY_ID,
                BUILDER_VERSION,
            ),
        ).fetchone()

        if existing is not None:
            return int(
                existing["id"]
            )

        with conn:
            cursor = conn.execute(
                """
                INSERT INTO shadow_structure_proposals (
                    hypothesis_evaluation_id,
                    research_run_id,
                    target_reference_contract_id,
                    underlying,
                    expiration,
                    right,
                    target_strike,
                    builder_family_id,
                    builder_version,
                    builder_rule_version,
                    anomaly_direction,
                    proposal_state,
                    reason_code,
                    structure_id,
                    structure_version,
                    structure_json,
                    entry_pricing_json,
                    risk_currency,
                    max_theoretical_loss_minor,
                    risk_basis,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?
                );
                """,
                (
                    proposal.hypothesis_evaluation_id,
                    proposal.research_run_id,
                    proposal.target_reference_contract_id,
                    proposal.underlying,
                    proposal.expiration,
                    proposal.right,
                    proposal.target_strike,
                    BUILDER_FAMILY_ID,
                    BUILDER_VERSION,
                    BUILDER_RULE_VERSION,
                    proposal.anomaly_direction,
                    proposal.proposal_state,
                    proposal.reason_code,
                    proposal.structure_id,
                    (
                        STRUCTURE_VERSION
                        if proposal.structure_id
                        is not None
                        else None
                    ),
                    structure_json,
                    entry_pricing_json,
                    proposal.risk_currency,
                    proposal.max_theoretical_loss_minor,
                    proposal.risk_basis,
                    _now_utc(),
                ),
            )

        return int(
            cursor.lastrowid
        )
    finally:
        conn.close()


def build_shadow_structure_proposals(
    *,
    hypothesis_scanner_run_id: int,
    persist: bool = True,
    db_path=None,
) -> ShadowStructureBridgeResult:
    surfaced = _load_surfaced(
        hypothesis_scanner_run_id=
            hypothesis_scanner_run_id,
        db_path=db_path,
    )

    proposals = []

    for row in surfaced:
        proposal = _build_one(
            row,
            db_path=db_path,
        )

        if persist:
            proposal_id = _persist_one(
                proposal,
                db_path=db_path,
            )

            proposal = ShadowStructureProposal(
                **{
                    **proposal.__dict__,
                    "persisted_proposal_id":
                        proposal_id,
                }
            )

        proposals.append(
            proposal
        )

    proposed_count = sum(
        item.proposal_state
        == "PROPOSED"
        for item in proposals
    )

    return ShadowStructureBridgeResult(
        hypothesis_scanner_run_id=
            hypothesis_scanner_run_id,
        surfaced_count=
            len(surfaced),
        proposed_count=
            proposed_count,
        blocked_count=
            len(proposals)
            - proposed_count,
        proposals=
            tuple(proposals),
    )
