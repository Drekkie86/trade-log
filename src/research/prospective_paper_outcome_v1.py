"""Prospective paper option package outcome assessment, *offline and pure*.

This evaluator does not create fills, mutate a database, set outcome_eligible=1,
or claim a complex-order execution. It is a deterministic, quoted-leg P&L
bridge on independently acquired, as-of evidence, with fail-closed gates.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

VERSION = "CHRISTIANIA_PROSPECTIVE_PAPER_OUTCOME_V1"
MAX_QUOTE_AGE_S = 15
MAX_CROSS_LEG_SKEW_S = 15
MAX_QUOTE_CAPTURE_AGE_S = 15
MAX_FX_AGE_S = 86400  # A declared *maximum*, not a claim about current Saxo FX.
USD_CENT = Decimal("0.01")
EUR_CENT = Decimal("0.01")


def D(x: Any) -> Decimal:
    try:
        v = Decimal(str(x))
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("INVALID_DECIMAL") from exc
    if not v.is_finite():
        raise ValueError("NONFINITE_DECIMAL")
    return v


def aware(x: str) -> datetime:
    try:
        val = datetime.fromisoformat(x.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("TIMESTAMP_UNPARSEABLE") from exc
    if val.tzinfo is None or val.utcoffset() is None:
        raise ValueError("TIMESTAMP_TIMEZONE_MISSING")
    return val.astimezone(timezone.utc)


def minor(v: Decimal) -> int:
    return int((v * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class OptionLeg:
    contract_id: str
    right: str  # C / P
    strike: str
    expiration: str
    multiplier: str
    side: str  # entry BUY / SELL
    quantity: int


@dataclass(frozen=True)
class LegQuote:
    contract_id: str
    right: str
    strike: str
    expiration: str
    multiplier: str
    bid: str
    ask: str
    bid_size: str
    ask_size: str
    quote_at: str   # VERIFIED absolute source timestamp (not ambiguous ET)
    bid_at: str
    ask_at: str
    source_id: str  # immutable provider observation ID, not invented
    snapshot_id: str
    captured_at: str
    provider: str


@dataclass(frozen=True)
class Phase:
    decision_at: str
    quotes: tuple[LegQuote, ...]
    entry_or_exit: str  # "ENTRY" or "EXIT"
    fx_eur_to_usd: str
    fx_observed_at: str
    fx_source: str
    commission_usd: str
    extra_slippage_usd: str
    taxes_usd: str
    fee_provenance: str
    timestamp_validation_ref: str  # independent verified live ThetaData record


@dataclass(frozen=True)
class PaperPackage:
    candidate_id: int
    strategy_id: str
    frozen_signal_version: str
    preregistration_hash: str
    prospective_session: str
    legs: tuple[OptionLeg, ...]
    entry: Phase
    exit: Phase
    exit_rule_id: str
    # Independent package fill / firm complex-order execution verification is
    # a future, separate gate. This object NEVER satisfies that requirement.


@dataclass(frozen=True)
class PaperResult:
    status: str
    reasons: tuple[str, ...]
    gross_pnl_usd_minor: int | None
    estimated_net_pnl_usd_minor: int | None
    estimated_net_pnl_eur_minor: int | None
    entry_cashflow_usd_minor: int | None
    exit_cashflow_usd_minor: int | None
    applied_cost_usd_minor: int | None
    usable_for_strategy_edge: bool
    validated_package_outcome: bool
    outcome_eligible: bool
    evidence_hash_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate(package: PaperPackage) -> PaperResult:
    """Fail closed and never promote independently valued leg quotes to fills."""
    serialized = json.dumps(asdict(package), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    errors: set[str] = set()

    def reason(code: str) -> None:
        errors.add(code)

    def finish(status: str, *vals: int | None) -> PaperResult:
        return PaperResult(
            status=status, reasons=tuple(sorted(errors)),
            gross_pnl_usd_minor=vals[0] if vals else None,
            estimated_net_pnl_usd_minor=vals[1] if vals else None,
            estimated_net_pnl_eur_minor=vals[2] if vals else None,
            entry_cashflow_usd_minor=vals[3] if vals else None,
            exit_cashflow_usd_minor=vals[4] if vals else None,
            applied_cost_usd_minor=vals[5] if vals else None,
            usable_for_strategy_edge=False,
            validated_package_outcome=False,
            outcome_eligible=False,
            evidence_hash_sha256=digest,
        )

    if (type(package.candidate_id) is not int or package.candidate_id <= 0
            or not package.strategy_id.strip() or
            not package.frozen_signal_version.strip() or
            not package.exit_rule_id.strip()):
        reason("MISSING_CANONICAL_ID_OR_FROZEN_RULE")
    if (len(package.preregistration_hash) != 64 or
            any(ch not in "0123456789abcdef" for ch in package.preregistration_hash)):
        reason("PREREGISTRATION_HASH_NOT_FROZEN")
    if not (2 <= len(package.legs) <= 8):
        reason("STRUCTURE_LEG_COUNT_INVALID")
    if len({l.contract_id for l in package.legs}) != len(package.legs):
        reason("DUPLICATE_STRUCTURE_CONTRACT_ID")
    if any(l.right not in ("C", "P") or l.side not in ("BUY", "SELL") or
           type(l.quantity) is not int or l.quantity < 1 or
           not l.contract_id or not l.expiration for l in package.legs):
        reason("INVALID_OPTION_LEG")
    try:
        multipliers = {D(l.multiplier) for l in package.legs}
        expirations = {l.expiration for l in package.legs}
        if any(D(l.strike) <= 0 for l in package.legs) or \
           any(m <= 0 for m in multipliers) or \
           len(multipliers) != 1 or len(expirations) != 1:
            reason("INVALID_STRIKE_MULTIPLIER_OR_MIXED_EXPIRY")
        if len(expirations) == 1 and (
                datetime.fromisoformat(next(iter(expirations))).date() <
                aware(package.exit.decision_at).date()):
            reason("EXIT_AFTER_OPTION_EXPIRATION")
        entry_time = aware(package.entry.decision_at)
        exit_time = aware(package.exit.decision_at)
        if exit_time <= entry_time:
            reason("EXIT_NOT_AFTER_ENTRY")
        if (datetime.fromisoformat(package.prospective_session).date() >
                entry_time.date()):
            reason("PROSPECTIVE_SESSION_AFTER_ENTRY")
    except (ValueError, TypeError):
        reason("TIME_OR_CONTRACT_INPUT_INVALID")
        entry_time = exit_time = None
    if errors:
        return finish("NOT_EVALUABLE")

    by_id = {l.contract_id: l for l in package.legs}
    phases: list[tuple[Phase, Decimal, Decimal, Decimal]] = []
    for phase in (package.entry, package.exit):
        expected_name = "ENTRY" if not phases else "EXIT"
        if phase.entry_or_exit != expected_name:
            reason("PHASE_SEQUENCE_INVALID")
        if len(phase.quotes) != len(package.legs):
            reason("INCOMPLETE_QUOTE_POPULATION")
            continue
        qbyid = {q.contract_id: q for q in phase.quotes}
        if len(qbyid) != len(phase.quotes) or set(qbyid) != set(by_id):
            reason("QUOTE_CONTRACT_SET_MISMATCH")
            continue
        if len({q.snapshot_id for q in phase.quotes}) != 1:
            reason("LEGS_NOT_FROM_ONE_SNAPSHOT")
        if len({q.source_id for q in phase.quotes}) != len(phase.quotes):
            reason("DUPLICATE_SOURCE_QUOTE_ID")
        if not phase.timestamp_validation_ref.strip():
            reason("INDEPENDENT_LIVE_TIMESTAMP_VERIFICATION_MISSING")
        if not phase.fee_provenance.strip() or not phase.fx_source.strip():
            reason("COST_OR_FX_PROVENANCE_MISSING")
        try:
            timestamp = aware(phase.decision_at)
            fx_time = aware(phase.fx_observed_at)
            rate = D(phase.fx_eur_to_usd)
            fee = sum((D(phase.commission_usd), D(phase.extra_slippage_usd),
                       D(phase.taxes_usd)), Decimal(0))
            if rate <= 0 or any(D(x) < 0 for x in (
                    phase.commission_usd, phase.extra_slippage_usd, phase.taxes_usd)):
                reason("NEGATIVE_COST_OR_INVALID_FX")
            age_fx = (timestamp - fx_time).total_seconds()
            if age_fx < 0 or age_fx > MAX_FX_AGE_S:
                reason("FX_TIMESTAMP_FUTURE_OR_STALE")
            leg_instants: list[datetime] = []
            total = Decimal(0)
            for leg in package.legs:
                q = qbyid[leg.contract_id]
                if (q.right != leg.right or q.expiration != leg.expiration or
                        D(q.strike) != D(leg.strike) or
                        D(q.multiplier) != D(leg.multiplier)):
                    reason("QUOTE_CONTRACT_IDENTITY_DRIFT")
                if not q.source_id.strip() or not q.snapshot_id.strip() or \
                   q.provider != "THETADATA":
                    reason("PROVIDER_SOURCE_PROVENANCE_MISSING")
                bid, ask, bs, az = (
                    D(q.bid), D(q.ask), D(q.bid_size), D(q.ask_size))
                if bid < 0 or ask < bid or bs < 0 or az < 0:
                    reason("INVALID_BID_ASK_OR_DEPTH")
                times = [aware(x) for x in
                         (q.quote_at, q.bid_at, q.ask_at, q.captured_at)]
                quote_t, bid_t, ask_t, capture_t = times
                leg_instants.extend(times[:3])
                if any(t > timestamp for t in times):
                    reason("LOOKAHEAD_OR_FUTURE_SOURCE")
                if any(t > capture_t for t in times[:3]):
                    reason("QUOTE_SOURCE_AFTER_CAPTURE")
                if ((timestamp - capture_t).total_seconds() >
                        MAX_QUOTE_CAPTURE_AGE_S or
                        any((timestamp-t).total_seconds() > MAX_QUOTE_AGE_S for t in times[:3])):
                    reason("STALE_LEG_OR_SNAPSHOT")
                entry = phase.entry_or_exit == "ENTRY"
                trade_side = leg.side if entry else ("SELL" if leg.side == "BUY" else "BUY")
                if trade_side == "BUY":
                    if az < leg.quantity:
                        reason("MISSING_BUY_SIDE_SIZE")
                    price = ask
                    sign = Decimal(-1)
                else:
                    if bs < leg.quantity:
                        reason("MISSING_SELL_SIDE_SIZE")
                    price = bid
                    sign = Decimal(1)
                total += sign * price * D(leg.multiplier) * D(leg.quantity)
            if (leg_instants and
                    (max(leg_instants)-min(leg_instants)).total_seconds() >
                    MAX_CROSS_LEG_SKEW_S):
                reason("ASYNCHRONOUS_LEG_QUOTES")
            phases.append((phase,total,fee,rate))
        except (ValueError, InvalidOperation, TypeError, KeyError):
            reason("QUOTE_PRICE_TIME_OR_COST_UNPARSEABLE")
    if errors or len(phases) != 2:
        return finish("NOT_EVALUABLE")

    (entry_phase, entry_cash, entry_cost, entry_fx), (
        exit_phase, exit_cash, exit_cost, exit_fx) = phases
    gross = entry_cash + exit_cash
    net = gross - entry_cost - exit_cost
    # Convert each cash movement at its own frozen contemporaneous FX rate.
    net_eur = (entry_cash-entry_cost)/entry_fx + (exit_cash-exit_cost)/exit_fx
    reason("NO_INDEPENDENT_EXECUTABLE_PACKAGE_FILL_VERIFICATION")
    return finish(
        "PAPER_LEG_QUOTE_STRESS_ONLY",
        minor(gross), minor(net), minor(net_eur),
        minor(entry_cash), minor(exit_cash), minor(entry_cost+exit_cost)
    )
