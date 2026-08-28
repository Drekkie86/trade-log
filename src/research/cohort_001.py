from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from random import Random, SystemRandom
from typing import Iterable, Protocol


COHORT_ID = "COHORT_001_DATA_QUALITY_BASELINE"

DTE_STRATA: tuple[
    tuple[str, int, int],
    ...,
] = (
    ("DTE_07_14", 7, 14),
    ("DTE_15_30", 15, 30),
    ("DTE_31_45", 31, 45),
)

ABS_DELTA_STRATA: tuple[
    tuple[str, float, float],
    ...,
] = (
    ("DELTA_010_020", 0.10, 0.20),
    ("DELTA_020_035", 0.20, 0.35),
    ("DELTA_035_050", 0.35, 0.50),
    ("DELTA_050_065", 0.50, 0.65),
    ("DELTA_065_080", 0.65, 0.80),
)

RIGHTS: tuple[str, ...] = (
    "C",
    "P",
)


class ShuffleLike(Protocol):
    def shuffle(
        self,
        x: list[object],
    ) -> None:
        ...


@dataclass(frozen=True)
class CohortQuote:
    option_quote_id: int
    provider_contract_id: str | None
    option_symbol: str | None
    right: str
    strike: float
    expiration: str
    delta: float


@dataclass(frozen=True)
class CohortStratum:
    dte_name: str
    dte_min: int
    dte_max: int

    delta_name: str
    abs_delta_min: float
    abs_delta_max: float

    right: str

    @property
    def key(self) -> str:
        return (
            f"{self.dte_name}|"
            f"{self.delta_name}|"
            f"{self.right}"
        )

    @property
    def delta_midpoint(
        self,
    ) -> float:
        return (
            self.abs_delta_min
            + self.abs_delta_max
        ) / 2.0


@dataclass(frozen=True)
class CohortSelection:
    stratum: CohortStratum
    quote: CohortQuote
    dte: int
    abs_delta: float
    delta_distance_to_midpoint: float
    resolution_sequence: int | None = None


@dataclass(frozen=True)
class EmptyStratum:
    stratum: CohortStratum


@dataclass(frozen=True)
class SelectionResult:
    selected: tuple[CohortSelection, ...]
    empty: tuple[EmptyStratum, ...]

    @property
    def selected_count(
        self,
    ) -> int:
        return len(self.selected)

    @property
    def empty_count(
        self,
    ) -> int:
        return len(self.empty)

    @property
    def total_strata(
        self,
    ) -> int:
        return (
            self.selected_count
            + self.empty_count
        )


def all_strata() -> tuple[
    CohortStratum,
    ...,
]:
    strata: list[
        CohortStratum
    ] = []

    for (
        dte_name,
        dte_min,
        dte_max,
    ) in DTE_STRATA:
        for (
            delta_name,
            delta_min,
            delta_max,
        ) in ABS_DELTA_STRATA:
            for right in RIGHTS:
                strata.append(
                    CohortStratum(
                        dte_name=dte_name,
                        dte_min=dte_min,
                        dte_max=dte_max,
                        delta_name=(
                            delta_name
                        ),
                        abs_delta_min=(
                            delta_min
                        ),
                        abs_delta_max=(
                            delta_max
                        ),
                        right=right,
                    )
                )

    return tuple(strata)


def _normalise_right(
    value: str,
) -> str:
    normalized = (
        value.strip().upper()
    )

    if normalized in {
        "C",
        "CALL",
    }:
        return "C"

    if normalized in {
        "P",
        "PUT",
    }:
        return "P"

    raise ValueError(
        f"Unsupported option right: "
        f"{value!r}"
    )


def _expiration_date(
    value: str,
) -> date:
    return date.fromisoformat(
        value[:10]
    )


def _quote_dte(
    quote: CohortQuote,
    session_date: date,
) -> int:
    return (
        _expiration_date(
            quote.expiration
        )
        - session_date
    ).days


def _in_delta_interval(
    value: float,
    lower: float,
    upper: float,
) -> bool:
    """
    Delta bands form a non-overlapping partition.

    Lower bounds are inclusive. Upper bounds are
    exclusive, except the final 0.80 boundary.
    """
    if upper == 0.80:
        return (
            value >= lower
            and value <= upper
        )

    return (
        value >= lower
        and value < upper
    )


