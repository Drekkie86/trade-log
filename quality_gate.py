from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SENSITIVE_EXACT = {
    ".env",
    "creds.txt",
    ".streamlit/secrets.toml",
}

FORBIDDEN_TRACKED_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".pyo",
}

PROTECTED_UNTRACKED_PREFIXES = (
    "src/",
    "tests/",
    "migrations/",
    ".github/",
)

PROTECTED_UNTRACKED_EXACT = {
    "trade_log_schema.sql",
    "quality_gate.py",
    "requirements-ci.txt",
}

MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")


@dataclass(frozen=True)
class GateResult:
    name: str
    ok: bool
    detail: str


def run(
    *args: str,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=capture,
        check=False,
    )


def git_lines(*args: str) -> list[str]:
    completed = run("git", *args)
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
        )
    return [
        line.rstrip()
        for line in completed.stdout.splitlines()
        if line.strip()
    ]


def tracked_files() -> list[str]:
    return git_lines("ls-files")


def untracked_files() -> list[str]:
    return git_lines(
        "ls-files",
        "--others",
        "--exclude-standard",
    )


def check_sensitive_tracked() -> GateResult:
    tracked = tracked_files()
    violations: list[str] = []

    for rel in tracked:
        normalized = rel.replace("\\", "/")
        if normalized in SENSITIVE_EXACT:
            violations.append(normalized)
            continue

        if Path(normalized).suffix.lower() in FORBIDDEN_TRACKED_SUFFIXES:
            violations.append(normalized)

    return GateResult(
        "tracked secrets / databases",
        not violations,
        (
            "none"
            if not violations
            else ", ".join(sorted(violations))
        ),
    )


def check_duplicate_test_modules() -> GateResult:
    """
    Fail on duplicate pytest module basenames outside tests/.

    A legacy root-level diagnostic named test_*.py is not itself a
    collision. The failure we need to prevent is the packaging bug where
    (for example) payload/test_x.py and tests/test_x.py both exist and
    pytest imports the wrong module.
    """

    canonical_names = {
        path.name
        for path in (ROOT / "tests").glob("test_*.py")
        if path.is_file()
    }

    violations: list[str] = []

    for path in ROOT.rglob("test_*.py"):
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            continue

        parts = rel.parts
        if not parts:
            continue

        if parts[0] == "tests":
            continue

        if any(
            part in {
                ".venv",
                ".git",
                "__pycache__",
            }
            for part in parts
        ):
            continue

        if path.name in canonical_names:
            violations.append(
                str(rel).replace("\\", "/")
            )

    return GateResult(
        "duplicate pytest module basenames",
        not violations,
        (
            "none"
            if not violations
            else ", ".join(sorted(violations))
        ),
    )


def check_untracked_protected() -> GateResult:
    untracked = [
        item.replace("\\", "/")
        for item in untracked_files()
    ]

    violations = [
        item
        for item in untracked
        if item in PROTECTED_UNTRACKED_EXACT
        or item.startswith(PROTECTED_UNTRACKED_PREFIXES)
    ]

    return GateResult(
        "untracked protected source/test/migration files",
        not violations,
        (
            "none"
            if not violations
            else ", ".join(sorted(violations))
        ),
    )


def check_migration_sequence() -> GateResult:
    migration_dir = ROOT / "migrations"
    if not migration_dir.exists():
        return GateResult(
            "migration numbering",
            False,
            "migrations/ directory missing",
        )

    numbers: list[int] = []
    names: list[str] = []

    for path in sorted(migration_dir.glob("*.sql")):
        match = MIGRATION_RE.match(path.name)
        if not match:
            continue
        numbers.append(int(match.group(1)))
        names.append(path.name)

    if not numbers:
        return GateResult(
            "migration numbering",
            False,
            "no numbered migrations found",
        )

    duplicates = sorted(
        number
        for number in set(numbers)
        if numbers.count(number) > 1
    )

    monotonic = numbers == sorted(numbers)
    contiguous = numbers == list(
        range(min(numbers), max(numbers) + 1)
    )

    ok = not duplicates and monotonic and contiguous
    detail = (
        f"{names[0]} .. {names[-1]}"
        if ok
        else (
            f"numbers={numbers}; "
            f"duplicates={duplicates}; "
            f"contiguous={contiguous}; "
            f"monotonic={monotonic}"
        )
    )

    return GateResult(
        "migration numbering",
        ok,
        detail,
    )


def check_schema_version_history() -> GateResult:
    schema = ROOT / "trade_log_schema.sql"
    if not schema.exists():
        return GateResult(
            "schema-version history safety",
            False,
            "trade_log_schema.sql missing",
        )

    text = schema.read_text(
        encoding="utf-8",
        errors="replace",
    )

    bad = "DELETE FROM schema_version" in text

    return GateResult(
        "schema-version history safety",
        not bad,
        (
            "non-destructive"
            if not bad
            else "DELETE FROM schema_version found"
        ),
    )


