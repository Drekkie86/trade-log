from datetime import date

from src.providers.thetadata import ThetaDataClient
from src.research.thetadata_live_adapter import (
    fetch_live_first_order_greek_rows,
    fetch_live_quote_rows,
    filter_dte_window,
)


def transport_for(payload: bytes):
    def transport(url: str, timeout: float) -> bytes:
        return payload
    return transport


def test_quote_snapshot_flattens_and_normalizes():
    payload = b"""
    {
      "response": [
        {
          "contract": {
            "symbol": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245,
            "right": "CALL"
          },
          "data": [
            {
              "bid": 1.0,
              "ask": 1.2,
              "timestamp": "2026-08-31T15:00:00"
            }
          ]
        }
      ]
    }
    """

    client = ThetaDataClient(
        transport=transport_for(payload)
    )

    rows = fetch_live_quote_rows(
        client,
        "AAPL",
    )

    assert len(rows) == 1
    assert rows[0]["underlying"] == "AAPL"
    assert rows[0]["right"] == "C"
    assert rows[0]["strike"] == 245.0
    assert rows[0]["raw_timestamp"] == (
        "2026-08-31T15:00:00"
    )


def test_greek_snapshot_normalizes_put():
    payload = b"""
    {
      "response": [
        {
          "contract": {
            "symbol": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245,
            "right": "PUT"
          },
          "data": [
            {
              "delta": -0.2,
              "implied_vol": 0.3,
              "iv_error": 0.001
            }
          ]
        }
      ]
    }
    """

    client = ThetaDataClient(
        transport=transport_for(payload)
    )

    rows = fetch_live_first_order_greek_rows(
        client,
        "AAPL",
    )

    assert rows[0]["right"] == "P"
    assert rows[0]["implied_vol"] == 0.3
    assert rows[0]["iv_error"] == 0.001


def test_filter_dte_window_is_exact():
    rows = (
        {
            "underlying": "AAPL",
            "expiration": "2026-09-06",
            "strike": 245.0,
            "right": "C",
        },
        {
            "underlying": "AAPL",
            "expiration": "2026-09-07",
            "strike": 245.0,
            "right": "C",
        },
        {
            "underlying": "AAPL",
            "expiration": "2026-10-15",
            "strike": 245.0,
            "right": "C",
        },
        {
            "underlying": "AAPL",
            "expiration": "2026-10-16",
            "strike": 245.0,
            "right": "C",
        },
    )

    filtered = filter_dte_window(
        rows,
        reference_date=date(2026, 8, 31),
        min_dte=7,
        max_dte=45,
    )

    assert [
        row["expiration"]
        for row in filtered
    ] == [
        "2026-09-07",
        "2026-10-15",
    ]