def _belongs_to_stratum(
    quote: CohortQuote,
    stratum: CohortStratum,
    session_date: date,
) -> bool:
    if (
        _normalise_right(
            quote.right
        )
        != stratum.right
    ):
        return False

    dte = _quote_dte(
        quote,
        session_date,
    )

    if not (
        stratum.dte_min
        <= dte
        <= stratum.dte_max
    ):
        return False

    abs_delta = abs(
        float(
            quote.delta
        )
    )

    return _in_delta_interval(
        abs_delta,
        stratum.abs_delta_min,
        stratum.abs_delta_max,
    )


def _selection_sort_key(
    quote: CohortQuote,
    stratum: CohortStratum,
) -> tuple[
    float,
    str,
    float,
    str,
]:
    abs_delta = abs(
        float(
            quote.delta
        )
    )

    delta_distance = abs(
        abs_delta
        - stratum.delta_midpoint
    )

    symbol = (
        quote.option_symbol
        or quote.provider_contract_id
        or ""
    )

    return (
        delta_distance,
        quote.expiration[:10],
        float(quote.strike),
        symbol,
    )


def select_primary_contracts(
    quotes: Iterable[CohortQuote],
    *,
    session_date: date,
) -> SelectionResult:
    """
    Select exactly one primary contract from each
    non-empty Cohort 001 stratum.

    Frozen tie-break order:
      1. smallest |delta| distance to stratum midpoint
      2. earlier expiration
      3. lower strike
      4. lexical option symbol

    No Saxo information is accepted by this function.
    Selection therefore cannot depend on whether Saxo
    can resolve the contract.
    """

    quote_list = tuple(quotes)

    if len(
        {
            quote.option_quote_id
            for quote in quote_list
        }
    ) != len(quote_list):
        raise ValueError(
            "option_quote_id values must "
            "be unique."
        )

    selected: list[
        CohortSelection
    ] = []

    empty: list[
        EmptyStratum
    ] = []

    for stratum in all_strata():
        eligible = [
            quote
            for quote in quote_list
            if _belongs_to_stratum(
                quote,
                stratum,
                session_date,
            )
        ]

        if not eligible:
            empty.append(
                EmptyStratum(
                    stratum=stratum
                )
            )
            continue

        winner = min(
            eligible,
            key=lambda quote:
                _selection_sort_key(
                    quote,
                    stratum,
                ),
        )

        dte = _quote_dte(
            winner,
            session_date,
        )

        abs_delta = abs(
            float(
                winner.delta
            )
        )

        selected.append(
            CohortSelection(
                stratum=stratum,
                quote=winner,
                dte=dte,
                abs_delta=abs_delta,
                delta_distance_to_midpoint=(
                    abs(
                        abs_delta
                        - stratum.delta_midpoint
                    )
                ),
            )
        )

    return SelectionResult(
        selected=tuple(selected),
        empty=tuple(empty),
    )


def assign_resolution_sequence(
    selections: Iterable[
        CohortSelection
    ],
    *,
    rng: ShuffleLike | None = None,
) -> tuple[
    CohortSelection,
    ...,
]:
    """
    Randomize only the Saxo-resolution order.

    The selected set is already frozen before this
    function runs. Randomization therefore cannot
    change which contracts were selected.

    Production defaults to SystemRandom. Tests may
    inject random.Random(seed) for deterministic
    verification.
    """

    rng = (
        rng
        if rng is not None
        else SystemRandom()
    )

    shuffled = list(
        selections
    )

    # Protocol uses list[object], while runtime
    # implementations accept any mutable list.
    rng.shuffle(  # type: ignore[arg-type]
        shuffled
    )

    sequenced: list[
        CohortSelection
    ] = []

    for sequence, selection in enumerate(
        shuffled,
        start=1,
    ):
        sequenced.append(
            CohortSelection(
                stratum=(
                    selection.stratum
                ),
                quote=selection.quote,
                dte=selection.dte,
                abs_delta=(
                    selection.abs_delta
                ),
                delta_distance_to_midpoint=(
                    selection
                    .delta_distance_to_midpoint
                ),
                resolution_sequence=sequence,
            )
        )

    return tuple(sequenced)


def selected_quote_ids(
    selections: Iterable[
        CohortSelection
    ],
) -> frozenset[int]:
    return frozenset(
        selection.quote.option_quote_id
        for selection in selections
    )


def make_test_rng(
    seed: int,
) -> Random:
    """
    Convenience helper for deterministic tests only.

    Production callers should not pass a seeded RNG.
    """
    return Random(seed)
