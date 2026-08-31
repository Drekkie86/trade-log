import pytest

from src.research.shadow_lifecycle import (
    FreshnessClass,
    GreekQuality,
    ShadowAdmissionQuality,
    ShadowState,
    UniverseStatus,
    can_transition,
    classify_freshness,
    classify_greek_quality,
    require_transition,
)


def test_happy_path_transitions():
    path = [
        ShadowState.SURFACED,
        ShadowState.INVESTIGATED,
        ShadowState.DECIDED,
        ShadowState.SHADOW_TRACKED,
        ShadowState.CLOSED_OR_EXPIRED,
        ShadowState.SCORED,
    ]
    for current, target in zip(path, path[1:]):
        assert can_transition(current, target)
        require_transition(current, target)


def test_rejection_is_terminal():
    assert can_transition(ShadowState.DECIDED, ShadowState.REJECTED)
    assert not can_transition(ShadowState.REJECTED, ShadowState.SURFACED)


def test_invalid_transition_fails_closed():
    with pytest.raises(ValueError):
        require_transition(ShadowState.SURFACED, ShadowState.SHADOW_TRACKED)


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (None, FreshnessClass.UNKNOWN),
        (-1, FreshnessClass.UNKNOWN),
        (0, FreshnessClass.FRESH),
        (15, FreshnessClass.FRESH),
        (15.001, FreshnessClass.AGING),
        (60, FreshnessClass.AGING),
        (60.001, FreshnessClass.STALE),
    ],
)
def test_freshness_classification(age, expected):
    assert classify_freshness(age) is expected


@pytest.mark.parametrize(
    ("iv_error", "expected"),
    [
        (None, GreekQuality.UNKNOWN),
        (0.0, GreekQuality.GOOD),
        (0.005, GreekQuality.GOOD),
        (-0.005, GreekQuality.GOOD),
        (0.0051, GreekQuality.REVIEW),
        (0.02, GreekQuality.REVIEW),
        (0.0201, GreekQuality.BAD),
    ],
)
def test_greek_quality(iv_error, expected):
    assert classify_greek_quality(iv_error) is expected


def test_greek_dependent_admission_requires_fresh_quote_and_good_greeks():
    quality = ShadowAdmissionQuality(
        quote_freshness=FreshnessClass.FRESH,
        greek_quality=GreekQuality.GOOD,
        greek_dependent_rule=True,
        quote_row_present=True,
        greek_row_present=True,
    )
    assert quality.eligible_for_first_shadow_cohort


def test_greek_timestamp_freshness_cannot_replace_quote_row():
    quality = ShadowAdmissionQuality(
        quote_freshness=FreshnessClass.UNKNOWN,
        greek_quality=GreekQuality.GOOD,
        greek_dependent_rule=True,
        quote_row_present=False,
        greek_row_present=True,
    )
    assert not quality.eligible_for_first_shadow_cohort


def test_provider_disagreement_does_not_automatically_block_admission():
    quality = ShadowAdmissionQuality(
        quote_freshness=FreshnessClass.FRESH,
        greek_quality=GreekQuality.GOOD,
        greek_dependent_rule=True,
        quote_row_present=True,
        greek_row_present=True,
        universe_status=UniverseStatus.DISAGREEMENT_RECORDED,
    )
    assert quality.eligible_for_first_shadow_cohort


def test_unusable_universe_blocks_admission():
    quality = ShadowAdmissionQuality(
        quote_freshness=FreshnessClass.FRESH,
        greek_quality=GreekQuality.GOOD,
        greek_dependent_rule=True,
        quote_row_present=True,
        greek_row_present=True,
        universe_status=UniverseStatus.UNUSABLE,
    )
    assert not quality.eligible_for_first_shadow_cohort


def test_non_greek_rule_does_not_require_greek_row():
    quality = ShadowAdmissionQuality(
        quote_freshness=FreshnessClass.FRESH,
        greek_quality=GreekQuality.UNKNOWN,
        greek_dependent_rule=False,
        quote_row_present=True,
        greek_row_present=False,
    )
    assert quality.eligible_for_first_shadow_cohort
