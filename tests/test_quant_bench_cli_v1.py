from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.quant.bench import run_vanilla_bench
from src.quant.disagreement import summarize
from src.quant.types import VanillaOption


ROOT = Path(__file__).resolve().parents[1]


def test_model_disagreement_summary_with_market_price():
    result = summarize({"A": 10.0, "B": 11.0, "C": 12.0}, market_price=13.0)
    assert result.mean == 11.0
    assert result.absolute_range == 2.0
    assert result.market_minus_consensus == 2.0
    assert result.market_z_score is not None


def test_vanilla_bench_runs_five_models_and_is_research_only():
    result = run_vanilla_bench(
        VanillaOption(100, 100, 0.25, 0.02, 0.25, "CALL"),
        market_price=5.5,
        tree_steps=250,
        mc_paths=20_000,
    ).as_dict()
    assert len(result["model_prices"]) == 6
    assert result["governance"]["decision_enabled"] is False
    assert result["governance"]["admission_enabled"] is False
    assert "not a trade signal" in result["governance"]["warning"]


def test_quant_cli_registry_json():
    cp = subprocess.run(
        [sys.executable, "christiania_quant.py", "registry"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert cp.returncode == 0, cp.stderr
    payload = json.loads(cp.stdout)
    assert payload["governance"] == "RESEARCH_ONLY"
    assert len(payload["models"]) >= 10


def test_quant_cli_bench_json():
    cp = subprocess.run(
        [
            sys.executable,
            "christiania_quant.py",
            "bench",
            "--spot", "100",
            "--strike", "100",
            "--time", "0.25",
            "--rate", "0.02",
            "--vol", "0.25",
            "--right", "CALL",
            "--mc-paths", "10000",
            "--tree-steps", "200",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert cp.returncode == 0, cp.stderr
    payload = json.loads(cp.stdout)
    assert payload["governance"]["state"] == "RESEARCH_ONLY"
    assert "HESTON" in payload["model_prices"]


def test_command_deck_has_quant_bench_and_research_warning():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"Quant Bench"' in app
    assert "RESEARCH ONLY — challenger-model disagreement" in app
    assert "No model on this page can admit a candidate or submit an order." in app
