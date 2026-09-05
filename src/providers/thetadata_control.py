from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse

from src.config import get_runtime_setting
from urllib.request import Request, urlopen

from src.providers.thetadata import ThetaDataClient

DEFAULT_THETA_BASE_URL = "http://127.0.0.1:25503/v3"
DEFAULT_PROBE_SYMBOL = "AAPL"
DEFAULT_PROBE_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class ThetaTerminalHealth:
    state: str
    base_url: str
    probe_symbol: str
    latency_ms: float | None
    detail: str
    http_status: int | None
    contract_json_valid: bool

    @property
    def ready(self) -> bool:
        return self.state == "READY"

    def as_dict(self) -> dict[str, object]:
        return asdict(self) | {"ready": self.ready}


def _validate_theta_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)

    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != "/v3"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Theta base URL must be a local HTTP v3 endpoint such as "
            "http://127.0.0.1:25503/v3."
        )

    return normalized


def configured_theta_base_url() -> str:
    raw = get_runtime_setting(
        "CHRISTIANIA_THETA_BASE_URL"
    )
    return _validate_theta_base_url(
        raw or DEFAULT_THETA_BASE_URL
    )


def configured_theta_client() -> ThetaDataClient:
    return ThetaDataClient(base_url=configured_theta_base_url())


def _probe_url(base_url: str, symbol: str) -> str:
    return (
        base_url.rstrip("/")
        + "/stock/list/dates/quote?"
        + urlencode({"symbol": symbol.upper(), "format": "json"})
    )


def _default_probe_transport(
    url: str,
    timeout: float,
) -> tuple[int, bytes]:
    request = Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except HTTPError as exc:
        return int(exc.code), exc.read()
    except URLError as exc:
        raise ConnectionError(str(exc.reason)) from exc


ProbeTransport = Callable[[str, float], tuple[int, bytes]]


def probe_theta_terminal(
    *,
    base_url: str | None = None,
    symbol: str = DEFAULT_PROBE_SYMBOL,
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    transport: ProbeTransport = _default_probe_transport,
) -> ThetaTerminalHealth:
    try:
        resolved = (
            configured_theta_base_url()
            if base_url is None
            else _validate_theta_base_url(base_url)
        )
    except ValueError as exc:
        return ThetaTerminalHealth(
            state="CONFIG_ERROR",
            base_url=(
                get_runtime_setting("CHRISTIANIA_THETA_BASE_URL")
                or str(base_url or "")
                or DEFAULT_THETA_BASE_URL
            ),
            probe_symbol=symbol.upper(),
            latency_ms=None,
            detail=str(exc),
            http_status=None,
            contract_json_valid=False,
        )

    started = time.perf_counter()

    try:
        status, raw = transport(
            _probe_url(resolved, symbol),
            timeout_seconds,
        )
    except (ConnectionError, TimeoutError, OSError) as exc:
        return ThetaTerminalHealth(
            state="UNREACHABLE",
            base_url=resolved,
            probe_symbol=symbol.upper(),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            detail=f"Theta Terminal could not be reached: {exc}",
            http_status=None,
            contract_json_valid=False,
        )

    latency_ms = (time.perf_counter() - started) * 1000.0

    if status != 200:
        body = raw.decode("utf-8", errors="replace")[:300]
        return ThetaTerminalHealth(
            state="HTTP_ERROR",
            base_url=resolved,
            probe_symbol=symbol.upper(),
            latency_ms=latency_ms,
            detail=f"Theta API returned HTTP {status}: {body}",
            http_status=status,
            contract_json_valid=False,
        )

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return ThetaTerminalHealth(
            state="CONTRACT_ERROR",
            base_url=resolved,
            probe_symbol=symbol.upper(),
            latency_ms=latency_ms,
            detail=f"Theta API returned non-JSON content: {exc}",
            http_status=status,
            contract_json_valid=False,
        )

    valid_contract = (
        isinstance(payload, list)
        or (
            isinstance(payload, dict)
            and isinstance(payload.get("response"), list)
        )
    )

    if not valid_contract:
        return ThetaTerminalHealth(
            state="CONTRACT_ERROR",
            base_url=resolved,
            probe_symbol=symbol.upper(),
            latency_ms=latency_ms,
            detail=(
                "Theta API returned JSON, but not the documented list "
                "or response-list shape."
            ),
            http_status=status,
            contract_json_valid=False,
        )

    return ThetaTerminalHealth(
        state="READY",
        base_url=resolved,
        probe_symbol=symbol.upper(),
        latency_ms=latency_ms,
        detail=(
            "Theta Terminal v3 HTTP API returned valid JSON from the "
            "read-only list-dates readiness probe."
        ),
        http_status=status,
        contract_json_valid=True,
    )


def wait_for_theta_terminal(
    *,
    wait_seconds: float,
    poll_seconds: float = 2.0,
    base_url: str | None = None,
    symbol: str = DEFAULT_PROBE_SYMBOL,
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    transport: ProbeTransport = _default_probe_transport,
) -> ThetaTerminalHealth:
    if wait_seconds < 0:
        raise ValueError("wait_seconds cannot be negative.")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive.")

    deadline = monotonic() + wait_seconds
    health = probe_theta_terminal(
        base_url=base_url,
        symbol=symbol,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )

    while not health.ready:
        if health.state == "CONFIG_ERROR":
            return health

        remaining = deadline - monotonic()
        if remaining <= 0:
            return health
        sleep(min(poll_seconds, remaining))
        health = probe_theta_terminal(
            base_url=base_url,
            symbol=symbol,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    return health
