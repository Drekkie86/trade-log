from __future__ import annotations

import argparse

from src.research.local_surface_residual_v2 import scan_local_surface_residual_v2


def main() -> None:
    parser = argparse.ArgumentParser(description="Run observational LOCAL_SURFACE_RESIDUAL_V2 for one persisted research run.")
    parser.add_argument("--research-run-id", type=int, required=True)
    args = parser.parse_args()
    result = scan_local_surface_residual_v2(research_run_id=args.research_run_id, persist=True)
    print("LOCAL_SURFACE_RESIDUAL_V2 observational run complete")
    print(f"Research run: {result.research_run_id}")
    print(f"Structural inputs: {result.structural_input_count}")
    print(f"Reference mapped: {result.reference_mapped_count}")
    print(f"Evaluable residuals: {result.evaluable_count}")
    print("Surfaced: 0 (hard-disabled by design)")


if __name__ == "__main__":
    main()
