from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

from src.config import get_runtime_setting

DEFAULT_MAX_GAP_MINUTES = 30.0


@dataclass(frozen=True)
class BurnInSample:
    observed_at: str
    boot_id: str
    database_ready: bool
    daemon_state: str
    theta_state: str
    backup_valid: bool
    market_state: str | None
    latest_iteration_status: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BurnInReport:
    state: str
    sample_count: int
    first_observed_at: str | None
    last_observed_at: str | None
    duration_hours: float
    unhealthy_samples: int
    max_gap_minutes: float | None
    reboot_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def resolve_burn_in_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    configured = get_runtime_setting("CHRISTIANIA_BURN_IN_LOG")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "audit_exports" / "v1_burn_in.jsonl"


def append_burn_in_sample(sample: BurnInSample, path: str | Path | None = None) -> Path:
    target = resolve_burn_in_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(sample.as_dict(), sort_keys=True) + "\n")
    return target


def read_burn_in_samples(path: str | Path | None = None) -> tuple[BurnInSample, ...]:
    target = resolve_burn_in_path(path)
    if not target.is_file():
        return ()
    samples: list[BurnInSample] = []
    for lineno, raw in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        payload = json.loads(raw)
        try:
            samples.append(BurnInSample(**payload))
        except TypeError as exc:
            raise ValueError(f"Invalid burn-in record at line {lineno}") from exc
    return tuple(samples)


def summarize_burn_in(
    samples: Iterable[BurnInSample],
    *,
    required_hours: float = 72.0,
    max_gap_minutes: float = DEFAULT_MAX_GAP_MINUTES,
) -> BurnInReport:
    ordered = sorted(samples, key=lambda s: s.observed_at)
    if not ordered:
        return BurnInReport("NO_DATA", 0, None, None, 0.0, 0, None, 0)

    times = [datetime.fromisoformat(s.observed_at.replace("Z", "+00:00")).astimezone(UTC) for s in ordered]
    duration = max(0.0, (times[-1] - times[0]).total_seconds() / 3600.0)
    gaps = [
        (b - a).total_seconds() / 60.0
        for a, b in zip(times, times[1:])
    ]
    max_gap = max(gaps) if gaps else 0.0
    unhealthy = sum(
        not (
            s.database_ready
            and s.daemon_state == "HEALTHY"
            and s.theta_state == "READY"
            and s.backup_valid
        )
        for s in ordered
    )
    boot_ids = [s.boot_id for s in ordered if s.boot_id and not s.boot_id.startswith("UNAVAILABLE:")]
    reboots = sum(a != b for a, b in zip(boot_ids, boot_ids[1:]))

    if unhealthy:
        state = "UNHEALTHY_SAMPLES_PRESENT"
    elif max_gap > max_gap_minutes:
        state = "OBSERVATION_GAP"
    elif duration < required_hours:
        state = "ACCUMULATING"
    else:
        state = "PASSED"

    return BurnInReport(
        state=state,
        sample_count=len(ordered),
        first_observed_at=ordered[0].observed_at,
        last_observed_at=ordered[-1].observed_at,
        duration_hours=duration,
        unhealthy_samples=unhealthy,
        max_gap_minutes=max_gap,
        reboot_count=reboots,
    )
