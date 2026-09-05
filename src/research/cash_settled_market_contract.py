from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from src.providers.thetadata import ThetaDataClient, ThetaDataError
from src.research.live_pipeline import LivePipelineError, parse_thetadata_market_timestamp
from src.research.thetadata_live_adapter import fetch_live_quote_rows

CONTRACT_VERSION = "CASH_SETTLED_MARKET_CONTRACT_V1"
NEW_YORK = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
PRIMARY_V1_SYMBOL = "XSP"
RESEARCH_SYMBOLS = ("SPX", "XSP")
DEFAULT_MAX_QUOTE_AGE_SECONDS = 180.0
DEFAULT_FUTURE_TOLERANCE_SECONDS = 5.0

CBOE_XSP_SPEC = "https://www.cboe.com/tradable_products/sp_500/mini_spx_options/specifications"
CBOE_SPX_SPEC = "https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications"
CBOE_XSP_COMPARISON = "https://www.cboe.com/tradable_products/sp_500/mini_spx_weekly_options/specifications/"


@dataclass(frozen=True)
class ContractSemantics:
    requested_symbol: str
    series_root: str | None
    settlement_type: str
    exercise_style: str
    multiplier: float | None
    settlement_style: str
    settlement_reference_time_et: str | None
    exact_series_identity: bool
    state: str
    reason: str
    source_url: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_evidence_path() -> Path:
    configured = os.environ.get("CHRISTIANIA_CASH_SETTLED_EVIDENCE_PATH")
    if configured and configured.strip():
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "runtime_evidence" / "cash_settled_market_contract_v1.json"


def resolve_contract_semantics(
    requested_symbol: str,
    *,
    series_root: str | None = None,
) -> ContractSemantics:
    requested = str(requested_symbol or "").strip().upper()
    root = str(series_root or "").strip().upper() or None

    if requested == "XSP":
        if root not in {None, "XSP"}:
            return ContractSemantics(
                requested, root, "CASH", "EUROPEAN", 100.0, "PM", "16:00:00",
                False, "SERIES_IDENTITY_CONFLICT",
                f"Theta series root {root} conflicts with requested XSP.", CBOE_XSP_SPEC,
            )
        return ContractSemantics(
            requested, "XSP", "CASH", "EUROPEAN", 100.0, "PM", "16:00:00",
            True, "VERIFIED_PRODUCT_CONTRACT",
            "Cboe specifies XSP as cash-settled, European-style, $100 multiplier and PM-settled.",
            CBOE_XSP_SPEC,
        )

    if requested == "SPX":
        if root is None:
            return ContractSemantics(
                requested, None, "CASH", "EUROPEAN", 100.0, "UNRESOLVED", None,
                False, "SERIES_ROOT_REQUIRED",
                "SPX product-family identity alone is insufficient because SPX and SPXW use different settlement conventions.",
                CBOE_SPX_SPEC,
            )
        if root == "SPX":
            return ContractSemantics(
                requested, root, "CASH", "EUROPEAN", 100.0, "AM", None,
                True, "VERIFIED_PRODUCT_CONTRACT",
                "Standard SPX is AM-settled. Its settlement calculation is opening-price based, so Christiania does not invent a single fixed settlement timestamp.",
                CBOE_SPX_SPEC,
            )
        if root == "SPXW":
            return ContractSemantics(
                requested, root, "CASH", "EUROPEAN", 100.0, "PM", "16:00:00",
                True, "VERIFIED_PRODUCT_CONTRACT",
                "SPXW is the PM-settled SPX series root.", CBOE_SPX_SPEC,
            )
        return ContractSemantics(
            requested, root, "CASH", "EUROPEAN", 100.0, "UNRESOLVED", None,
            False, "SERIES_ROOT_UNRECOGNIZED",
            f"Unrecognized SPX series root {root}; settlement convention is not inferred.", CBOE_SPX_SPEC,
        )

    return ContractSemantics(
        requested or "UNKNOWN", root, "UNVERIFIED", "UNVERIFIED", None,
        "UNRESOLVED", None, False, "UNSUPPORTED_PRODUCT",
        "Product is outside Christiania's V1 cash-settled market-contract registry.", None,
    )


