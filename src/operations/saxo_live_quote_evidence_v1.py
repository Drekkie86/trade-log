"""Single-symbol Saxo LIVE stock/OPRA quote qualification, never order execution.

This module ONLY makes the four bounded read-only requests:
  option root -> one calendar expiry -> stock InfoPrice -> option InfoPrice.
Saxo InfoPrices are **not** executable multi-leg prices. Even a confirmed
live firm quote is a broker reference, not a trade recommendation.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src.providers.saxo import (
    SAXO_LIVE_BASE_URL, SaxoApiAuthenticationError, SaxoClient,
    SaxoError, SaxoNetworkError, SaxoOptionQuote, SaxoUnderlyingQuote,
    SaxoRateLimitError,
)
from src.providers.saxo_auth import (
    SaxoAuthenticationError, get_saxo_live_access_token,
)

NEW_YORK = ZoneInfo("America/New_York")
MAX_SOURCE_AGE_SECONDS = 15
MAX_ONE_EXPIRY_CONTRACTS = 2000
PREFERRED_SYMBOL = "AAPL"
VERSION = "SAXO_LIVE_SPOT_OPRA_EVIDENCE_V1"


@dataclass(frozen=True)
class QuoteProof:
    state: str
    detail: str
    delayed_by_minutes: int | None
    market_state: str | None
    last_updated: str | None
    bid_ask_present: bool
    sizes_present: bool


@dataclass(frozen=True)
class SaxoFeedProof:
    state: str
    detail: str
    symbol: str
    checked_at: str
    stock: QuoteProof | None
    option: QuoteProof | None
    sampled_expiry: str | None = None
    option_contract_size: float | None = None
    evidence_source: str = "SAXO_LIVE_OPENAPI_INFOPRICES"
    order_authority: bool = False
    broker_fill_verified: bool = False
    environment: str = "LIVE"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _date(raw: str | None) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _trading_session_window(now: datetime) -> bool:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AS_OF_TIME_MUST_HAVE_TIMEZONE")
    ny = now.astimezone(NEW_YORK)
    return (
        ny.weekday() < 5
        and time(9, 30) <= ny.time().replace(tzinfo=None) < time(16, 0)
    )


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def _expiries(now: datetime) -> tuple[str, ...]:
    """Up to two distant monthly series, chosen before seeing any quotes."""
    current = now.astimezone(NEW_YORK).date()
    results: list[str] = []
    for move in range(1, 5):
        ix = (current.year * 12 + current.month - 1) + move
        y, m = divmod(ix, 12)
        candidate = _third_friday(y, m + 1)
        if 14 <= (candidate - current).days <= 100:
            results.append(candidate.isoformat())
        if len(results) >= 2:
            break
    return tuple(results)


def qualify_quote(
    quote: SaxoOptionQuote | SaxoUnderlyingQuote,
    *,
    now: datetime,
) -> QuoteProof:
    """Checks delay, market state, genuine sides/sizes, timestamp and types.

    Never mark a closed, delayed, indicative or missing-status quote
    executable, even if broker's basic QuoteQuality reports EXECUTABLE.
    """
    market = str(quote.market_state or "").strip().upper()
    t = _date(quote.last_updated)
    bid, ask = quote.bid, quote.ask
    sizes = quote.bid_size, quote.ask_size
    bidask = (
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            and math.isfinite(x) and x > 0 for x in (bid, ask))
        and bid <= ask
    )
    size_ok = all(
        isinstance(x, (int, float)) and not isinstance(x, bool)
        and math.isfinite(x) and x > 0 for x in sizes
    )

    def proof(state: str, detail: str):
        return QuoteProof(
            state, detail, quote.delayed_by_minutes,
            quote.market_state, quote.last_updated, bidask, size_ok,
        )

    types = " ".join(str(x or "").upper().replace("_", "") for x in (
        quote.price_type_bid, quote.price_type_ask,
    ))
    error_code = str(quote.error_code or "None").upper().replace("_", "")
    if "NOACCESS" in types or error_code == "NOACCESS":
        return proof("NO_ACCESS", "Saxo does not grant price access.")
    if error_code in {"NOMARKET", "PENDING"}:
        return proof("NO_MARKET_QUOTE", "Saxo reports no current market price.")
    if error_code not in {"NONE", ""}:
        return proof("PROVIDER_PRICE_ERROR", "Saxo returned a quote-level error.")
    if "OLDINDICATIVE" in types:
        return proof("OLD_INDICATIVE", "Saxo supplied an old indicative price.")
    delay = quote.delayed_by_minutes
    if delay is not None and delay > 0:
        return proof("DELAYED", "Saxo reports delayed market data.")
    if delay is None or isinstance(delay, bool) or delay < 0:
        return proof("DELAY_UNKNOWN", "Saxo did not certify a real-time feed.")
    if not _trading_session_window(now) or market != "OPEN":
        return proof(
            "SESSION_CLOSED_OR_UNKNOWN",
            "No active US continuous-market quote can be verified.",
        )
    if t is None:
        return proof("CLOCK_UNKNOWN", "Quote has no valid provider timestamp.")
    age = (now.astimezone(UTC) - t).total_seconds()
    if age < -2 or age > MAX_SOURCE_AGE_SECONDS:
        return proof("STALE", "Quote is outside the live reference time window.")
    if not bidask or not size_ok:
        return proof("NO_TWO_SIDED_DEPTH", "Fresh bid, ask and positive sizes are missing.")
    if any(x in types for x in ("INDICATIVE", "OLD")):
        return proof(
            "REALTIME_INDICATIVE",
            "Real-time indicative quote; executable package fill not established.",
        )
    source_type = str(quote.price_source_type or "").strip().upper()
    if source_type != "FIRM":
        return proof(
            "REALTIME_SOURCE_UNCONFIRMED",
            "Live quote received, but provider did not mark it firm.",
        )
    return proof(
        "REALTIME_FIRM_REFERENCE",
        "Fresh two-sided firm InfoPrice; multi-leg execution still unverified.",
    )


def _sample_option(space: dict[str, Any], *, stock_mid: float | None):
    expiries = space.get("OptionSpace")
    if not isinstance(expiries, list) or len(expiries) > 4:
        return None
    choices: list[tuple[dict, dict]] = [
        (series, opt)
        for series in expiries if isinstance(series, dict)
        for opt in series.get("SpecificOptions", [])
        if isinstance(opt, dict)
        and type(opt.get("Uic")) is int and opt["Uic"] > 0
        and isinstance(opt.get("StrikePrice"), (int, float))
        and math.isfinite(opt["StrikePrice"]) and opt["StrikePrice"] > 0
        and str(opt.get("PutCall", "")).lower() == "call"
        and type(opt.get("UnderlyingUic")) is int
        and opt["UnderlyingUic"] > 0
    ]
    if not choices or len(choices) > MAX_ONE_EXPIRY_CONTRACTS:
        return None
    strikes = sorted(opt["StrikePrice"] for _, opt in choices)
    center = stock_mid if stock_mid and math.isfinite(stock_mid) else strikes[len(strikes)//2]
    return min(
        choices,
        key=lambda pair: (
            abs(float(pair[1]["StrikePrice"])-center),
            int(pair[1]["Uic"]),
        ),
    )


def probe_saxo_spot_opra(
    *,
    now: datetime | None = None,
    symbol: str = PREFERRED_SYMBOL,
    client_factory: Callable[..., SaxoClient] = SaxoClient,
    token_provider: Callable[..., str] = get_saxo_live_access_token,
    clock: Callable[[], datetime] | None = None,
) -> SaxoFeedProof:
    """Bounded LIVE diagnostics. Qualify both quotes at one final observation cut."""
    clock = clock or (lambda: now if now is not None else datetime.now(UTC))
    now = now or clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AS_OF_TIME_MUST_HAVE_TIMEZONE")
    if symbol not in {"AAPL", "SPY", "IWM"}:
        raise ValueError("SYMBOL_NOT_PREDECLARED")
    def result(state, detail, stock=None, option=None, expiry=None, multiplier=None,
               assessed_at=None):
        return SaxoFeedProof(
            state, detail, symbol,
            (assessed_at or now).isoformat(timespec="seconds"),
            stock, option, expiry, multiplier,
        )
    # Do not make extra provider calls while the US market is closed; a
    # closed-market zero-delay quote cannot prove that we have OPRA rights.
    if not _trading_session_window(now):
        return result(
            "MARKET_CLOSED_UNVERIFIED",
            "Market is closed; no real-time stock/OPRA entitlement claim made.",
        )
    try:
        client = client_factory(
            token_provider=token_provider,
            base_url=SAXO_LIVE_BASE_URL,
            timeout_seconds=8,
        )
        root = client.find_option_root(symbol)
        root_id = root.get("Identifier")
        if type(root_id) is not int or root_id <= 0:
            return result("NO_OPTION_ROOT", "No unambiguous OPRA option root.")
        for expiry in _expiries(now):
            space = client.get_option_space(root_id, expiration=expiry)
            chosen = _sample_option(space, stock_mid=None)
            if chosen is None:
                continue
            series, opt = chosen
            stock = client.get_underlying_quote(opt["UnderlyingUic"])
            if (
                stock.reference_price is not None
                and math.isfinite(stock.reference_price)
                and stock.reference_price > 0
            ):
                preferred = _sample_option(space, stock_mid=stock.reference_price)
                if preferred is not None:
                    series, opt = preferred
            option_quote = client.get_option_quote(opt["Uic"])
            # Validate both sources against one actual decision cut, AFTER
            # all requests; a slow lookup must not make old quotes live.
            assessment_cut = clock()
            stock_proof = qualify_quote(stock, now=assessment_cut)
            option_proof = qualify_quote(option_quote, now=assessment_cut)
            raw_mult = space.get("ContractSize")
            multiplier = (
                float(raw_mult)
                if isinstance(raw_mult, (int, float)) and not isinstance(raw_mult, bool)
                and math.isfinite(raw_mult) and raw_mult > 0
                else None
            )
            if (
                stock_proof.state == "REALTIME_FIRM_REFERENCE"
                and option_proof.state == "REALTIME_FIRM_REFERENCE"
                and multiplier is not None
            ):
                return result(
                    "LIVE_TWO_SIDED_REFERENCE",
                    "Stock and one OPRA option returned live firm InfoPrices. "
                    "Multi-leg price, commissions, and execution still unverified.",
                    stock_proof, option_proof, expiry, multiplier,
                    assessed_at=assessment_cut,
                )
            return result(
                "PARTIAL_OR_UNVERIFIED",
                "At least one required stock/OPRA quote failed the strict live-source gate.",
                stock_proof, option_proof, expiry, multiplier,
                assessed_at=assessment_cut,
            )
        return result(
            "NO_LISTED_SAMPLE",
            "No bounded listed OPRA call sample for the predeclared expiries.",
        )
    except SaxoApiAuthenticationError as exc:
        return result(
            "LOGIN_OR_PERMISSION_REQUIRED",
            "Saxo rejected an authenticated read-only market-data lookup "
            f"(HTTP {exc.status_code}).",
        )
    except SaxoRateLimitError:
        return result("RATE_LIMITED", "Saxo rate limit prevented the probe.")
    except SaxoNetworkError:
        return result("UNREACHABLE", "Saxo OpenAPI could not be reached.")
    except (SaxoAuthenticationError, SaxoError, ValueError, TypeError, OSError):
        return result(
            "DATA_SOURCE_FAILED",
            "The Saxo reference/quote probe failed; no prices accepted.",
        )
