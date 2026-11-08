from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "review_packages"
PROMPT_PATH = ROOT / "docs" / "CLAUDE_HOSTILE_REVIEW_FULL_PROMPT.md"

SENSITIVE_TRACKED_EXACT = {
    ".env",
    ".streamlit/secrets.toml",
    "creds.txt",
    "credentials.txt",
}

SENSITIVE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
}

MODEL_KEYWORDS = (
    "quant",
    "model",
    "pricing",
    "black",
    "bsm",
    "heston",
    "merton",
    "svi",
    "sabr",
    "local_vol",
    "local-vol",
    "implied_vol",
    "implied-vol",
    "greek",
    "monte",
    "tree",
    "garch",
    "ewma",
    "realized",
    "forecast",
    "calibration",
    "scenario",
    "risk",
    "var",
    "cvar",
    "edge",
    "shadow",
    "casino",
    "0dte",
    "volatility",
)

IMPORTANT_DOCS = (
    "README.md",
    "docs/V1_ARCHITECTURE.md",
    "docs/V1_STATUS.md",
    "docs/ROADMAP.md",
    "docs/CLAUDE_REVIEW_COPYPASTE_PROMPT.md",
    "docs/CLAUDE_REVIEW_PAUSE_POINT_2026-08-29.md",
    "research/edge_discovery/EDGE_DISCOVERY_PROTOCOL_V1.md",
)


def run(*args: str, timeout: int = 120, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env=env,
    )


