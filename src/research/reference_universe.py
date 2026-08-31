from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ReferenceUniverseError(ValueError):
    pass


@dataclass(frozen=True)
class ReferenceSnapshotState:
    provider_contract_id: str
    state: str
    reason_code: str | None


@dataclass(frozen=True)
class ReferenceSnapshotReconciliation:
    reference_count: int
    snapshot_count: int
    snapshot_present_count: int
    snapshot_absent_count: int
    snapshot_only_count: int
    states: tuple[ReferenceSnapshotState, ...]
    snapshot_only_ids: tuple[str, ...]

    @property
    def reference_accounting_reconciles(self) -> bool:
        return (
            self.reference_count
            ==
            self.snapshot_present_count
            + self.snapshot_absent_count
        )


def massive_reference_contract_id(
    row: dict[str, Any],
) -> str:
    value = row.get("ticker")
    if not isinstance(value, str) or not value.strip():
        raise ReferenceUniverseError(
            "Massive reference row is missing ticker."
        )
    return value.strip().upper()


def massive_snapshot_contract_id(
    row: dict[str, Any],
) -> str:
    details = row.get("details") or {}
    value = details.get("ticker")
    if not isinstance(value, str) or not value.strip():
        raise ReferenceUniverseError(
            "Massive snapshot row is missing details.ticker."
        )
    return value.strip().upper()


def _unique_ids(
    rows: list[dict[str, Any]],
    *,
    identity_fn,
    label: str,
) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []

    for row in rows:
        identity = identity_fn(row)
        if identity in seen:
            raise ReferenceUniverseError(
                f"Duplicate {label} contract identity: "
                f"{identity}"
            )
        seen.add(identity)
        ordered.append(identity)

    return tuple(ordered)


def reconcile_massive_reference_snapshot(
    reference_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
) -> ReferenceSnapshotReconciliation:
    """
    Reconcile Massive listing-reference contracts
    against Massive option-chain snapshot rows.

    Absence is recorded as an observation state.
    No cause is inferred from absence.
    """

    reference_ids = _unique_ids(
        reference_rows,
        identity_fn=massive_reference_contract_id,
        label="reference",
    )
    snapshot_ids = _unique_ids(
        snapshot_rows,
        identity_fn=massive_snapshot_contract_id,
        label="snapshot",
    )

    reference_set = set(reference_ids)
    snapshot_set = set(snapshot_ids)

    states: list[ReferenceSnapshotState] = []
    for identity in reference_ids:
        if identity in snapshot_set:
            states.append(
                ReferenceSnapshotState(
                    provider_contract_id=identity,
                    state="PRESENT",
                    reason_code=None,
                )
            )
        else:
            states.append(
                ReferenceSnapshotState(
                    provider_contract_id=identity,
                    state="ABSENT",
                    reason_code="SNAPSHOT_ROW_ABSENT",
                )
            )

    snapshot_only = tuple(
        identity
        for identity in snapshot_ids
        if identity not in reference_set
    )

    present_count = sum(
        state.state == "PRESENT"
        for state in states
    )
    absent_count = sum(
        state.state == "ABSENT"
        for state in states
    )

    return ReferenceSnapshotReconciliation(
        reference_count=len(reference_ids),
        snapshot_count=len(snapshot_ids),
        snapshot_present_count=present_count,
        snapshot_absent_count=absent_count,
        snapshot_only_count=len(snapshot_only),
        states=tuple(states),
        snapshot_only_ids=snapshot_only,
    )