def check_expected_schema_version() -> GateResult:
    try:
        from src.database.repository import (
            EXPECTED_SCHEMA_VERSION,
        )
    except Exception as exc:
        return GateResult(
            "expected schema version",
            False,
            f"cannot import repository: {exc}",
        )

    migration_numbers = []
    for path in (ROOT / "migrations").glob("*.sql"):
        match = MIGRATION_RE.match(path.name)
        if match:
            migration_numbers.append(
                int(match.group(1))
            )

    if not migration_numbers:
        return GateResult(
            "expected schema version",
            False,
            "no migrations found",
        )

    latest = max(migration_numbers)
    ok = EXPECTED_SCHEMA_VERSION == latest

    return GateResult(
        "expected schema version",
        ok,
        (
            f"repository={EXPECTED_SCHEMA_VERSION}, latest migration={latest}"
        ),
    )


def build_fresh_database() -> GateResult:
    try:
        from src.database.repository import (
            get_connection,
        )
    except Exception as exc:
        return GateResult(
            "fresh database build + integrity",
            False,
            f"cannot import repository: {exc}",
        )

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "quality_gate.db"
        conn = get_connection(db_path)

        try:
            schema = (
                ROOT / "trade_log_schema.sql"
            ).read_text(
                encoding="utf-8"
            )
            conn.executescript(schema)

            native_version_row = conn.execute(
                "SELECT MAX(version) FROM schema_version;"
            ).fetchone()

            if (
                native_version_row is None
                or native_version_row[0] is None
            ):
                raise RuntimeError(
                    "Native schema created no schema_version."
                )

            native_version = int(
                native_version_row[0]
            )

            for migration in sorted(
                (ROOT / "migrations").glob("*.sql")
            ):
                match = MIGRATION_RE.match(
                    migration.name
                )
                if (
                    match
                    and int(match.group(1))
                    > native_version
                ):
                    conn.executescript(
                        migration.read_text(
                            encoding="utf-8"
                        )
                    )

            conn.commit()

            integrity = conn.execute(
                "PRAGMA integrity_check;"
            ).fetchone()[0]

            foreign_keys = conn.execute(
                "PRAGMA foreign_key_check;"
            ).fetchall()

            version = conn.execute(
                "SELECT MAX(version) FROM schema_version;"
            ).fetchone()[0]

            from src.database.repository import (
                EXPECTED_SCHEMA_VERSION,
            )

            ok = (
                integrity == "ok"
                and not foreign_keys
                and int(version)
                == int(EXPECTED_SCHEMA_VERSION)
            )

            return GateResult(
                "fresh database build + integrity",
                ok,
                (
                    f"native_schema_version={native_version}; "
                    f"integrity={integrity}; "
                    f"fk_rows={len(foreign_keys)}; "
                    f"schema_version={version}"
                ),
            )
        except Exception as exc:
            return GateResult(
                "fresh database build + integrity",
                False,
                repr(exc),
            )
        finally:
            conn.close()


def run_pytest() -> GateResult:
    completed = run(
        sys.executable,
        "-m",
        "pytest",
    )

    if completed.returncode == 0:
        summary = ""
        for line in reversed(
            completed.stdout.splitlines()
        ):
            if "passed" in line:
                summary = line.strip()
                break

        return GateResult(
            "full pytest suite",
            True,
            summary or "pytest passed",
        )

    tail = "\n".join(
        (
            completed.stdout
            + "\n"
            + completed.stderr
        ).splitlines()[-25:]
    )

    return GateResult(
        "full pytest suite",
        False,
        tail,
    )


def warn_untracked_debris() -> list[str]:
    warnings = []
    for item in untracked_files():
        normalized = item.replace("\\", "/")
        if normalized.startswith(
            PROTECTED_UNTRACKED_PREFIXES
        ):
            continue
        warnings.append(normalized)
    return warnings


def print_result(result: GateResult) -> None:
    symbol = "PASS" if result.ok else "FAIL"
    print(
        f"[{symbol}] {result.name}: "
        f"{result.detail}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Christiania local quality gate."
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help=(
            "Skip the full pytest suite. Intended only "
            "for fast local diagnostics, never release gating."
        ),
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help=(
            "CI mode: suppress non-failing debris listing."
        ),
    )
    args = parser.parse_args()

    print("Christiania Quality Gate v1")
    print("===========================")
    print()

    checks = [
        check_sensitive_tracked(),
        check_duplicate_test_modules(),
        check_untracked_protected(),
        check_migration_sequence(),
        check_schema_version_history(),
        check_expected_schema_version(),
        build_fresh_database(),
    ]

    if not args.skip_tests:
        checks.append(run_pytest())

    for result in checks:
        print_result(result)

    warnings = (
        []
        if args.ci
        else warn_untracked_debris()
    )

    if warnings:
        print()
        print(
            "WARN: untracked non-protected files "
            "exist. They do not fail the gate:"
        )
        for item in warnings[:50]:
            print(f"  {item}")
        if len(warnings) > 50:
            print(
                f"  ... and {len(warnings) - 50} more"
            )

    failed = [
        result
        for result in checks
        if not result.ok
    ]

    print()
    if failed:
        print(
            f"QUALITY GATE FAILED: "
            f"{len(failed)} check(s) failed."
        )
        return 1

    print("QUALITY GATE PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
