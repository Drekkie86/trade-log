from __future__ import annotations

import json

from src.operations.theta_watchdog import evaluate_theta_watchdog


def main() -> int:
    result = evaluate_theta_watchdog()
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 2 if result.recovery_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
