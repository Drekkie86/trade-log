from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

DEFAULT_REGISTRY=Path("research/edge_discovery/HOLDOUT_ACCESS_REGISTRY.json")


def parse_args():
    p=argparse.ArgumentParser(description="Record non-mechanical access to a prospective holdout window.")
    p.add_argument("start")
    p.add_argument("end")
    p.add_argument("reason")
    p.add_argument("--registry",default=str(DEFAULT_REGISTRY))
    return p.parse_args()


def main()->int:
    a=parse_args(); path=Path(a.registry)
    payload=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version":"1.0","access_events":[]}
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
    payload.setdefault("access_events",[]).append({
      "event_id":f"ACCESS_{now.replace(':','').replace('-','')}",
      "start":a.start,"end":a.end,"access_type":"NON_MECHANICAL_REVIEW",
      "reason":a.reason,"contaminates_confirmation":True,"recorded_at_utc":now,
    })
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    print("RECORDED HOLDOUT ACCESS; WINDOW IS CONTAMINATED FOR CONFIRMATION")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