def git(*args: str, timeout: int = 120) -> str:
    completed = run("git", *args, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed:\n{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tracked_files() -> list[str]:
    raw = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [item.decode("utf-8") for item in raw.split(b"\0") if item]


def refuse_sensitive_tracked(files: list[str]) -> None:
    violations: list[str] = []
    for rel in files:
        normalized = rel.replace("\\", "/")
        if normalized in SENSITIVE_TRACKED_EXACT:
            violations.append(normalized)
            continue
        if Path(normalized).suffix.lower() in SENSITIVE_SUFFIXES:
            violations.append(normalized)
    if violations:
        raise RuntimeError(
            "Refusing to build review package because sensitive-looking tracked files exist: "
            + ", ".join(sorted(violations))
        )


def category(rel: str) -> str:
    p = rel.replace("\\", "/")
    lower = p.lower()
    if lower.startswith("tests/"):
        return "tests"
    if lower.startswith("migrations/") or lower.endswith(".sql"):
        return "database"
    if lower.startswith("deploy/") or lower.startswith(".github/"):
        return "deployment_ci"
    if lower.startswith("docs/"):
        return "documentation"
    if lower.startswith("research/"):
        return "research"
    if lower.startswith("src/quant/") or any(keyword in lower for keyword in MODEL_KEYWORDS):
        return "quant_models"
    if lower.endswith(".py"):
        return "python_source"
    if lower.endswith((".toml", ".yml", ".yaml", ".json", ".ini", ".cfg")):
        return "configuration"
    if lower.startswith("assets/"):
        return "assets"
    return "other"


def write_repo_tree(files: list[str], target: Path) -> None:
    target.write_text("\n".join(sorted(files)) + "\n", encoding="utf-8")


def write_manifest(files: list[str], copied_root: Path, target: Path) -> tuple[int, int]:
    total_bytes = 0
    rows = []
    for rel in sorted(files):
        path = copied_root / rel
        size = path.stat().st_size
        total_bytes += size
        rows.append(
            {
                "path": rel.replace("\\", "/"),
                "category": category(rel),
                "bytes": size,
                "sha256": sha256_file(path),
            }
        )

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "category", "bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), total_bytes


def write_review_index(files: list[str], target: Path) -> None:
    grouped: dict[str, list[str]] = {}
    for rel in sorted(files):
        grouped.setdefault(category(rel), []).append(rel.replace("\\", "/"))

    model_targets = sorted(
        rel.replace("\\", "/")
        for rel in files
        if category(rel) in {"quant_models", "research"}
    )

    lines = [
        "# Christiania hostile review index",
        "",
        "This file is generated from the exact tracked-file set in the package.",
        "It is an orientation aid only; Claude must still use MANIFEST.csv as the completeness ledger.",
        "",
        "## High-priority authoritative / framing documents",
        "",
    ]

    for doc in IMPORTANT_DOCS:
        marker = "present" if doc in files else "NOT PRESENT"
        lines.append(f"- `{doc}` — {marker}")

    lines.extend(["", "## Quantitative / research targets", ""])
    for rel in model_targets:
        lines.append(f"- `{rel}`")

    lines.extend(["", "## All files by review category", ""])
    for name in sorted(grouped):
        lines.append(f"### {name} ({len(grouped[name])})")
        lines.append("")
        for rel in grouped[name]:
            lines.append(f"- `{rel}`")
        lines.append("")

    target.write_text("\n".join(lines), encoding="utf-8")


def capture_command(name: str, args: list[str], target: Path, timeout: int) -> int:
    started = datetime.now(timezone.utc).isoformat()
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        return_code = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nTIMEOUT after {timeout} seconds\n"

    target.write_text(
        "\n".join(
            [
                f"COMMAND_NAME: {name}",
                f"STARTED_UTC: {started}",
                f"COMMAND: {' '.join(args)}",
                f"RETURN_CODE: {return_code}",
                "",
                "===== STDOUT =====",
                stdout,
                "",
                "===== STDERR =====",
                stderr,
            ]
        ),
        encoding="utf-8",
        errors="replace",
    )
    return return_code


def write_git_context(target: Path) -> None:
    fields = {
        "commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "origin_main": git("rev-parse", "origin/main"),
        "status_porcelain": git("status", "--porcelain=v1"),
        "remote_origin": git("remote", "get-url", "origin"),
    }
    log = git("log", "-30", "--date=iso-strict", "--pretty=format:%H%x09%ad%x09%s")
    target.write_text(
        "\n".join(
            [
                "# Exact source identity",
                *(f"{key}={value}" for key, value in fields.items()),
                "",
                "# Last 30 commits",
                log,
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_package_readme(target: Path, commit: str, quality_gate_rc: int | None) -> None:
    gate_text = "NOT RUN" if quality_gate_rc is None else f"return code {quality_gate_rc}"
    target.write_text(
        textwrap.dedent(
            f"""
            # START HERE — Christiania full hostile review package

            This is a self-contained adversarial-review bundle generated from Git commit:

            `{commit}`

            ## What is included

            - `repository/` — **every Git-tracked file** from the exact source commit, preserving paths.
            - `MANIFEST.csv` — SHA-256, byte size and review category for every tracked file.
            - `REPO_TREE.txt` — complete tracked-file list.
            - `REVIEW_INDEX.md` — orientation index highlighting quantitative/research/deployment targets.
            - `CLAUDE_HOSTILE_REVIEW_FULL_PROMPT.md` — the required hostile-review instructions.
            - `GIT_CONTEXT.txt` — exact Git identity and recent commit history.
            - `QUALITY_GATE.txt` — Christiania's own quality-gate execution evidence ({gate_text}).
            - `PYTHON_COMPILEALL.txt` — syntax/import-bytecode compilation evidence.
            - `PACKAGE_METADATA.json` — package provenance and checksums metadata.

            ## Important security boundary

            This package is intentionally built from **tracked files only**. It does **not** include live `.env` files, OAuth client secrets, cookie secrets, SSH keys, API keys, production `/etc/christiania/*`, the live SQLite database, backups, private audit exports or broker credentials.

            That exclusion is deliberate. Claude must review the **contracts and code** governing those resources, but must not interpret their absence as proof that production secret handling or runtime state is correct.

            ## Instructions to Claude

            1. Open `CLAUDE_HOSTILE_REVIEW_FULL_PROMPT.md` first.
            2. Treat `MANIFEST.csv` as the completeness ledger.
            3. Review the entire `repository/` tree, not only the files mentioned in the prompt.
            4. If context limits prevent complete inspection, use the required coverage ledger and explicitly mark omissions.
            5. Do not trust green tests, docs or claims without cross-checking implementation.

            ## Package integrity

            The outer ZIP receives a sibling `.sha256` file after construction. The manifest provides per-file hashes inside the package.
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def build_package(output_dir: Path, skip_quality_gate: bool) -> Path:
    if not (ROOT / ".git").exists():
        raise RuntimeError("Run this script from a real Christiania Git checkout.")

    status = git("status", "--porcelain=v1")
    if status:
        raise RuntimeError(
            "Refusing to package a dirty working tree. Commit/stash/remove changes first:\n" + status
        )

    head = git("rev-parse", "HEAD")
    origin_main = git("rev-parse", "origin/main")
    if head != origin_main:
        raise RuntimeError(
            f"Refusing to package a non-origin/main commit: HEAD={head}, origin/main={origin_main}"
        )

    files = tracked_files()
    refuse_sensitive_tracked(files)

    if "docs/CLAUDE_HOSTILE_REVIEW_FULL_PROMPT.md" not in files:
        raise RuntimeError("Full hostile-review prompt is not tracked in this commit.")

    output_dir.mkdir(parents=True, exist_ok=True)
    short = head[:12]
    package_name = f"christiania-hostile-review-{short}"
    zip_path = output_dir / f"{package_name}.zip"
    sha_path = output_dir / f"{package_name}.zip.sha256"

    if zip_path.exists():
        zip_path.unlink()
    if sha_path.exists():
        sha_path.unlink()

    with tempfile.TemporaryDirectory(prefix="christiania-hostile-review-") as tmp_raw:
        tmp = Path(tmp_raw)
        package_root = tmp / package_name
        repo_copy = package_root / "repository"
        repo_copy.mkdir(parents=True)

        for rel in files:
            src = ROOT / rel
            dst = repo_copy / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_symlink():
                # Preserve the link target as review evidence without dereferencing arbitrary paths.
                dst.write_text(f"SYMLINK -> {os.readlink(src)}\n", encoding="utf-8")
            else:
                shutil.copy2(src, dst)

        prompt_copy = package_root / "CLAUDE_HOSTILE_REVIEW_FULL_PROMPT.md"
        shutil.copy2(PROMPT_PATH, prompt_copy)

        write_repo_tree(files, package_root / "REPO_TREE.txt")
        file_count, total_bytes = write_manifest(files, repo_copy, package_root / "MANIFEST.csv")
        write_review_index(files, package_root / "REVIEW_INDEX.md")
        write_git_context(package_root / "GIT_CONTEXT.txt")

        compile_rc = capture_command(
            "python compileall",
            [sys.executable, "-m", "compileall", "-q", "."],
            package_root / "PYTHON_COMPILEALL.txt",
            timeout=300,
        )

        quality_gate_rc: int | None
        if skip_quality_gate:
            quality_gate_rc = None
            (package_root / "QUALITY_GATE.txt").write_text(
                "QUALITY GATE NOT RUN: package builder invoked with --skip-quality-gate\n",
                encoding="utf-8",
            )
        else:
            quality_gate_rc = capture_command(
                "Christiania quality gate",
                [sys.executable, "quality_gate.py", "--ci"],
                package_root / "QUALITY_GATE.txt",
                timeout=1800,
            )

        write_package_readme(package_root / "START_HERE.md", head, quality_gate_rc)

        metadata = {
            "package_format_version": 1,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "source_commit": head,
            "source_origin_main": origin_main,
            "tracked_file_count": file_count,
            "tracked_total_bytes": total_bytes,
            "python": sys.version,
            "platform": sys.platform,
            "quality_gate_return_code": quality_gate_rc,
            "compileall_return_code": compile_rc,
            "security_note": "Tracked files only; live secrets/runtime DB/backups are intentionally excluded.",
        }
        (package_root / "PACKAGE_METADATA.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(package_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(tmp))

    zip_sha = sha256_file(zip_path)
    sha_path.write_text(f"{zip_sha}  {zip_path.name}\n", encoding="utf-8")

    print("Christiania hostile review package created")
    print(f"commit={head}")
    print(f"zip={zip_path}")
    print(f"sha256={zip_sha}")
    if quality_gate_rc is not None:
        print(f"quality_gate_return_code={quality_gate_rc}")
    print(f"compileall_return_code={compile_rc}")
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a complete, reproducible Claude hostile-review bundle from the exact tracked Christiania repository."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--skip-quality-gate",
        action="store_true",
        help="Skip the full Christiania quality gate. Not recommended for the package sent to Claude.",
    )
    args = parser.parse_args()

    try:
        build_package(args.output_dir.resolve(), args.skip_quality_gate)
    except Exception as exc:
        print(f"PACKAGE BUILD FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
