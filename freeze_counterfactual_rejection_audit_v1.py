from __future__ import annotations

import json

from src.research.counterfactual_rejection_audit_v1 import (
    freeze_counterfactual_rejection_audit_v1,
    freeze_result_as_dict,
)


def main() -> None:
    result = freeze_counterfactual_rejection_audit_v1()
    print(
        json.dumps(
            freeze_result_as_dict(result),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
