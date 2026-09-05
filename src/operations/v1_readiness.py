from __future__ import annotations

from dataclasses import asdict, dataclass


BACKUP_MAX_AGE_HOURS = 36.0


@dataclass(frozen=True)
class ReadinessCheck:
    category: str
    name: str
    state: str
    detail: str
    blocking: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class V1Readiness:
    product_state: str
    product_ready: bool
    scientific_state: str
    independent_prospective_dates: int
    checks: tuple[ReadinessCheck, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "product_state": self.product_state,
            "product_ready": self.product_ready,
            "scientific_state": self.scientific_state,
            "independent_prospective_dates": self.independent_prospective_dates,
            "checks": [check.as_dict() for check in self.checks],
        }


def assess_v1_readiness(
    deck: dict,
    backup_inventory: dict,
    *,
    require_runtime: bool = False,
) -> V1Readiness:
    checks: list[ReadinessCheck] = []

    db = deck.get("database", {})
    db_ok = (
        deck.get("ready") is True
        and db.get("quick_check") == "ok"
        and db.get("foreign_key_violation_count") == 0
        and str(db.get("journal_mode", "")).lower() == "wal"
    )
    checks.append(ReadinessCheck(
        "database", "sqlite-health", "PASS" if db_ok else "FAIL",
        "Schema/integrity/FKs/WAL are healthy." if db_ok else "Database health requirements are not satisfied.",
        True,
    ))

    valid_backups = int(backup_inventory.get("valid_files", 0) or 0)
    latest_age = backup_inventory.get("latest_valid_age_hours")
    backup_ok = valid_backups > 0 and latest_age is not None and float(latest_age) <= BACKUP_MAX_AGE_HOURS
    checks.append(ReadinessCheck(
        "recovery", "verified-backup", "PASS" if backup_ok else "FAIL",
        (
            f"Latest valid backup age {float(latest_age):.1f}h."
            if latest_age is not None else "No valid verified backup is available."
        ),
        True,
    ))

    market = deck.get("market_clock", {})
    calendar_ok = bool(market.get("state")) and bool(market.get("next_sample_at") or market.get("session_date"))
    checks.append(ReadinessCheck(
        "schedule", "xnys-calendar", "PASS" if calendar_ok else "FAIL",
        f"Market state: {market.get('state', 'UNKNOWN')}.", True,
    ))

    daemon = deck.get("daemon_health", {})
    daemon_ok = daemon.get("state") == "HEALTHY"
    daemon_blocking = require_runtime
    checks.append(ReadinessCheck(
        "runtime", "research-daemon",
        "PASS" if daemon_ok else ("FAIL" if daemon_blocking else "INFO"),
        f"Daemon state: {daemon.get('state', 'UNKNOWN')}.", daemon_blocking,
    ))

    theta = deck.get("theta_health", {})
    theta_ok = theta.get("ready") is True
    checks.append(ReadinessCheck(
        "provider", "theta-terminal",
        "PASS" if theta_ok else ("FAIL" if require_runtime else "INFO"),
        f"Theta state: {theta.get('state', 'NOT_PROBED')}.", require_runtime,
    ))

    models = deck.get("models", [])
    firewall_ok = bool(models) and all(
        not bool(row.get("admission_enabled")) and not bool(row.get("decision_enabled"))
        for row in models
    )
    checks.append(ReadinessCheck(
        "governance", "model-decision-firewall", "PASS" if firewall_ok else "FAIL",
        "All registered models remain non-decision/non-admission." if firewall_ok else "A model decision/admission flag is enabled.",
        True,
    ))

    dates = int(deck.get("prospective", {}).get("independent_dates", 0) or 0)
    scientific_state = (
        "PREREG_REVIEW_THRESHOLD_REACHED" if dates >= 20
        else "FIRST_DESCRIPTIVE_REVIEW_REACHED" if dates >= 5
        else "PROSPECTIVE_CALIBRATION_ACCUMULATING"
    )
    checks.append(ReadinessCheck(
        "science", "prospective-evidence", "INFO",
        f"{dates} independent prospective date(s); scientific maturity is not a product-readiness gate.",
        False,
    ))

    blockers = [check for check in checks if check.blocking and check.state == "FAIL"]
    product_ready = not blockers
    product_state = "V1_OPERATIONALLY_READY" if product_ready else "V1_NOT_OPERATIONALLY_READY"
    return V1Readiness(
        product_state=product_state, product_ready=product_ready,
        scientific_state=scientific_state, independent_prospective_dates=dates,
        checks=tuple(checks),
    )
