from __future__ import annotations

import json

from src.research.prospective_hypothesis_checkpoint_v1 import (
    evaluate_prospective_hypotheses_v1,
    result_as_dict,
)


def main() -> None:
    result = evaluate_prospective_hypotheses_v1(persist=True)
    print(json.dumps(result_as_dict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
