from datetime import date

import pytest

from src.providers.massive import (
    MassiveClient,
    MassiveTruncatedError,
)
from src.research.reference_universe import (
    ReferenceUniverseError,
    reconcile_massive_reference_snapshot,
)


def test_reference_page_uses_reference_endpoint(monkeypatch):
    client = MassiveClient("secret")
    captured = {}

    def fake_get_json(path, params=None):
        captured["path"] = path
        captured["params"] = params
        return {"results": []}

    monkeypatch.setattr(
        MassiveClient,
        "_get_json",
        lambda self, path, params=None: fake_get_json(path, params),
    )

    client.get_option_contracts_reference_page(
        "aapl",
        expiration_date_gte="2026-09-07",
        expiration_date_lte="2026-10-15",
    )

    assert captured["path"] == (
        "/v3/reference/options/contracts"
    )
    assert captured["params"]["underlying_ticker"] == "AAPL"
    assert captured["params"]["expired"] == "false"


def test_reference_window_calculates_dte_bounds(monkeypatch):
    client = MassiveClient("secret")

    monkeypatch.setattr(
        MassiveClient,
        "get_option_contracts_reference_page",
        lambda self, *args, **kwargs: {
            "results": [],
            "request_id": "r1",
            "status": "OK",
        },
    )

    payload = client.get_option_contracts_reference(
        "AAPL",
        min_dte=7,
        max_dte=45,
        as_of_date=date(2026, 8, 31),
    )

    assert payload["window_expiration_gte"] == "2026-09-07"
    assert payload["window_expiration_lte"] == "2026-10-15"
    assert payload["frame_semantics"] == "LISTING_REFERENCE"
    assert payload["truncated"] is False


def test_reference_pagination_fail_closed(monkeypatch):
    client = MassiveClient("secret")

    monkeypatch.setattr(
        MassiveClient,
        "get_option_contracts_reference_page",
        lambda self, *args, **kwargs: {
            "results": [{"ticker": "O:A"}],
            "next_url": "https://api.massive.com/next",
        },
    )

    monkeypatch.setattr(
        MassiveClient,
        "_get_json_url",
        lambda self, url: {
            "results": [{"ticker": "O:B"}],
            "next_url": "https://api.massive.com/still-more",
        },
    )

    with pytest.raises(MassiveTruncatedError):
        client.get_option_contracts_reference(
            "AAPL",
            max_pages=2,
            require_complete=True,
            as_of_date=date(2026, 8, 31),
        )


def test_reconciliation_records_present_and_absent():
    reference_rows = [
        {"ticker": "O:A"},
        {"ticker": "O:B"},
        {"ticker": "O:C"},
    ]
    snapshot_rows = [
        {"details": {"ticker": "O:A"}},
        {"details": {"ticker": "O:C"}},
    ]

    result = reconcile_massive_reference_snapshot(
        reference_rows,
        snapshot_rows,
    )

    assert result.reference_count == 3
    assert result.snapshot_present_count == 2
    assert result.snapshot_absent_count == 1
    assert result.reference_accounting_reconciles

    states = {
        item.provider_contract_id: (
            item.state,
            item.reason_code,
        )
        for item in result.states
    }

    assert states["O:B"] == (
        "ABSENT",
        "SNAPSHOT_ROW_ABSENT",
    )


def test_reconciliation_records_snapshot_only_rows():
    result = reconcile_massive_reference_snapshot(
        [{"ticker": "O:A"}],
        [
            {"details": {"ticker": "O:A"}},
            {"details": {"ticker": "O:EXTRA"}},
        ],
    )

    assert result.snapshot_only_count == 1
    assert result.snapshot_only_ids == ("O:EXTRA",)
    assert result.reference_accounting_reconciles


def test_duplicate_reference_identity_fails_closed():
    with pytest.raises(
        ReferenceUniverseError,
        match="Duplicate reference",
    ):
        reconcile_massive_reference_snapshot(
            [
                {"ticker": "O:A"},
                {"ticker": "O:A"},
            ],
            [],
        )


def test_missing_snapshot_identity_fails_closed():
    with pytest.raises(
        ReferenceUniverseError,
        match="details.ticker",
    ):
        reconcile_massive_reference_snapshot(
            [{"ticker": "O:A"}],
            [{"details": {}}],
        )
