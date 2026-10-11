"""Saxo native multi-leg PRICE-ONLY observation, never an order.

Endpoint allowlist contains exactly POST /trade/v1/prices/multileg.
Saxo documentation distinguishes this from /trade/v2/orders/multileg.
Explicit off-by-default request. No DB writes, trades or validated outcomes.
"""
from __future__ import annotations

import hashlib
import json
import math
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src.operations.market_calendar import get_market_session
from src.providers.saxo import SAXO_LIVE_BASE_URL, SAXO_SIM_BASE_URL

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
VERSION = "SAXO_NATIVE_MULTILEG_PRICE_RESEARCH_V1"
PRICE_ONLY_ROUTE = "/trade/v1/prices/multileg"
MAX_LEGS = 4
MAX_ASOF_AGE_SECONDS = 15
MAX_PRICE_REQUEST_SECONDS = 10
MAX_HTTP_TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class NativePriceLeg:
    saxo_uic: int
    quantity: int
    side: str  # BUY / SELL


@dataclass(frozen=True)
class NativePackageQuote:
    status: str
    reasons: tuple[str, ...]
    observed_at: str
    request_completed_at: str
    strategy_bid: float | None
    strategy_ask: float | None
    strategy_bid_size: float | None
    strategy_ask_size: float | None
    quote_age_seconds: float | None
    strategy_price_source: str | None
    quoted_legs: int
    source_model: str
    price_only: bool
    broker_package_fill_verified: bool
    outcome_eligible: bool
    trading_enabled: bool
    evidence_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("TIMEZONE_OFFSET_MISSING")
    return parsed.astimezone(UTC)


def _quote_result(
    *,
    when: datetime,
    completed: datetime,
    reasons: set[str],
    price: dict[str, Any] | None = None,
    quoted_legs: int = 0,
) -> NativePackageQuote:
    info=price or {}
    status=("BROKER_PACKAGE_PRICE_REFERENCE_ONLY" if not reasons
            else "UNVERIFIED_OR_UNAVAILABLE_PACKAGE_PRICE")
    safe={
        "model":VERSION,
        "state":status,
        "time":when.isoformat(),
        "completed_at":completed.isoformat(),
        "errors":sorted(reasons),
        "quoted_legs":quoted_legs,
        "price":info,
    }
    digest=hashlib.sha256(json.dumps(
        safe, sort_keys=True, separators=(",", ":"),allow_nan=False
    ).encode("utf-8")).hexdigest()
    return NativePackageQuote(
        status=status,reasons=tuple(sorted(reasons)),
        observed_at=when.isoformat(),request_completed_at=completed.isoformat(),
        strategy_bid=info.get("bid"),strategy_ask=info.get("ask"),
        strategy_bid_size=info.get("bid_size"),
        strategy_ask_size=info.get("ask_size"),
        quote_age_seconds=info.get("age"),
        strategy_price_source=info.get("price_source"),
        quoted_legs=quoted_legs,source_model=VERSION,
        price_only=True,broker_package_fill_verified=False,
        outcome_eligible=False,trading_enabled=False,
        evidence_sha256=digest,
    )


def _http_price_transport(
    url: str, body: dict[str, Any], token: str, timeout_seconds: float
) -> dict[str, Any]:
    # HTTP POST is required for pricing; this is NOT a broker-order POST.
    if not any(url == base+PRICE_ONLY_ROUTE for base in
               (SAXO_LIVE_BASE_URL,SAXO_SIM_BASE_URL)):
        raise ValueError("PRICE_ONLY_URL_ALLOWLIST_VIOLATION")
    req=urllib.request.Request(
        url,
        data=json.dumps(body,sort_keys=True).encode("utf-8"),
        headers={"Authorization":f"Bearer {token}",
                 "Content-Type":"application/json","Accept":"application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req,timeout=min(
        timeout_seconds,MAX_HTTP_TIMEOUT_SECONDS)) as resp:
        content=resp.read(128*1024+1)
        if len(content)>128*1024:
            raise ValueError("PRICE_PAYLOAD_TOO_LARGE")
    value=json.loads(content)
    if not isinstance(value,dict):
        raise ValueError("PRICE_RESPONSE_NOT_OBJECT")
    return value


