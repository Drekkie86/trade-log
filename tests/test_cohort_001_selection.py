from datetime import date

import pytest

from src.research.cohort_001 import (
    CohortQuote,
    SelectionUniverseInput,
    all_strata,
    assign_resolution_sequence,
    evaluate_selection_universe,
    make_test_rng,
    select_primary_contracts,
    selected_quote_ids,
)


SESSION_DATE = date(
    2026,
    8,
    28,
)


def quote(
    quote_id: int,
    *,
    right: str = "C",
    strike: float = 320.0,
    expiration: str = "2026-09-11",
    delta: float = 0.15,
    symbol: str | None = None,
) -> CohortQuote:
    return CohortQuote(
        option_quote_id=quote_id,
        provider_contract_id=(
            symbol
            or f"O:TEST{quote_id}"
        ),
        option_symbol=(
            symbol
            or f"O:TEST{quote_id}"
        ),
        right=right,
        strike=strike,
        expiration=expiration,
        delta=delta,
    )


def test_cohort_has_30_frozen_strata():
    strata = all_strata()

    assert len(strata) == 30
    assert len(
        {
            item.key
            for item in strata
        }
    ) == 30


def test_selects_one_per_non_empty_stratum():
    result = select_primary_contracts(
        [
            quote(
                1,
                expiration="2026-09-11",
                delta=0.15,
            ),
            quote(
                2,
                right="P",
                expiration="2026-09-11",
                delta=-0.15,
            ),
        ],
        session_date=SESSION_DATE,
    )

    assert result.selected_count == 2
    assert result.empty_count == 28
    assert result.total_strata == 30


def test_delta_midpoint_is_first_tiebreak():
    result = select_primary_contracts(
        [
            quote(
                1,
                delta=0.11,
            ),
            quote(
                2,
                delta=0.149,
            ),
        ],
        session_date=SESSION_DATE,
    )

    assert (
        result.selected[0]
        .quote.option_quote_id
        == 2
    )


def test_earlier_expiry_is_second_tiebreak():
    result = select_primary_contracts(
        [
            quote(
                1,
                expiration="2026-09-11",
                delta=0.15,
            ),
            quote(
                2,
                expiration="2026-09-10",
                delta=0.15,
            ),
        ],
        session_date=SESSION_DATE,
    )

    selected = [
        item
        for item in result.selected
        if (
            item.stratum.dte_name
            == "DTE_07_14"
            and item.stratum.delta_name
            == "DELTA_010_020"
            and item.stratum.right
            == "C"
        )
    ]

    assert len(selected) == 1
    assert (
        selected[0]
        .quote.option_quote_id
        == 2
    )


def test_lower_strike_is_third_tiebreak():
    result = select_primary_contracts(
        [
            quote(
                1,
                strike=321,
                delta=0.15,
            ),
            quote(
                2,
                strike=319,
                delta=0.15,
            ),
        ],
        session_date=SESSION_DATE,
    )

    assert (
        result.selected[0]
        .quote.option_quote_id
        == 2
    )


def test_lexical_symbol_is_fourth_tiebreak():
    result = select_primary_contracts(
        [
            quote(
                1,
                strike=320,
                delta=0.15,
                symbol="O:ZZZ",
            ),
            quote(
                2,
                strike=320,
                delta=0.15,
                symbol="O:AAA",
            ),
        ],
        session_date=SESSION_DATE,
    )

    assert (
        result.selected[0]
        .quote.option_quote_id
        == 2
    )


def test_quote_id_is_final_total_order_tiebreak():
    first = quote(
        1,
        symbol="O:SAME",
        delta=0.15,
    )

    second = quote(
        2,
        symbol="O:SAME",
        delta=0.15,
    )

    forward = select_primary_contracts(
        [first, second],
        session_date=SESSION_DATE,
    )

    reverse = select_primary_contracts(
        [second, first],
        session_date=SESSION_DATE,
    )

    assert (
        forward.selected[0]
        .quote.option_quote_id
        == 1
    )

    assert (
        reverse.selected[0]
        .quote.option_quote_id
        == 1
    )


def test_put_delta_uses_absolute_value():
    result = select_primary_contracts(
        [
            quote(
                1,
                right="P",
                delta=-0.34,
            ),
        ],
        session_date=SESSION_DATE,
    )

    selected = result.selected[0]

    assert (
        selected.stratum.delta_name
        == "DELTA_020_035"
    )
    assert selected.abs_delta == 0.34


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (0.10, "DELTA_010_020"),
        (0.20, "DELTA_020_035"),
        (0.35, "DELTA_035_050"),
        (0.50, "DELTA_050_065"),
        (0.65, "DELTA_065_080"),
        (0.80, "DELTA_065_080"),
    ],
)
def test_each_delta_boundary_has_one_stratum(
    delta,
    expected,
):
    result = select_primary_contracts(
        [
            quote(
                1,
                delta=delta,
            ),
        ],
        session_date=SESSION_DATE,
    )

    names = {
        item.stratum.delta_name
        for item in result.selected
    }

    assert names == {expected}


