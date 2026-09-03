from __future__ import annotations

from src.research.local_surface_empirical_null_v1 import fit_empirical_null_v1


def main() -> None:
    result = fit_empirical_null_v1(persist=True)
    print("LOCAL_SURFACE_EMPIRICAL_NULL_V1 discovery fit complete")
    print(f"Null run: {result.null_run_id}")
    print(f"Discovery sessions: {result.source_first_session_date} -> {result.source_last_session_date}")
    print(f"Observations: {result.observation_count}")
    print(f"Strata: {result.stratum_count}")
    print("p-values: disabled")
    print("FDR/BH: disabled")
    print("decision/admission path: disabled")
    print("Effective-N values, where present, are exploratory dependence proxies only.")


if __name__ == "__main__":
    main()
