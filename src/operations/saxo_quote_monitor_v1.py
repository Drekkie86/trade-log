"""Operational Saxo market-data heartbeat; never a trade signal.

Only read-only reference/InfoPrice requests during US continuous-market
hours. Outside session it records MARKET_CLOSED_UNVERIFIED without any
Saxo requests. The report contains no IDs, credentials, order actions or
raw account/provider payloads; System UI reads this tiny file offline.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from src.operations.saxo_live_quote_evidence_v1 import (
    SaxoFeedProof, probe_saxo_spot_opra,
)

STATUS_PATH = Path("/var/lib/christiania/data/saxo_feed_status_v1.json")
MAX_REPORT_BYTES = 12 * 1024
MAX_CHECK_AGE = timedelta(minutes=85)
VALID_STATES = frozenset({
    "MARKET_CLOSED_UNVERIFIED", "NO_OPTION_ROOT",
    "NO_LISTED_SAMPLE", "PARTIAL_OR_UNVERIFIED",
    "LIVE_TWO_SIDED_REFERENCE", "LOGIN_OR_PERMISSION_REQUIRED",
    "RATE_LIMITED", "UNREACHABLE", "DATA_SOURCE_FAILED",
})


def _utc(value: str) -> datetime | None:
    try:
        x = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return x.astimezone(UTC) if x.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def persist_quote_status(
    proof: SaxoFeedProof,
    *,
    path: Path = STATUS_PATH,
) -> None:
    if proof.state not in VALID_STATES:
        raise ValueError("UNKNOWN_FEED_STATUS")
    target = Path(path)
    if target.is_symlink() or not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("INVALID_STATUS_DESTINATION")
    # Keep only redacted provider/source diagnostics; report must not
    # contain any account keys, bearer tokens or raw response bodies.
    body = json.dumps(proof.as_dict(), sort_keys=True, separators=(",", ":"))
    if len(body.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("OVERSIZE_FEED_STATUS")
    fd, name = tempfile.mkstemp(
        prefix=".saxo_feed_status_", dir=str(target.parent),
        suffix=".tmp",
    )
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(body + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, target)
        if os.name != "nt":
            os.chmod(target, 0o600)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_quote_status(
    *,
    path: Path = STATUS_PATH,
    now: datetime | None = None,
) -> dict[str, object]:
    """Bounded read; stale or suspicious evidence never turns green."""
    now = now or datetime.now(UTC)
    target = Path(path)
    unavailable = {
        "state": "UNVERIFIED",
        "detail": "No current Saxo stock/OPRA sample has been verified.",
    }
    try:
        if (target.is_symlink() or not target.is_file()
            or target.stat().st_size > MAX_REPORT_BYTES):
            return unavailable
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("state") not in VALID_STATES:
            return unavailable
        if payload.get("environment", "LIVE") != "LIVE":
            # Any invented SIM report must not support LIVE trading decisions.
            return unavailable
        if payload.get("order_authority") is not False:
            return unavailable
        if payload.get("broker_fill_verified") is not False:
            return unavailable
        asof = _utc(payload.get("checked_at"))
        if asof is None or asof > now + timedelta(seconds=30):
            return unavailable
        if now.astimezone(UTC) - asof > MAX_CHECK_AGE:
            return {"state": "STALE", "detail": "Saxo stock/OPRA sample is outdated."}
        return {
            "state": payload["state"],
            "detail": str(payload.get("detail") or "")[:240],
            "checked_at": payload["checked_at"],
            "stock_state": (
                payload.get("stock", {}).get("state")
                if isinstance(payload.get("stock"), dict) else None
            ),
            "option_state": (
                payload.get("option", {}).get("state")
                if isinstance(payload.get("option"), dict) else None
            ),
        }
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return unavailable


def run_market_data_heartbeat(
    *,
    probe: Callable[[], SaxoFeedProof] = probe_saxo_spot_opra,
    path: Path = STATUS_PATH,
) -> str:
    proof = probe()
    persist_quote_status(proof, path=path)
    return proof.state


def main() -> int:
    state = run_market_data_heartbeat()
    # A missing subscription is a trading-data blocker, not an outage
    # of the independent research collector or a reason to restart Saxo.
    print(json.dumps({"market_data_state": state, "order_authority": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
