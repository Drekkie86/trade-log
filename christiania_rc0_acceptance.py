from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys

from src.config import load_runtime_env_file
from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.sqlite_runtime import inspect_database


APP_DIR = Path("/opt/christiania")
ENV_FILE = Path("/etc/christiania/christiania.env")
DEPLOYED_COMMIT = APP_DIR / "DEPLOYED_COMMIT"

REQUIRED_UNITS = (
    "christiania-theta.service",
    "christiania-daemon.service",
    "christiania-app.service",
    "christiania-backup.timer",
    "christiania-health.timer",
    "christiania-audit.timer",
    "christiania-restore-drill.timer",
    "christiania-burn-in.timer",
    "christiania-supervisor.timer",
)


@dataclass(frozen=True)
class AcceptanceCheck:
    name: str
    state: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "state": self.state,
            "detail": self.detail,
        }


def _run(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _check(name: str, ok: bool, passed: str, failed: str) -> AcceptanceCheck:
    return AcceptanceCheck(
        name=name,
        state="PASS" if ok else "FAIL",
        detail=passed if ok else failed,
    )


def static_checks(
    *,
    app_dir: Path = APP_DIR,
    env_file: Path = ENV_FILE,
) -> list[AcceptanceCheck]:
    checks: list[AcceptanceCheck] = []

    checks.append(
        _check(
            "app-directory",
            app_dir.is_dir(),
            f"Application directory present: {app_dir}",
            f"Application directory missing: {app_dir}",
        )
    )
    checks.append(
        _check(
            "environment-file",
            env_file.is_file(),
            f"Environment file present: {env_file}",
            f"Environment file missing: {env_file}",
        )
    )

    if env_file.is_file():
        mode = env_file.stat().st_mode & 0o777
        checks.append(
            _check(
                "environment-permissions",
                mode & 0o007 == 0,
                f"Environment file mode {mode:o} excludes world access.",
                f"Environment file mode {mode:o} permits world access.",
            )
        )

    commit_path = app_dir / "DEPLOYED_COMMIT"
    commit = commit_path.read_text(encoding="utf-8").strip() if commit_path.is_file() else ""
    checks.append(
        _check(
            "deployed-commit-marker",
            len(commit) == 40 and all(c in "0123456789abcdef" for c in commit.lower()),
            f"Deployed commit marker: {commit}",
            "Missing or malformed DEPLOYED_COMMIT marker.",
        )
    )

    health_timer = app_dir / "deploy/systemd/christiania-health.timer"
    timer_text = health_timer.read_text(encoding="utf-8") if health_timer.is_file() else ""
    deep_cadence_ok = (
        "OnUnitActiveSec=6h" in timer_text
        and "OnUnitActiveSec=5m" not in timer_text
    )
    checks.append(
        _check(
            "deep-health-cadence",
            deep_cadence_ok,
            "Deep SQLite integrity verification is scheduled every 6h.",
            "Deep health timer cadence is not the RC0 6h policy.",
        )
    )

    return checks


def runtime_checks() -> list[AcceptanceCheck]:
    checks: list[AcceptanceCheck] = []

    db = inspect_database()
    db_ok = (
        db.exists
        and db.schema_version == EXPECTED_SCHEMA_VERSION
        and db.journal_mode == "wal"
        and db.quick_check == "ok"
        and db.foreign_key_violation_count == 0
    )
    checks.append(
        _check(
            "database-deep-health",
            db_ok,
            (
                f"SQLite v{db.schema_version}; WAL; quick_check ok; "
                "foreign keys clean."
            ),
            "Database deep integrity check failed.",
        )
    )

    for unit in REQUIRED_UNITS:
        verb = "is-enabled" if unit.endswith(".timer") else "is-active"
        result = _run(["systemctl", verb, unit], timeout=15)
        actual = (result.stdout or result.stderr).strip()
        expected = "enabled" if verb == "is-enabled" else "active"
        checks.append(
            _check(
                f"systemd:{unit}",
                actual == expected,
                f"{unit} is {expected}.",
                f"{unit} state is {actual!r}, expected {expected!r}.",
            )
        )

    health = _run(
        [
            sys.executable,
            str(APP_DIR / "christiania_health.py"),
            "--strict-daemon",
            "--strict-theta",
            "--strict-backup",
        ],
        timeout=180,
    )
    checks.append(
        _check(
            "strict-health-cli",
            health.returncode == 0,
            "Strict Christiania health check passed.",
            (
                "Strict health failed: "
                + (health.stdout + "\n" + health.stderr)[-1200:]
            ),
        )
    )

    ss = _run(["ss", "-ltnp"], timeout=15)
    listeners = ss.stdout
    forbidden_public = []
    for port in (8501, 25503, 4180):
        token = f":{port}"
        for line in listeners.splitlines():
            if token in line and (
                "0.0.0.0:" in line
                or "[::]:" in line
                or "*:" in line
            ):
                forbidden_public.append(line.strip())
    checks.append(
        _check(
            "private-internal-listeners",
            not forbidden_public,
            "Internal Christiania/Theta/OAuth listener ports are not wildcard-bound.",
            "Wildcard-bound internal ports detected: " + " | ".join(forbidden_public),
        )
    )

    supervisor = _run(
        [
            sys.executable,
            str(APP_DIR / "christiania_rc0_supervisor.py"),
            "--env-file",
            str(ENV_FILE),
            "--json",
            "--no-alert",
        ],
        timeout=90,
    )
    checks.append(
        _check(
            "rc0-supervisor",
            supervisor.returncode == 0,
            "Lightweight RC0 supervisor reports HEALTHY.",
            (
                "Supervisor failed: "
                + (supervisor.stdout + "\n" + supervisor.stderr)[-1200:]
            ),
        )
    )

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Christiania hosted RC0 acceptance gate."
    )
    parser.add_argument(
        "--phase",
        choices=("static", "runtime", "full"),
        default="full",
    )
    parser.add_argument("--env-file", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    for env_file in args.env_file:
        loaded = load_runtime_env_file(env_file, overwrite=False)
        if not loaded:
            raise SystemExit(f"Environment file missing or empty: {env_file}")

    checks: list[AcceptanceCheck] = []
    if args.phase in {"static", "full"}:
        checks.extend(static_checks())
    if args.phase in {"runtime", "full"}:
        checks.extend(runtime_checks())

    failed = [check for check in checks if check.state == "FAIL"]
    payload = {
        "ready": not failed,
        "phase": args.phase,
        "failed": len(failed),
        "checks": [check.as_dict() for check in checks],
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Christiania Hosted RC0 Acceptance")
        print("--------------------------------")
        for check in checks:
            print(f"[{check.state}] {check.name}: {check.detail}")
        print()
        print("RC0 ACCEPTED" if not failed else "RC0 NOT ACCEPTED")

    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
