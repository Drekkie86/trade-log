"""Regression: deploy receiver runs the transition gate as an absolute script.

Unlike importing this function in pytest, Python script execution from a
different working directory puts src/operations (not release root) on sys.path.
Check late imports in a truly isolated interpreter, without PYTHONPATH.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_transition_script_imports_verifier_with_isolated_python(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = root / "src" / "operations" / "deployment_transition_gate.py"
    snippet = (
        "import runpy\n"
        "from pathlib import Path\n"
        "from datetime import datetime, UTC\n"
        f"module = runpy.run_path({str(script)!r}, run_name='isolated_smoke')\n"
        "assert module['_verified_volume_backup']("
        "Path('/missing/scheduler.json'), "
        "Path('/not-a-real-mounted-volume'), "
        "Path('/missing/live.db'), now=datetime.now(UTC)) is False\n"
        "print('STANDALONE_GATE_IMPORT_PASS')\n"
    )
    process = subprocess.run(
        [sys.executable, "-I", "-c", snippet],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert process.returncode == 0, process.stdout + "\n" + process.stderr
    assert "STANDALONE_GATE_IMPORT_PASS" in process.stdout
