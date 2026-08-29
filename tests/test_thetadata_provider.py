from __future__ import annotations

from datetime import date
import json
from urllib.parse import parse_qs, urlparse

import pytest

from src.providers.thetadata import (
    ThetaDataClient,
    ThetaDataResponseError,
    theta_identity_key,
)


def test_accepts_response_envelope():
    payload = {
        "response": [
            {
                "contract": {
                    "symbol": "AAPL",
                    "expiration": "2026-09-25",
                    "strike": 225.0,
                    "right": "PUT",
                },
                "data": [
                    {
                        "bid": 0.01,
                        "ask": 0.09,
                        "created": "2026-08-28T17:15:16.204",
                    }
                ],
            }
        ]
    }

    client = ThetaDataClient(
        transport=lambda url, timeout: json.dumps(payload).encode()
    )
    rows = client.option_eod_chain_raw(
        "AAPL",
        date(2026, 8, 28),
    )

    assert len(rows) == 1
    assert rows[0]["contract"]["strike"] == 225.0


def test_flatten_contract_and_observation():
    payload = {
        "response": [
            {
                "contract": {
                    "symbol": "AAPL",
                    "expiration": "2026-09-25",
                    "strike": 225.0,
                    "right": "PUT",
                },
                "data": [
                    {
                        "bid": 0.01,
                        "ask": 0.09,
                        "bid_size": 111,
                        "ask_size": 98,
                    }
                ],
            }
        ]
    }

    client = ThetaDataClient(
        transport=lambda url, timeout: json.dumps(payload).encode()
    )
    rows = client.option_eod_chain_flat(
        "AAPL",
        date(2026, 8, 28),
    )

    assert rows == (
        {
            "provider": "THETADATA",
            "underlying": "AAPL",
            "expiration": "2026-09-25",
            "strike": 225.0,
            "right": "PUT",
            "bid": 0.01,
            "ask": 0.09,
            "bid_size": 111,
            "ask_size": 98,
        },
    )


def test_flatten_fails_on_multiple_data_rows():
    payload = {
        "response": [
            {
                "contract": {
                    "symbol": "AAPL",
                    "expiration": "2026-09-25",
                    "strike": 225.0,
                    "right": "PUT",
                },
                "data": [{}, {}],
            }
        ]
    }

    client = ThetaDataClient(
        transport=lambda url, timeout: json.dumps(payload).encode()
    )

    with pytest.raises(
        ThetaDataResponseError,
        match="exactly one EOD data row",
    ):
        client.option_eod_chain_flat(
            "AAPL",
            date(2026, 8, 28),
        )


def test_identity_key():
    key = theta_identity_key(
        {
            "underlying": "aapl",
            "expiration": "2026-09-25",
            "strike": 225,
            "right": "put",
        }
    )

    assert key == (
        "AAPL",
        "2026-09-25",
        225.0,
        "PUT",
    )
