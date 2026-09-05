from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from src.config import load_runtime_env_file
from src.operations.secure_edge import inspect_secure_edge_configuration, render_caddyfile


ROOT = Path(__file__).resolve().parent
CADDY_TEMPLATE = ROOT / "deploy" / "secure-edge" / "Caddyfile.template"


def _binary_check(name: str) -> dict[str, str]:
    path = shutil.which(name)
    return {
        "name": f"binary-{name}",
        "state": "PASS" if path else "FAIL",
        "detail": path or f"{name} is not on PATH.",
    }


def run_preflight() -> dict[str, object]:
    status = inspect_secure_edge_configuration()
    checks = [check.as_dict() for check in status.checks]
    checks.extend([_binary_check("caddy"), _binary_check("oauth2-proxy")])

    caddy = shutil.which("caddy")
    if caddy and CADDY_TEMPLATE.is_file() and status.public_host:
        import tempfile

        rendered = render_caddyfile(
            CADDY_TEMPLATE.read_text(encoding="utf-8"),
            status.public_host,
        )
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".Caddyfile", delete=False
        ) as handle:
            handle.write(rendered)
            rendered_path = Path(handle.name)
        try:
            cp = subprocess.run(
                [caddy, "validate", "--config", str(rendered_path), "--adapter", "caddyfile"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            rendered_path.unlink(missing_ok=True)
        checks.append({
            "name": "caddy-config",
            "state": "PASS" if cp.returncode == 0 else "FAIL",
            "detail": "Rendered Caddyfile validates." if cp.returncode == 0 else (cp.stderr.strip() or cp.stdout.strip() or "Caddyfile validation failed."),
        })
    else:
        checks.append({
            "name": "caddy-config",
            "state": "FAIL",
            "detail": "Caddy binary, Caddy template, and valid public host are required for config validation.",
        })

    ready = all(check["state"] == "PASS" for check in checks)
    return {
        "ready": ready,
        "public_host": status.public_host,
        "authorized_email_count": status.authorized_email_count,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Christiania secure web-edge preflight.")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.env_file:
        loaded = load_runtime_env_file(args.env_file, overwrite=False)
        if not loaded:
            raise SystemExit(f"Environment file missing or empty: {args.env_file}")

    result = run_preflight()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("Christiania secure web-edge preflight")
        print("--------------------------------------")
        for check in result["checks"]:
            print(f"[{check['state']}] {check['name']}: {check['detail']}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
