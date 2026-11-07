from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

DEFAULT_LOG = Path("research/edge_discovery/HYPOTHESIS_EVALUATION_LOG.jsonl")


def parse_args():
    p=argparse.ArgumentParser(description="Append one evaluated edge hypothesis to the research log.")
    p.add_argument("family_id")
    p.add_argument("feature_set")
    p.add_argument("threshold")
    p.add_argument("structure")
    p.add_argument("horizon")
    p.add_argument("--log", default=str(DEFAULT_LOG))
    return p.parse_args()


def main()->int:
    a=parse_args(); path=Path(a.log); path.parent.mkdir(parents=True,exist_ok=True)
    record={
      "timestamp_utc":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),
      "family_id":a.family_id,
      "feature_set":a.feature_set,
      "threshold":a.threshold,
      "structure":a.structure,
      "horizon":a.horizon,
    }
    with path.open("a",encoding="utf-8",newline="\n") as fh:
        fh.write(json.dumps(record,sort_keys=True,separators=(",",":"))+"\n")
    print(f"RECORDED {a.family_id}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
