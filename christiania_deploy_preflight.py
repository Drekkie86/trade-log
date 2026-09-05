from __future__ import annotations

import argparse
import json
import importlib.metadata
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import exchange_calendars as xcals

from run_theta_terminal import theta_auth_mode

from src.config import get_runtime_setting
from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    resolve_db_path,
)
from src.providers.thetadata_control import (
    configured_theta_base_url,
    probe_theta_terminal,
)
from src.operations.sqlite_runtime import (
    inspect_database,
    resolve_backup_dir,
)
from src.operations.audit_export import (
    resolve_audit_dir,
)
from src.operations.backup_recovery import (
    inventory_backups,
)


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    state: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _check(
    name: str,
    condition: bool,
    success: str,
    failure: str,
) -> PreflightCheck:
    return PreflightCheck(
        name=name,
        state=(
            "PASS"
            if condition
            else "FAIL"
        ),
        detail=(
            success
            if condition
            else failure
        ),
    )


def run_preflight(*, require_theta_live: bool = False) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []

    checks.append(
        _check(
            "python-version",
            sys.version_info >= (3, 10),
            (
                f"Python {sys.version_info.major}."
                f"{sys.version_info.minor} is supported."
            ),
            "Python 3.10 or newer is required.",
        )
    )

    db_setting = get_runtime_setting(
        "CHRISTIANIA_DB_PATH"
    )
    db_path = resolve_db_path()

    checks.append(
        _check(
            "persistent-db-path",
            bool(db_setting)
            and Path(db_setting).expanduser().is_absolute(),
            f"Configured database path: {db_path}",
            (
                "CHRISTIANIA_DB_PATH must be configured as an "
                "absolute persistent path for cloud deployment."
            ),
        )
    )

    db_health = inspect_database(
        db_path
    )

    checks.append(
        _check(
            "database-health",
            db_health.exists
            and db_health.schema_version == EXPECTED_SCHEMA_VERSION
            and db_health.journal_mode == "wal"
            and db_health.quick_check == "ok"
            and db_health.foreign_key_violation_count == 0,
            (
                f"SQLite v{db_health.schema_version}; WAL; "
                "integrity and foreign keys clean."
            ),
            (
                "Database missing, wrong schema, non-WAL, "
                "or failed integrity checks."
            ),
        )
    )

    backup_setting = get_runtime_setting(
        "CHRISTIANIA_BACKUP_DIR"
    )
    backup_dir = resolve_backup_dir()

    checks.append(
        _check(
            "persistent-backup-path",
            bool(backup_setting)
            and Path(backup_setting).expanduser().is_absolute(),
            f"Configured backup path: {backup_dir}",
            (
                "CHRISTIANIA_BACKUP_DIR must be configured as "
                "an absolute persistent path."
            ),
        )
    )

    same_location = (
        db_path.resolve().parent
        == backup_dir.resolve()
    )

    checks.append(
        _check(
            "backup-separation",
            not same_location,
            "Backup directory is separate from the live DB directory.",
            (
                "Backup directory is the live DB directory. Use a "
                "separate persistent location for recovery resilience."
            ),
        )
    )

    audit_setting = get_runtime_setting(
        "CHRISTIANIA_AUDIT_DIR"
    )
    audit_dir = resolve_audit_dir()
    checks.append(
        _check(
            "persistent-audit-path",
            bool(audit_setting)
            and Path(audit_setting).expanduser().is_absolute(),
            f"Configured audit path: {audit_dir}",
            "CHRISTIANIA_AUDIT_DIR must be configured as an absolute persistent path.",
        )
    )

    backup_inventory = inventory_backups(backup_dir)
    checks.append(
        _check(
            "verified-backup-available",
            backup_inventory.valid_files > 0,
            f"{backup_inventory.valid_files} verified backup(s) available.",
            "No verified Christiania backup is available yet.",
        )
    )

    checks.append(
        _check(
            "massive-secret",
            bool(
                get_runtime_setting(
                    "MASSIVE_API_KEY"
                )
            ),
            "MASSIVE_API_KEY is configured.",
            "MASSIVE_API_KEY is missing.",
        )
    )

    theta_setting = get_runtime_setting(
        "CHRISTIANIA_THETA_JAR"
    )
    theta_path = (
        None
        if not theta_setting
        else Path(theta_setting).expanduser()
    )

    checks.append(
        _check(
            "theta-terminal-jar",
            theta_path is not None
            and theta_path.is_file(),
            f"Theta Terminal jar found: {theta_path}",
            "CHRISTIANIA_THETA_JAR is missing or does not exist.",
        )
    )

    checks.append(
        _check(
            "java-runtime",
            shutil.which("java") is not None,
            "Java executable found on PATH.",
            "Java executable not found on PATH.",
        )
    )

    try:
        auth_mode = theta_auth_mode()
        auth_ok = True
    except RuntimeError as exc:
        auth_mode = str(exc)
        auth_ok = False

    checks.append(
        _check(
            "theta-authentication",
            auth_ok,
            f"Theta authentication mode: {auth_mode}.",
            auth_mode,
        )
    )

    try:
        theta_base_url = configured_theta_base_url()
        theta_url_ok = True
    except ValueError as exc:
        theta_base_url = str(exc)
        theta_url_ok = False

    checks.append(
        _check(
            "theta-local-endpoint",
            theta_url_ok,
            f"Theta API endpoint is local-only: {theta_base_url}",
            f"Invalid Theta API endpoint: {theta_base_url}",
        )
    )

    if require_theta_live:
        theta_health = probe_theta_terminal()
        checks.append(
            _check(
                "theta-live-readiness",
                theta_health.ready,
                theta_health.detail,
                f"{theta_health.state}: {theta_health.detail}",
            )
        )

    try:
        calendar = xcals.get_calendar(
            "XNYS"
        )
        calendar_ok = (
            calendar.is_session(
                "2026-09-04"
            )
            and not calendar.is_session(
                "2026-09-07"
            )
        )
    except Exception:
        calendar_ok = False

    checks.append(
        _check(
            "xnys-calendar",
            calendar_ok,
            "XNYS calendar loaded and Labor Day closure recognized.",
            "XNYS exchange calendar validation failed.",
        )
    )

    try:
        streamlit_version = importlib.metadata.version(
            "streamlit"
        )
    except importlib.metadata.PackageNotFoundError:
        streamlit_version = None

    checks.append(
        _check(
            "streamlit-runtime",
            streamlit_version is not None,
            (
                f"Streamlit {streamlit_version} is installed."
                if streamlit_version is not None
                else "Streamlit is unavailable."
            ),
            "Streamlit runtime is unavailable.",
        )
    )

    symbols = get_runtime_setting(
        "CHRISTIANIA_SYMBOLS"
    )

    checks.append(
        _check(
            "research-universe",
            bool(symbols and symbols.strip()),
            "CHRISTIANIA_SYMBOLS is configured.",
            "CHRISTIANIA_SYMBOLS is missing for service deployment.",
        )
    )

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Christiania one-VM deployment preflight."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
    )
    parser.add_argument(
        "--require-theta-live",
        action="store_true",
        help="Also require a successful live Theta v3 readiness probe.",
    )
    args = parser.parse_args()

    checks = run_preflight(
        require_theta_live=args.require_theta_live
    )
    failed = [
        check
        for check in checks
        if check.state == "FAIL"
    ]

    if args.json:
        print(
            json.dumps(
                {
                    "ready": not failed,
                    "checks": [
                        check.as_dict()
                        for check in checks
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(
            "Christiania deployment preflight"
        )
        print(
            "--------------------------------"
        )

        for check in checks:
            print(
                f"[{check.state}] {check.name}: {check.detail}"
            )

        print()
        print(
            "DEPLOYMENT READY"
            if not failed
            else "DEPLOYMENT NOT READY"
        )

    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
