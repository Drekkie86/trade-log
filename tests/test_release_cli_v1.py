from __future__ import annotations

import subprocess
import sys


def test_release_cli_version():
    cp = subprocess.run([sys.executable, "christiania_release.py", "version"], text=True, capture_output=True)
    assert cp.returncode == 0
    assert cp.stdout.strip() == "1.0.0-rc1"
