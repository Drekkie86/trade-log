from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from src.research.edge_statement_validation import validate_file

def main()->int:
    p=argparse.ArgumentParser(description="Fail-closed Christiania Edge Statement validator v3")
    p.add_argument("document")
    p.add_argument("--discovery-registry",default="research/edge_discovery/DISCOVERY_WINDOW_REGISTRY.json")
    p.add_argument("--hypothesis-log",default="research/edge_discovery/HYPOTHESIS_EVALUATION_LOG.jsonl")
    p.add_argument("--programme-budget",default="research/edge_discovery/PROGRAMME_FAMILY_BUDGET_V1.json")
    p.add_argument("--holdout-registry",default="research/edge_discovery/HOLDOUT_ACCESS_REGISTRY.json")
    a=p.parse_args()
    print("Christiania - Edge Statement validation v3")
    try:
        result=validate_file(a.document,a.discovery_registry,hypothesis_log_path=a.hypothesis_log,programme_budget_path=a.programme_budget,holdout_registry_path=a.holdout_registry)
    except (FileNotFoundError,KeyError,ValueError) as exc:
        print(f"FAIL: {exc}"); return 2
    print(result.report())
    return 0 if result.ok else 1
if __name__=="__main__": raise SystemExit(main())
