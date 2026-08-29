"""
Tests for edge_statement_validation.py.

The central tests are the ones that exercise real failure modes already
present in the pack: an overlapping confirmation window (the August 2026
contamination), a loosened independence_unit with no justification, and
results sitting inside a PREREGISTERED document.
"""

from __future__ import annotations

import json

import pytest

from src.research.edge_statement_validation import (
    DiscoveryWindow,
    validate_edge_statement,
    validate_file,
)


def base_document(**overrides):
    doc = {
        "schema_version": "1.0",
        "status": "PREREGISTERED",
        "candidate_id": "EDGE_CANDIDATE_001",
        "family_id": "FAMILY_VOL_RICHNESS",
        "created_at_utc": "2026-09-10T00:00:00Z",
        "created_from_discovery_data_end": "2026-08-31",
        "eligible_population": {"underlyings": ["AAPL"]},
        "setup": {
            "structure": "SHORT_PUT_SPREAD",
            "direction": "SHORT",
            "entry_rule": "IV_RANK_ABOVE_70",
            "exit_rule": "CLOSE_AT_50PCT_PROFIT_OR_21DTE",
            "max_holding_period": "21D",
        },
        "tradability": {
            "bid_must_be_positive": True,
            "max_spread_to_mid": 0.25,
        },
        "estimand": {
            "primary_metric": "NET_EXPECTANCY",
            "comparator": "MATCHED_CONTROL",
            "cost_provenance": "QUOTED",
            "net_of_costs_required": True,
        },
        "confirmation": {
            "data_start": "2026-09-01",
            "data_end": "2026-12-31",
            "independence_unit": "underlying_session",
            "minimum_independent_units": 60,
            "test": "PAIRED_T",
            "alpha_or_q": 0.05,
            "multiplicity_method": "BENJAMINI_HOCHBERG",
            "effect_size_floor": 0.03,
        },
        "searched_family": {
            "features_searched": ["iv_rank"],
            "thresholds_searched": [70, 80, 90],
            "structures_searched": ["SHORT_PUT_SPREAD"],
            "horizons_searched": ["21D"],
            "hypothesis_count": 3,
        },
        "edge_statement": (
            "For AAPL short put spreads when IV rank exceeds 70, "
            "expect positive net expectancy after quoted costs versus "
            "matched controls."
        ),
        "results": {"locked_until_confirmation": True},
    }
    for key, value in overrides.items():
        doc[key] = value
    return doc


AUGUST_WINDOW = (
    DiscoveryWindow(
        "AUGUST_2026_THETADATA",
        "2026-08-01",
        "2026-08-31",
        "AAPL/XOM/JPM ThetaData staging discovery period",
    ),
)


def test_valid_preregistration_passes():
    result = validate_edge_statement(
        base_document(), discovery_windows=AUGUST_WINDOW
    )
    assert result.ok, result.errors


def test_draft_status_is_always_permitted_and_never_trusted():
    result = validate_edge_statement(
        {"status": "DRAFT"}, discovery_windows=AUGUST_WINDOW
    )
    assert result.ok
    assert "not a preregistration" in result.warnings[0]


def test_confirmation_overlapping_august_is_rejected():
    """
    This is the live contamination risk from the review: August 2026 has
    already shaped the screening design and must not be reusable as
    confirmation data.
    """
    doc = base_document()
    doc["confirmation"]["data_start"] = "2026-08-15"

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)

    assert not result.ok
    assert any("overlaps registered discovery window" in e for e in result.errors)


def test_confirmation_starting_before_discovery_data_end_is_rejected():
    doc = base_document()
    doc["confirmation"]["data_start"] = "2026-08-20"
    doc["created_from_discovery_data_end"] = "2026-08-31"

    result = validate_edge_statement(doc, discovery_windows=())

    assert not result.ok
    assert any("does not fall after" in e for e in result.errors)


def test_missing_discovery_data_end_is_rejected():
    doc = base_document()
    doc["created_from_discovery_data_end"] = None

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)

    assert not result.ok
    assert any("created_from_discovery_data_end" in e for e in result.errors)


