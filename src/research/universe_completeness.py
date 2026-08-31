from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ExpiryCount:
    expiration: str
    primary_count: int
    reference_count: int


@dataclass(frozen=True)
class UniverseCompletenessResult:
    primary_expirations: tuple[str, ...]
    reference_expirations: tuple[str, ...]
    primary_only_expirations: tuple[str, ...]
    reference_only_expirations: tuple[str, ...]
    per_expiry: tuple[ExpiryCount, ...]

    @property
    def is_complete(self) -> bool:
        return not self.primary_only_expirations and not self.reference_only_expirations


def compare_expiration_sets(
    primary_contracts: Iterable[tuple[str, str]],
    reference_contracts: Iterable[tuple[str, str]],
) -> UniverseCompletenessResult:
    """
    Compare provider expiration sets.

    Each iterable contains (canonical_contract_id, expiration).

    Expiration-set completeness is intentionally checked separately from
    contract-level reconciliation. A provider can return every contract for
    the expirations it knows about and still omit an entire expiration.
    """
    primary = list(primary_contracts)
    reference = list(reference_contracts)

    primary_exp = {expiration for _, expiration in primary}
    reference_exp = {expiration for _, expiration in reference}

    counts = []
    for expiration in sorted(primary_exp | reference_exp):
        counts.append(
            ExpiryCount(
                expiration=expiration,
                primary_count=sum(1 for _, exp in primary if exp == expiration),
                reference_count=sum(1 for _, exp in reference if exp == expiration),
            )
        )

    return UniverseCompletenessResult(
        primary_expirations=tuple(sorted(primary_exp)),
        reference_expirations=tuple(sorted(reference_exp)),
        primary_only_expirations=tuple(sorted(primary_exp - reference_exp)),
        reference_only_expirations=tuple(sorted(reference_exp - primary_exp)),
        per_expiry=tuple(counts),
    )
