from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.database.repository import (
    create_listing_reference_contract,
    create_listing_reference_contracts,
    record_provider_observation_availability,
    record_provider_observation_availabilities,
    record_unmatched_provider_contract_observation,
)
from src.research.reference_universe import (
    ReferenceSnapshotReconciliation,
    reconcile_massive_reference_snapshot,
)


def persist_massive_reference_frame(
    *,
    research_run_id: int,
    underlying: str,
    reference_rows: list[dict[str, Any]],
    observed_at: str,
    db_path=None,
) -> dict[str, int]:
    """
    Persist Massive listing-reference contracts in one batch.

    Returns a mapping from Massive provider ticker
    to listing_reference_contracts.id.
    """

    contracts: list[dict[str, Any]] = []

    for row in reference_rows:
        ticker = row.get("ticker")
        expiration = row.get("expiration_date")
        strike = row.get("strike_price")
        contract_type = row.get("contract_type")

        if contract_type == "call":
            right = "C"
        elif contract_type == "put":
            right = "P"
        else:
            raise ValueError(
                f"Unsupported Massive contract_type: {contract_type}"
            )

        contracts.append(
            {
                "research_run_id": research_run_id,
                "provider": "MASSIVE",
                "underlying": underlying.upper(),
                "provider_contract_id": ticker,
                "option_symbol": ticker,
                "expiration": expiration,
                "strike": strike,
                "right": right,
                "exercise_style": row.get("exercise_style"),
                "shares_per_contract": row.get("shares_per_contract"),
                "primary_exchange": row.get("primary_exchange"),
                "additional_underlyings_json": (
                    None
                    if row.get("additional_underlyings") is None
                    else __import__("json").dumps(
                        row.get("additional_underlyings"),
                        sort_keys=True,
                    )
                ),
                "observed_at": observed_at,
            }
        )

    inserted = create_listing_reference_contracts(
        contracts,
        db_path=db_path,
    )

    return {
        str(row["ticker"]).upper():
            inserted[
                (
                    research_run_id,
                    "MASSIVE",
                    str(row["ticker"]),
                )
            ]
        for row in reference_rows
    }



def persist_massive_snapshot_availability(
    *,
    research_run_id: int,
    underlying: str,
    reference_id_by_ticker: dict[str, int],
    reference_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
    observed_at: str,
    db_path=None,
) -> ReferenceSnapshotReconciliation:
    """
    Reconcile and persist Massive snapshot PRESENT/ABSENT
    states against the listing-reference frame.
    """

    reconciliation = reconcile_massive_reference_snapshot(
        reference_rows,
        snapshot_rows,
    )

    availability_rows = [
        {
            "reference_contract_id":
                reference_id_by_ticker[
                    state.provider_contract_id
                ],
            "provider":
                "MASSIVE",
            "evidence_family":
                "MASSIVE_SNAPSHOT",
            "state":
                state.state,
            "reason_code":
                state.reason_code,
            "observed_at":
                observed_at,
        }
        for state in reconciliation.states
    ]

    record_provider_observation_availabilities(
        availability_rows,
        db_path=db_path,
    )

    snapshot_by_ticker = {
        str((row.get("details") or {}).get("ticker")).strip().upper(): row
        for row in snapshot_rows
        if (row.get("details") or {}).get("ticker")
    }

    for provider_contract_id in reconciliation.snapshot_only_ids:
        row = snapshot_by_ticker.get(provider_contract_id) or {}
        details = row.get("details") or {}
        contract_type = str(
            details.get("contract_type") or ""
        ).lower()
        right = (
            "C"
            if contract_type == "call"
            else "P"
            if contract_type == "put"
            else None
        )

        record_unmatched_provider_contract_observation(
            {
                "research_run_id": research_run_id,
                "provider": "MASSIVE",
                "evidence_family": "MASSIVE_SNAPSHOT",
                "anomaly_type": "SNAPSHOT_ONLY",
                "underlying": underlying.upper(),
                "provider_contract_id": provider_contract_id,
                "expiration": details.get("expiration_date"),
                "strike": details.get("strike_price"),
                "right": right,
                "reason_code": "SNAPSHOT_IDENTITY_NOT_IN_REFERENCE_FRAME",
                "observed_at": observed_at,
                "raw_payload_json": __import__("json").dumps(
                    row,
                    sort_keys=True,
                    default=str,
                ),
            },
            db_path=db_path,
        )

    return reconciliation


def persist_massive_reference_and_snapshot(
    *,
    research_run_id: int,
    underlying: str,
    reference_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
    observed_at: str,
    db_path=None,
) -> dict[str, Any]:
    """
    End-to-end persistence slice:
    reference listing frame -> snapshot availability evidence.
    """

    reference_map = persist_massive_reference_frame(
        research_run_id=research_run_id,
        underlying=underlying,
        reference_rows=reference_rows,
        observed_at=observed_at,
        db_path=db_path,
    )

    reconciliation = persist_massive_snapshot_availability(
        research_run_id=research_run_id,
        underlying=underlying,
        reference_id_by_ticker=reference_map,
        reference_rows=reference_rows,
        snapshot_rows=snapshot_rows,
        observed_at=observed_at,
        db_path=db_path,
    )

    return {
        "reference_ids": reference_map,
        "reconciliation": asdict(reconciliation),
    }
