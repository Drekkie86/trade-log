from __future__ import annotations

from datetime import date

from validate_thetadata_massive_universe import (
    in_window,
    massive_identity_key,
    normalize_right,
)


def test_normalize_right_c():
    assert normalize_right("C") == "CALL"


def test_normalize_right_put():
    assert normalize_right("put") == "PUT"


def test_massive_key_uses_snapshot_underlying():
    assert massive_identity_key(
        "JPM",
        {
            "expiration": "2026-09-18",
            "strike": 200.0,
            "right": "P",
        },
    ) == (
        "JPM",
        "2026-09-18",
        200.0,
        "PUT",
    )


def test_window_uses_historical_as_of_date():
    assert in_window(
        ("AAPL", "2026-08-28", 200.0, "CALL"),
        date(2026, 8, 28),
        0,
        45,
    )
