from __future__ import annotations

import json

from src.research.counterfactual_rejection_audit_v1 import (
    evaluate_counterfactual_rejection_audit_v1,
    evaluation_result_as_dict,
)


def main() -> None:
    result = evaluate_counterfactual_rejection_audit_v1()
    print(
        json.dumps(
            evaluation_result_as_dict(result),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
