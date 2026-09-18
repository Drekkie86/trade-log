from __future__ import annotations

import json

from src.research.h2_h3_followup_confirmation_v1 import (
    evaluate_h2_h3_followup_confirmation_v1,
    result_as_dict,
)


def main() -> None:
    result = evaluate_h2_h3_followup_confirmation_v1(
        persist=True,
    )
    print(
        json.dumps(
            result_as_dict(result),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