def settlement_reference_at(expiration: str, semantics: ContractSemantics) -> datetime | None:
    if semantics.settlement_reference_time_et is None:
        return None
    day = datetime.fromisoformat(str(expiration)).date()
    clock = time.fromisoformat(semantics.settlement_reference_time_et)
    return datetime.combine(day, clock, tzinfo=NEW_YORK)


def _payload_rows(payload: Any) -> tuple[Any, ...]:
    if isinstance(payload, list):
        return tuple(payload)
    if isinstance(payload, dict) and isinstance(payload.get("response"), list):
        return tuple(payload["response"])
    raise ValueError("Unexpected ThetaData list payload shape.")


def fetch_reference_expirations(client: ThetaDataClient, symbol: str) -> tuple[str, ...]:
    payload = client._get_payload("/option/list/expirations", {"symbol": symbol.upper()})
    values: list[str] = []
    for row in _payload_rows(payload):
        if isinstance(row, Mapping):
            value = row.get("expiration") or row.get("date")
        else:
            value = row
        if value not in {None, ""}:
            values.append(str(value))
    return tuple(dict.fromkeys(values))


def _series_root(row: Mapping[str, Any], requested_symbol: str) -> str | None:
    for key in ("root", "series_root", "option_root", "symbol"):
        value = row.get(key)
        if value not in {None, ""}:
            candidate = str(value).strip().upper()
            if candidate in {"XSP", "SPX", "SPXW"}:
                return candidate
    return "XSP" if requested_symbol.upper() == "XSP" else None