def test_default_independence_unit_needs_no_justification():
    doc = base_document()
    doc["confirmation"]["independence_unit"] = "underlying_session"

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)
    assert result.ok, result.errors


def test_loosened_independence_unit_without_justification_is_rejected():
    """
    This is the single-word change that would have turned a null result
    into a validated edge with a three-order-of-magnitude inflated N.
    """
    doc = base_document()
    doc["confirmation"]["independence_unit"] = "session"

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)

    assert not result.ok
    assert any("loosens the default" in e for e in result.errors)


def test_loosened_independence_unit_with_justification_is_accepted():
    doc = base_document()
    doc["confirmation"]["independence_unit"] = "session"
    doc["confirmation"]["independence_justification"] = (
        "Cross-underlying paired-edge correlation measured at r=0.05, "
        "95% CI [-0.30, 0.39], n=40 sessions; sessions treated as "
        "independent on this basis."
    )

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)
    assert result.ok, result.errors


def test_unknown_independence_unit_is_rejected():
    doc = base_document()
    doc["confirmation"]["independence_unit"] = "contract"

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)

    assert not result.ok
    assert any("is not one of" in e for e in result.errors)


def test_optional_multiplicity_control_is_rejected():
    doc = base_document()
    doc["confirmation"]["multiplicity_method"] = None

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)

    assert not result.ok
    assert any("multiplicity_method is required" in e for e in result.errors)


def test_results_present_while_preregistered_is_rejected():
    """
    'results.locked_until_confirmation: true' is a comment in an editable
    file, not a lock. Only a separate results file referencing this
    document's hash counts.
    """
    doc = base_document()
    doc["results"] = {
        "locked_until_confirmation": True,
        "net_expectancy": 0.031,
    }

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)

    assert not result.ok
    assert any("results are present while status is PREREGISTERED" in e for e in result.errors)


def test_confirmed_status_requires_preregistration_hash():
    doc = base_document(status="CONFIRMED")
    doc["results"] = {"net_expectancy": 0.031}

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)

    assert not result.ok
    assert any("requires preregistration_sha256" in e for e in result.errors)


def test_confirmed_status_with_hash_and_results_passes():
    doc = base_document(status="CONFIRMED")
    doc["preregistration_sha256"] = "a" * 64
    doc["results"] = {"net_expectancy": 0.031, "ci_low": 0.004}

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)
    assert result.ok, result.errors


def test_assumed_cost_provenance_warns_but_does_not_block():
    doc = base_document()
    doc["estimand"]["cost_provenance"] = "ASSUMED"

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)

    assert result.ok
    assert any("ASSUMED" in w for w in result.warnings)


def test_zero_hypothesis_count_is_rejected():
    doc = base_document()
    doc["searched_family"]["hypothesis_count"] = 0

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)

    assert not result.ok
    assert any("hypothesis_count must be >= 1" in e for e in result.errors)


def test_missing_edge_statement_is_rejected():
    doc = base_document()
    doc["edge_statement"] = None

    result = validate_edge_statement(doc, discovery_windows=AUGUST_WINDOW)

    assert not result.ok
    assert any("edge_statement must be written" in e for e in result.errors)


def test_validate_file_reads_registry_and_document(tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "discovery_windows": [
                    {
                        "window_id": "AUGUST_2026_THETADATA",
                        "start": "2026-08-01",
                        "end": "2026-08-31",
                        "description": "ThetaData staging discovery",
                    }
                ]
            }
        )
    )

    document_path = tmp_path / "candidate.json"
    document_path.write_text(json.dumps(base_document()))

    result = validate_file(document_path, registry)
    assert result.ok, result.errors
    assert result.sha256 is not None
    assert len(result.sha256) == 64


def test_validate_file_missing_registry_raises(tmp_path):
    document_path = tmp_path / "candidate.json"
    document_path.write_text(json.dumps(base_document()))

    with pytest.raises(FileNotFoundError, match="Discovery registry"):
        validate_file(document_path, tmp_path / "missing.json")
