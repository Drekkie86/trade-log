from __future__ import annotations

from datetime import date

import pytest

from reconcile_massive_thetadata_aapl import (
    in_requested_expiry_window,
    massive_identity_key,
    normalize_right,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("C", "CALL"),
        ("c", "CALL"),
        ("CALL", "CALL"),
        ("P", "PUT"),
        ("p", "PUT"),
        ("PUT", "PUT"),
    ],
)
def test_normalize_right(value, expected):
    assert normalize_right(value) == expected


def test_massive_identity_uses_snapshot_underlying_and_c_p_right():
    row = {
        "expiration": "2026-09-25",
        "strike": 225.0,
        "right": "P",
        "option_symbol": "O:AAPL260925P00225000",
    }

    assert massive_identity_key("AAPL", row) == (
        "AAPL",
        "2026-09-25",
        225.0,
        "PUT",
    )


def test_massive_identity_rejects_missing_expiration():
    with pytest.raises(ValueError, match="missing expiration"):
        massive_identity_key(
            "AAPL",
            {"strike": 225.0, "right": "C"},
        )


def test_requested_expiry_window_is_historical_date_based():
    key = ("AAPL", "2026-08-28", 200.0, "CALL")

    assert in_requested_expiry_window(
        key,
        date(2026, 8, 28),
        0,
        45,
    )

    assert not in_requested_expiry_window(
        key,
        date(2026, 8, 29),
        0,
        45,
    )
