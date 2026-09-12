from __future__ import annotations

from dataclasses import asdict, dataclass


MIB = 1024**2


@dataclass(frozen=True)
class ServiceResourcePolicy:
    unit: str
    memory_warning_bytes: int
    memory_high_bytes: int
    memory_max_bytes: int
    timeout_start_seconds: int
    timeout_stop_seconds: int = 90
    oom_policy: str = "stop"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _mib(value: int) -> int:
    return value * MIB


SERVICE_RESOURCE_POLICIES: dict[str, ServiceResourcePolicy] = {
    "christiania-app.service": ServiceResourcePolicy(
        unit="christiania-app.service",
        memory_warning_bytes=_mib(384),
        memory_high_bytes=_mib(512),
        memory_max_bytes=_mib(1024),
        timeout_start_seconds=90,
    ),
    "christiania-daemon.service": ServiceResourcePolicy(
        unit="christiania-daemon.service",
        memory_warning_bytes=_mib(512),
        memory_high_bytes=_mib(768),
        memory_max_bytes=_mib(1280),
        timeout_start_seconds=90,
    ),
    "christiania-theta.service": ServiceResourcePolicy(
        unit="christiania-theta.service",
        memory_warning_bytes=_mib(1024),
        memory_high_bytes=_mib(1536),
        memory_max_bytes=_mib(2560),
        timeout_start_seconds=90,
    ),
    "christiania-oauth2-proxy.service": ServiceResourcePolicy(
        unit="christiania-oauth2-proxy.service",
        memory_warning_bytes=_mib(128),
        memory_high_bytes=_mib(192),
        memory_max_bytes=_mib(256),
        timeout_start_seconds=90,
    ),
    "christiania-supervisor.service": ServiceResourcePolicy(
        unit="christiania-supervisor.service",
        memory_warning_bytes=_mib(128),
        memory_high_bytes=_mib(192),
        memory_max_bytes=_mib(256),
        timeout_start_seconds=120,
    ),
    "christiania-theta-watchdog.service": ServiceResourcePolicy(
        unit="christiania-theta-watchdog.service",
        memory_warning_bytes=_mib(96),
        memory_high_bytes=_mib(128),
        memory_max_bytes=_mib(192),
        timeout_start_seconds=45,
    ),
    "christiania-theta-recover.service": ServiceResourcePolicy(
        unit="christiania-theta-recover.service",
        memory_warning_bytes=_mib(128),
        memory_high_bytes=_mib(192),
        memory_max_bytes=_mib(256),
        timeout_start_seconds=180,
    ),
    "christiania-theta-refresh.service": ServiceResourcePolicy(
        unit="christiania-theta-refresh.service",
        memory_warning_bytes=_mib(128),
        memory_high_bytes=_mib(192),
        memory_max_bytes=_mib(256),
        timeout_start_seconds=300,
    ),
    "christiania-health.service": ServiceResourcePolicy(
        unit="christiania-health.service",
        memory_warning_bytes=_mib(256),
        memory_high_bytes=_mib(384),
        memory_max_bytes=_mib(512),
        timeout_start_seconds=180,
    ),
    "christiania-audit.service": ServiceResourcePolicy(
        unit="christiania-audit.service",
        memory_warning_bytes=_mib(512),
        memory_high_bytes=_mib(768),
        memory_max_bytes=_mib(1024),
        timeout_start_seconds=1800,
    ),
    "christiania-backup.service": ServiceResourcePolicy(
        unit="christiania-backup.service",
        memory_warning_bytes=_mib(512),
        memory_high_bytes=_mib(768),
        memory_max_bytes=_mib(1024),
        timeout_start_seconds=3600,
    ),
    "christiania-restore-drill.service": ServiceResourcePolicy(
        unit="christiania-restore-drill.service",
        memory_warning_bytes=_mib(768),
        memory_high_bytes=_mib(1024),
        memory_max_bytes=_mib(1536),
        timeout_start_seconds=3600,
    ),
    "christiania-burn-in.service": ServiceResourcePolicy(
        unit="christiania-burn-in.service",
        memory_warning_bytes=_mib(256),
        memory_high_bytes=_mib(384),
        memory_max_bytes=_mib(512),
        timeout_start_seconds=180,
    ),
    "christiania-v1-readiness.service": ServiceResourcePolicy(
        unit="christiania-v1-readiness.service",
        memory_warning_bytes=_mib(256),
        memory_high_bytes=_mib(384),
        memory_max_bytes=_mib(512),
        timeout_start_seconds=180,
    ),
}


def service_resource_policy(
    unit: str,
) -> ServiceResourcePolicy:
    try:
        return SERVICE_RESOURCE_POLICIES[unit]
    except KeyError as exc:
        raise KeyError(
            f"No Christiania resource policy is defined for {unit!r}."
        ) from exc


def managed_service_units() -> tuple[str, ...]:
    return tuple(SERVICE_RESOURCE_POLICIES)


def systemd_dropin_text(
    policy: ServiceResourcePolicy,
) -> str:
    return (
        "[Service]\n"
        f"MemoryHigh={policy.memory_high_bytes}\n"
        f"MemoryMax={policy.memory_max_bytes}\n"
        f"TimeoutStartSec={policy.timeout_start_seconds}s\n"
        f"TimeoutStopSec={policy.timeout_stop_seconds}s\n"
        f"OOMPolicy={policy.oom_policy}\n"
    )