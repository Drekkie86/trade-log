from datetime import date

import pytest

from src.research.cohort_001 import (
    CohortQuote,
    all_strata,
    assign_resolution_sequence,
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


def test_boundary_delta_has_one_stratum():
    result = select_primary_contracts(
        [
            quote(
                1,
                delta=0.20,
            ),
        ],
        session_date=SESSION_DATE,
    )

    names = {
        item.stratum.delta_name
        for item in result.selected
    }

    assert "DELTA_010_020" not in names
    assert "DELTA_020_035" in names
    assert len(names) == 1


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