def test_duplicate_option_quote_ids_rejected():
    with pytest.raises(
        ValueError,
        match="must be unique",
    ):
        select_primary_contracts(
            [
                quote(1),
                quote(
                    1,
                    strike=321,
                ),
            ],
            session_date=SESSION_DATE,
        )


def test_resolution_randomization_preserves_set():
    selected = (
        select_primary_contracts(
            [
                quote(
                    1,
                    right="C",
                    delta=0.15,
                ),
                quote(
                    2,
                    right="P",
                    delta=-0.15,
                ),
                quote(
                    3,
                    right="C",
                    delta=0.30,
                ),
            ],
            session_date=SESSION_DATE,
        )
        .selected
    )

    sequenced = (
        assign_resolution_sequence(
            selected,
            rng=make_test_rng(123),
        )
    )

    assert (
        selected_quote_ids(selected)
        == selected_quote_ids(
            sequenced
        )
    )

    assert {
        item.resolution_sequence
        for item in sequenced
    } == {
        1,
        2,
        3,
    }


def test_seeded_test_randomization_is_repeatable():
    selected = (
        select_primary_contracts(
            [
                quote(
                    1,
                    right="C",
                    delta=0.15,
                ),
                quote(
                    2,
                    right="P",
                    delta=-0.15,
                ),
                quote(
                    3,
                    right="C",
                    delta=0.30,
                ),
            ],
            session_date=SESSION_DATE,
        )
        .selected
    )

    first = assign_resolution_sequence(
        selected,
        rng=make_test_rng(7),
    )

    second = assign_resolution_sequence(
        selected,
        rng=make_test_rng(7),
    )

    assert [
        item.quote.option_quote_id
        for item in first
    ] == [
        item.quote.option_quote_id
        for item in second
    ]

def universe_input(
    quote_id: int,
    *,
    delta: float | None = 0.15,
    model_count: int = 1,
    symbol: str | None = None,
) -> SelectionUniverseInput:
    resolved_symbol = (
        symbol
        if symbol is not None
        else f"O:TEST{quote_id}"
    )

    return SelectionUniverseInput(
        option_quote_id=quote_id,
        provider="MASSIVE",
        underlying="AAPL",
        provider_contract_id=(
            resolved_symbol
        ),
        option_symbol=(
            resolved_symbol
        ),
        right="C",
        strike=320.0,
        expiration="2026-09-11",
        delta=delta,
        model_observation_count=(
            model_count
        ),
    )


def test_missing_delta_is_explicit_exclusion():
    result = evaluate_selection_universe(
        [
            universe_input(
                1,
                delta=None,
                model_count=1,
            ),
        ]
    )

    assert result.eligible_count == 0
    assert result.exclusion_count == 1
    assert (
        result.exclusions[0]
        .reason_code
        == "MISSING_DELTA"
    )


def test_no_matching_model_is_explicit_exclusion():
    result = evaluate_selection_universe(
        [
            universe_input(
                1,
                delta=None,
                model_count=0,
            ),
        ]
    )

    assert result.eligible_count == 0
    assert result.exclusion_count == 1
    assert (
        result.exclusions[0]
        .reason_code
        == "NO_MATCHING_MODEL_OBSERVATION"
    )


def test_duplicate_model_is_explicit_exclusion():
    result = evaluate_selection_universe(
        [
            universe_input(
                1,
                delta=None,
                model_count=2,
            ),
        ]
    )

    assert result.eligible_count == 0
    assert result.exclusion_count == 1
    assert (
        result.exclusions[0]
        .reason_code
        == "DUPLICATE_MODEL_OBSERVATION"
    )


def test_outside_delta_range_is_counted_exclusion():
    result = evaluate_selection_universe(
        [
            universe_input(
                1,
                delta=0.05,
            ),
            universe_input(
                2,
                delta=0.90,
            ),
        ]
    )

    assert result.eligible_count == 0
    assert result.exclusion_count == 2
    assert {
        item.reason_code
        for item in result.exclusions
    } == {
        "OUTSIDE_DELTA_SAMPLING_RANGE"
    }


def test_selection_universe_reconciles_all_inputs():
    result = evaluate_selection_universe(
        [
            universe_input(
                1,
                delta=0.15,
            ),
            universe_input(
                2,
                delta=None,
            ),
            universe_input(
                3,
                delta=0.95,
            ),
        ]
    )

    assert result.normalized_count == 3
    assert (
        result.eligible_count
        + result.exclusion_count
        == 3
    )