def observe_multileg_strategy_price(
    *,
    account_key: str,
    legs: tuple[NativePriceLeg, ...],
    saxo_client: Any,
    allow_price_only_post: bool = False,
    clock: Callable[[], datetime] | None = None,
    transport: Callable[[str,dict[str,Any],str,float],dict[str,Any]] | None = None,
) -> NativePackageQuote:
    """At most one explicitly authorized price-only request, no order.

    Important: even an apparently firm native multi-leg price is NOT
    evidence that an order was executed or that an actual P&L was earned.
    """
    now_fn=clock or (lambda:datetime.now(UTC))
    now=now_fn()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("CLOCK_TIMEZONE_MISSING")
    now=now.astimezone(UTC)
    if not allow_price_only_post:
        return _quote_result(when=now,completed=now,
                             reasons={"NATIVE_PACKAGE_PRICING_NOT_AUTHORIZED"})
    if not 2<=len(legs)<=MAX_LEGS:
        return _quote_result(when=now,completed=now,
                             reasons={"NATIVE_PACKAGE_LEG_COUNT_INVALID"})
    if (not isinstance(account_key,str) or not account_key.strip()
            or len(account_key)>256):
        return _quote_result(when=now,completed=now,
                             reasons={"BROKER_ACCOUNT_IDENTITY_MISSING"})
    seen=set()
    for leg in legs:
        if (type(leg.saxo_uic) is not int or leg.saxo_uic<=0
                or leg.saxo_uic in seen or
                type(leg.quantity) is not int or not 1<=leg.quantity<=10
                or leg.side not in ("BUY","SELL")):
            return _quote_result(when=now,completed=now,
                                 reasons={"NATIVE_PACKAGE_LEG_IDENTITY_INVALID"})
        seen.add(leg.saxo_uic)
    session=get_market_session(now.astimezone(NY).date())
    if session is None:
        return _quote_result(when=now,completed=now,reasons={"XNYS_MARKET_CLOSED"})
    if not (_aware(session.sample_window_start)<=now<=
            _aware(session.sample_window_end)):
        return _quote_result(when=now,completed=now,
                             reasons={"OUTSIDE_XNYS_SAMPLE_WINDOW"})
    # The API endpoint supports price-only POST. AccountKey and bearer token
    # are NEVER added to output, hash input, logs or error messages.
    base=getattr(saxo_client,"base_url","").rstrip("/")
    if base not in (SAXO_LIVE_BASE_URL,SAXO_SIM_BASE_URL):
        return _quote_result(when=now,completed=now,
                             reasons={"BROKER_ENDPOINT_NOT_ALLOWLISTED"})
    try:
        token=saxo_client._current_access_token()
    except Exception:
        return _quote_result(when=now,completed=now,
                             reasons={"BROKER_AUTHENTICATION_NOT_AVAILABLE"})
    body={
        "AccountKey":account_key,
        "FieldGroups":["Quote","InstrumentPriceDetails"],
        "Legs":[{
            "Amount":l.quantity,
            "AssetType":"StockOption",
            "BuySell":"Buy" if l.side=="BUY" else "Sell",
            "Uic":l.saxo_uic,
        } for l in legs],
    }
    try:
        response=(transport or _http_price_transport)(
            base+PRICE_ONLY_ROUTE,body,token,MAX_HTTP_TIMEOUT_SECONDS)
    except Exception:
        return _quote_result(when=now,completed=now,
                             reasons={"BROKER_PRICE_ONLY_REQUEST_FAILED"})
    after=now_fn()
    if after.tzinfo is None or after.utcoffset() is None:
        return _quote_result(when=now,completed=now,
                             reasons={"POST_RESPONSE_CLOCK_UNVERIFIED"})
    after=after.astimezone(UTC)
    failures=set()
    info={}
    evidence_count=0
    try:
        if (after<now or
                (after-now).total_seconds()>MAX_PRICE_REQUEST_SECONDS or
                after>_aware(session.sample_window_end)):
            failures.add("PACKAGE_PRICE_COLLECTION_TIME_INVALID_OR_SLOW")
        if not isinstance(response,dict):
            raise ValueError("RESPONSE_NOT_OBJECT")
        entries=response["Legs"]
        if not isinstance(entries,list) or len(entries)!=len(legs):
            failures.add("PACKAGE_LEG_COUNT_MISMATCH")
        else:
            expected={l.saxo_uic:(
                l.quantity,"Buy" if l.side=="BUY" else "Sell") for l in legs}
            actual={}
            for item in entries:
                uic=int(item["Uic"])
                if uic in actual:
                    failures.add("DUPLICATE_PACKAGE_LEG_UIC")
                actual[uic]=(float(item["Amount"]),item["BuySell"])
                if item.get("AssetType")!="StockOption":
                    failures.add("PACKAGE_ASSET_TYPE_MISMATCH")
            if actual != expected:
                failures.add("PACKAGE_LEG_IDENTITY_OR_QUANTITY_MISMATCH")
            evidence_count=len(actual)
        details=response.get("InstrumentPriceDetails") or {}
        if details.get("IsMarketOpen") is not True or (
                details.get("ShortTradeDisabled") is True):
            failures.add("PACKAGE_MARKET_CLOSED_OR_SHORT_DISABLED")
        top_quote=response["Quote"]
        timestamp=_aware(response["LastUpdated"])
        age=(after-timestamp).total_seconds()
        if not 0<=age<=MAX_ASOF_AGE_SECONDS:
            failures.add("PACKAGE_QUOTE_STALE_OR_FUTURE")
        info["age"]=round(age,3)
        if (str(top_quote.get("PriceSourceType","")).strip().upper()!="FIRM"
                or str(top_quote.get("PriceTypeBid","")).strip().upper()!="TRADABLE"
                or str(top_quote.get("PriceTypeAsk","")).strip().upper()!="TRADABLE"
                or top_quote.get("DelayedByMinutes") != 0 or
                top_quote.get("ErrorCode")!="None"):
            failures.add("PACKAGE_QUOTE_NOT_FIRM_OR_NOT_REALTIME")
        source=top_quote.get("PriceSource") or response.get("PriceSource")
        if not source:
            failures.add("PACKAGE_PRICE_SOURCE_MISSING")
        info["price_source"]=str(source) if source else None
        bid=float(top_quote["Bid"])
        ask=float(top_quote["Ask"])
        if not (math.isfinite(bid) and math.isfinite(ask) and bid<=ask):
            failures.add("INVALID_PACKAGE_BID_ASK")
        info["bid"],info["ask"]=(
            bid if math.isfinite(bid) else None,
            ask if math.isfinite(ask) else None)
        # Signed strategy credits may produce negative prices: do not
        # force nonnegative total package debit/credit. Size still required.
        bid_size=top_quote.get("BidSize")
        ask_size=top_quote.get("AskSize")
        if (bid_size is None or ask_size is None or
                not math.isfinite(float(bid_size)) or
                not math.isfinite(float(ask_size)) or
                float(bid_size)<1 or float(ask_size)<1):
            failures.add("PACKAGE_SIZE_OR_DEPTH_NOT_PROVEN")
        else:
            info["bid_size"]=float(bid_size)
            info["ask_size"]=float(ask_size)
    except (KeyError,ValueError,TypeError,OverflowError):
        failures.add("PACKAGE_PRICE_RESPONSE_UNVERIFIABLE")
    return _quote_result(
        when=now,completed=after,reasons=failures,price=info,
        quoted_legs=evidence_count,
    )
