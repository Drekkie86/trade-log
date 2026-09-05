from __future__ import annotations

from dataclasses import asdict, dataclass

from src.version import CHRISTIANIA_VERSION


@dataclass(frozen=True)
class AcceptanceCheck:
    name: str
    state: str
    blocking: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReleaseAcceptance:
    version: str
    state: str
    release_candidate_ready: bool
    checks: tuple[AcceptanceCheck, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "state": self.state,
            "release_candidate_ready": self.release_candidate_ready,
            "checks": [c.as_dict() for c in self.checks],
        }


def assess_release_candidate(
    *,
    product_ready: bool,
    runtime_ready: bool,
    secure_edge_ready: bool,
    restore_drill_passed: bool,
    release_manifest_clean: bool,
    burn_in_state: str,
    reboot_proven: bool,
    theta_timestamp_confidence: str | None,
    require_burn_in: bool = True,
    require_reboot: bool = True,
    require_live_timestamp_validation: bool = True,
) -> ReleaseAcceptance:
    checks: list[AcceptanceCheck] = []

    def add(name: str, ok: bool, detail: str, *, blocking: bool = True) -> None:
        checks.append(AcceptanceCheck(name, "PASS" if ok else ("FAIL" if blocking else "INFO"), blocking, detail))

    add("product-readiness", product_ready, "Product readiness gate is green.")
    add("runtime-readiness", runtime_ready, "Daemon, Theta and database runtime are healthy.")
    add("secure-web-edge", secure_edge_ready, "HTTPS/OIDC secure edge is configured and validated.")
    add("restore-drill", restore_drill_passed, "Verified backup restore drill passed.")
    add("release-manifest", release_manifest_clean, "Release manifest is pinned to a clean Git state.")
    add(
        "burn-in",
        burn_in_state == "PASSED",
        f"Burn-in state: {burn_in_state}.",
        blocking=require_burn_in,
    )
    add(
        "reboot-proof",
        reboot_proven,
        "A real host reboot was proven by Linux boot-id change.",
        blocking=require_reboot,
    )
    timestamp_ok = theta_timestamp_confidence == "DOCUMENTED_AND_LIVE_VALIDATED"
    add(
        "theta-timestamp-live-validation",
        timestamp_ok,
        f"Theta timestamp confidence: {theta_timestamp_confidence or 'UNKNOWN'}.",
        blocking=require_live_timestamp_validation,
    )

    blocked = any(c.blocking and c.state == "FAIL" for c in checks)
    return ReleaseAcceptance(
        version=CHRISTIANIA_VERSION,
        state="V1_RC_READY" if not blocked else "V1_RC_NOT_READY",
        release_candidate_ready=not blocked,
        checks=tuple(checks),
    )
