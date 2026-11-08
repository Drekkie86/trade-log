from __future__ import annotations

import json

from src.research.historical_replay_recovery_v1 import (
    result_as_dict,
    run_historical_replay_recovery_v1,
)


def main() -> None:
    result = run_historical_replay_recovery_v1()
    print(json.dumps(result_as_dict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