def _number(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value in {None, ""}:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def assess_live_quote_row(
    requested_symbol: str,
    row: Mapping[str, Any],
    *,
    observed_at: datetime,
    max_quote_age_seconds: float = DEFAULT_MAX_QUOTE_AGE_SECONDS,
    future_tolerance_seconds: float = DEFAULT_FUTURE_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")

    root = _series_root(row, requested_symbol)
    semantics = resolve_contract_semantics(requested_symbol, series_root=root)
    blockers: list[str] = []
    if not semantics.exact_series_identity:
        blockers.append(semantics.state)

    raw_timestamp = row.get("raw_timestamp") or row.get("timestamp") or row.get("quote_timestamp")
    quote_age = None
    parsed_timestamp = None
    if raw_timestamp in {None, ""}:
        blockers.append("QUOTE_TIMESTAMP_MISSING")
    else:
        try:
            parsed = parse_thetadata_market_timestamp(str(raw_timestamp))
        except LivePipelineError:
            blockers.append("QUOTE_TIMESTAMP_INVALID")
        else:
            parsed_timestamp = parsed.isoformat()
            quote_age = (observed_at.astimezone(NEW_YORK) - parsed).total_seconds()
            if quote_age < -future_tolerance_seconds:
                blockers.append("QUOTE_TIMESTAMP_IN_FUTURE")
            elif quote_age > max_quote_age_seconds:
                blockers.append("QUOTE_STALE")

    bid = _number(row, "bid", "bid_price")
    ask = _number(row, "ask", "ask_price")
    if bid is None or ask is None:
        blockers.append("NBBO_MISSING")
    elif bid < 0 or ask <= 0 or bid > ask:
        blockers.append("NBBO_INVALID")

    expiration = row.get("expiration")
    strike = _number(row, "strike")
    right = str(row.get("right") or "").strip().upper()
    if expiration in {None, ""}:
        blockers.append("EXPIRATION_MISSING")
    else:
        try:
            datetime.fromisoformat(str(expiration))
        except ValueError:
            blockers.append("EXPIRATION_INVALID")
    if strike is None or strike <= 0:
        blockers.append("STRIKE_INVALID")
    if right not in {"C", "P", "CALL", "PUT"}:
        blockers.append("RIGHT_INVALID")

    settlement_at = None
    if expiration not in {None, ""} and semantics.exact_series_identity:
        try:
            resolved = settlement_reference_at(str(expiration), semantics)
        except ValueError:
            resolved = None
        settlement_at = None if resolved is None else resolved.isoformat()

    return {
        "requested_symbol": requested_symbol.upper(),
        "series_root": root,
        "state": "LIVE_VALIDATED" if not blockers else "LIVE_BLOCKED",
        "blockers": blockers,
        "raw_timestamp": raw_timestamp,
        "parsed_timestamp_et": parsed_timestamp,
        "quote_age_seconds": quote_age,
        "bid": bid,
        "ask": ask,
        "expiration": expiration,
        "strike": strike,
        "right": right,
        "settlement_reference_at_et": settlement_at,
        "contract_semantics": semantics.as_dict(),
    }


def _best_live_assessment(symbol: str, rows: Iterable[Mapping[str, Any]], observed_at: datetime) -> dict[str, Any]:
    assessments = [assess_live_quote_row(symbol, row, observed_at=observed_at) for row in rows]
    passing = [item for item in assessments if item["state"] == "LIVE_VALIDATED"]
    if passing:
        return min(passing, key=lambda item: abs(float(item.get("quote_age_seconds") or 0.0)))
    if assessments:
        return min(assessments, key=lambda item: len(item.get("blockers") or []))
    return {
        "requested_symbol": symbol.upper(),
        "state": "LIVE_BLOCKED",
        "blockers": ["NO_QUOTE_ROWS"],
        "contract_semantics": resolve_contract_semantics(symbol).as_dict(),
    }


def build_probe_evidence(
    client: ThetaDataClient,
    *,
    symbols: Iterable[str] = RESEARCH_SYMBOLS,
    mode: str = "reference",
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    probe_mode = str(mode).strip().lower()
    if probe_mode not in {"reference", "live"}:
        raise ValueError("mode must be 'reference' or 'live'")
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")

    result: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "probe_mode": probe_mode,
        "generated_at": now.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "provider": "THETADATA",
        "provider_base_url": client.base_url,
        "primary_v1_symbol": PRIMARY_V1_SYMBOL,
        "symbols": {},
    }

    for raw_symbol in symbols:
        symbol = str(raw_symbol).strip().upper()
        entry: dict[str, Any] = {"requested_symbol": symbol}
        try:
            expirations = fetch_reference_expirations(client, symbol)
        except (ThetaDataError, ValueError) as exc:
            entry.update(state="REFERENCE_BLOCKED", blockers=[type(exc).__name__], error=str(exc))
            result["symbols"][symbol] = entry
            continue

        entry["reference_expiration_count"] = len(expirations)
        entry["reference_sample_expirations"] = list(expirations[:5])
        if not expirations:
            entry.update(state="REFERENCE_BLOCKED", blockers=["NO_EXPIRATIONS"])
            result["symbols"][symbol] = entry
            continue

        if probe_mode == "reference":
            entry.update(state="REFERENCE_PROVEN", blockers=[])
            result["symbols"][symbol] = entry
            continue

        try:
            quote_rows = fetch_live_quote_rows(client, symbol)
        except ThetaDataError as exc:
            entry.update(state="LIVE_BLOCKED", blockers=[type(exc).__name__], error=str(exc))
            result["symbols"][symbol] = entry
            continue

        assessment = _best_live_assessment(symbol, quote_rows, now)
        entry.update(assessment)
        entry["live_quote_row_count"] = len(quote_rows)
        result["symbols"][symbol] = entry

    states = {key: value.get("state") for key, value in result["symbols"].items()}
    live_symbols = sorted(key for key, state in states.items() if state == "LIVE_VALIDATED")
    if probe_mode == "reference":
        overall = "REFERENCE_PROVEN" if states and all(state == "REFERENCE_PROVEN" for state in states.values()) else "REFERENCE_INCOMPLETE"
    elif set(live_symbols) == set(result["symbols"]):
        overall = "LIVE_VALIDATED"
    elif PRIMARY_V1_SYMBOL in live_symbols:
        overall = "LIVE_VALIDATED_XSP_ONLY"
    else:
        overall = "LIVE_PROBE_FAILED"
    result["overall_state"] = overall
    result["live_symbols"] = live_symbols
    result["decision_enabled"] = False
    result["broker_order_path"] = False
    return result


def write_probe_evidence(evidence: Mapping[str, Any], path: Path | None = None) -> Path:
    target = Path(path or default_evidence_path()).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(dict(evidence), indent=2, sort_keys=True) + "\n"
    payload = canonical.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    enriched = dict(evidence)
    enriched["evidence_payload_sha256"] = digest
    final_payload = json.dumps(enriched, indent=2, sort_keys=True) + "\n"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(final_payload, encoding="utf-8", newline="\n")
    temporary.replace(target)
    return target


def read_probe_evidence(path: Path | None = None) -> dict[str, Any] | None:
    target = Path(path or default_evidence_path()).expanduser()
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("contract_version") != CONTRACT_VERSION:
        return None
    return payload
