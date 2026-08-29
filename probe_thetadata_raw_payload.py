from __future__ import annotations
import argparse, json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("symbol")
    p.add_argument("date")
    p.add_argument("--max-dte", type=int, default=45)
    a = p.parse_args()

    url = "http://127.0.0.1:25503/v3/option/history/eod?" + urlencode({
        "symbol": a.symbol.upper(),
        "expiration": "*",
        "start_date": a.date,
        "end_date": a.date,
        "max_dte": str(a.max_dte),
        "format": "json",
    })

    print("Christiania - ThetaData raw payload probe")
    print("=========================================")
    print("Read-only. No database writes. No broker calls.")
    print(f"Request: {url}")
    print()

    try:
        with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=60) as r:
            status = getattr(r, "status", None)
            ctype = r.headers.get("Content-Type")
            raw = r.read()
    except HTTPError as e:
        raw = e.read()
        print(f"HTTP STATUS: {e.code}")
        print(f"CONTENT-TYPE: {e.headers.get('Content-Type')}")
        print(raw.decode("utf-8", errors="replace")[:5000])
        return 1
    except URLError as e:
        print(f"FAIL: {e}")
        return 1

    print(f"HTTP STATUS: {status}")
    print(f"CONTENT-TYPE: {ctype}")
    print(f"BODY BYTES: {len(raw)}")
    text = raw.decode("utf-8", errors="replace")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        print("JSON TYPE: INVALID")
        print(text[:5000])
        return 1

    print(f"JSON TYPE: {type(payload).__name__}")
    if isinstance(payload, dict):
        print(f"TOP-LEVEL KEYS: {sorted(payload.keys())}")
        print(json.dumps(payload, indent=2, sort_keys=True)[:5000])
        return 2
    if isinstance(payload, list):
        print(f"ROW COUNT: {len(payload)}")
        if payload:
            print(f"FIRST ROW TYPE: {type(payload[0]).__name__}")
            if isinstance(payload[0], dict):
                print(f"FIRST ROW KEYS: {sorted(payload[0].keys())}")
                print(json.dumps(payload[0], indent=2, sort_keys=True)[:5000])
        return 0

    print(text[:5000])
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
