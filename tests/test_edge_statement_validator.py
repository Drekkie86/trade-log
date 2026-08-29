from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_template_is_valid_json():
    path = Path("research/edge_discovery/EDGE_STATEMENT_TEMPLATE_V1.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["results"] == {"locked_until_confirmation": True}


def test_validator_accepts_template_as_draft():
    result = subprocess.run(
        [
            sys.executable,
            "validate_edge_statement.py",
            "research/edge_discovery/EDGE_STATEMENT_TEMPLATE_V1.json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "VALID JSON EDGE STATEMENT" in result.stdout


def test_template_is_not_preregistration_ready():
    result = subprocess.run(
        [
            sys.executable,
            "validate_edge_statement.py",
            "research/edge_discovery/EDGE_STATEMENT_TEMPLATE_V1.json",
            "--preregister",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "NOT PREREGISTRATION READY" in result.stdout
