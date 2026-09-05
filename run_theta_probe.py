from __future__ import annotations

import argparse
import json

from src.providers.thetadata_control import (
    DEFAULT_PROBE_SYMBOL,
    probe_theta_terminal,
    wait_for_theta_terminal,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Theta Terminal v3 readiness probe for Christiania."
    )
    parser.add_argument("--wait-seconds", type=float, default=0.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--symbol", default=DEFAULT_PROBE_SYMBOL)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    health = (
        probe_theta_terminal(symbol=args.symbol)
        if args.wait_seconds <= 0
        else wait_for_theta_terminal(
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
            symbol=args.symbol,
        )
    )

    if args.json:
        print(json.dumps(health.as_dict(), indent=2, sort_keys=True))
    else:
        print("Christiania Theta readiness")
        print("----------------------------")
        print(f"State: {health.state}")
        print(f"Endpoint: {health.base_url}")
        print(f"Probe symbol: {health.probe_symbol}")
        print(f"HTTP: {health.http_status}")
        print(
            "Latency: "
            + (
                "n/a"
                if health.latency_ms is None
                else f"{health.latency_ms:.1f} ms"
            )
        )
        print(f"Detail: {health.detail}")

    return 0 if health.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
