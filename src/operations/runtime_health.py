from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta


DAEMON_HEARTBEAT_MAX_AGE = timedelta(minutes=3)


@dataclass(frozen=True)
class DaemonHealth:
    state: str
    heartbeat_at: str | None
    heartbeat_age_seconds: float | None
    max_heartbeat_age_seconds: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    ).astimezone(UTC)


def assess_daemon_health(
    daemon_lock: dict | None,
    *,
    now: datetime | None = None,
    max_age: timedelta = DAEMON_HEARTBEAT_MAX_AGE,
) -> DaemonHealth:
    if max_age <= timedelta(0):
        raise ValueError(
            "max_age must be positive."
        )

    observed_at = (
        datetime.now(UTC)
        if now is None
        else now.astimezone(UTC)
    )

    if daemon_lock is None:
        return DaemonHealth(
            state="NO_DAEMON_LEASE",
            heartbeat_at=None,
            heartbeat_age_seconds=None,
            max_heartbeat_age_seconds=max_age.total_seconds(),
        )

    raw_heartbeat = daemon_lock.get(
        "heartbeat_at"
    )

    if not raw_heartbeat:
        return DaemonHealth(
            state="INVALID_DAEMON_LEASE",
            heartbeat_at=None,
            heartbeat_age_seconds=None,
            max_heartbeat_age_seconds=max_age.total_seconds(),
        )

    try:
        heartbeat = _parse_utc(
            str(raw_heartbeat)
        )
    except ValueError:
        return DaemonHealth(
            state="INVALID_DAEMON_LEASE",
            heartbeat_at=str(raw_heartbeat),
            heartbeat_age_seconds=None,
            max_heartbeat_age_seconds=max_age.total_seconds(),
        )

    age_seconds = max(
        0.0,
        (observed_at - heartbeat).total_seconds(),
    )

    state = (
        "HEALTHY"
        if age_seconds <= max_age.total_seconds()
        else "STALE_DAEMON_LEASE"
    )

    return DaemonHealth(
        state=state,
        heartbeat_at=str(raw_heartbeat),
        heartbeat_age_seconds=age_seconds,
        max_heartbeat_age_seconds=max_age.total_seconds(),
    )
