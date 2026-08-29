from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
from typing import Any, Mapping

from src.config import get_required_setting
from src.providers.massive import (
    MassiveClient,
    normalize_massive_option_chain,
)
from src.providers.thetadata import (
    ThetaDataClient,
    ThetaDataError,
    theta_identity_key,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only one-day Massive <-> ThetaData option identity "
            "reconciliation."
        )
    )
    parser.add_argument("symbol")
    parser.add_argument("date")
    parser.add_argument("--min-dte", type=int, default=0)
    parser.add_argument("--max-dte", type=int, default=45)
    parser.add_argument("--sample", type=int, default=10)
    return parser.parse_args()


def normalize_right(value: object) -> str:
    right = str(value or "").strip().upper()

    if right in {"C", "CALL"}:
        return "CALL"

    if right in {"P", "PUT"}:
        return "PUT"

    raise ValueError(f"Unsupported option right: {value!r}")


def massive_identity_key(
    underlying: str,
    row: Mapping[str, Any],
) -> tuple[str, str, float, str]:
    """
    Build canonical identity from Christiania's normalized Massive quote.

    Important: normalize_massive_option_chain() stores the underlying at
    snapshot level, not on every option quote, and encodes right as C/P.
    """
    symbol = underlying.strip().upper()
    if not symbol:
        raise ValueError("Underlying cannot be blank.")

    expiration = row.get("expiration")
    strike = row.get("strike")
    right = row.get("right")

    if expiration in (None, ""):
        raise ValueError(
            f"Massive normalized row missing expiration: {row}"
        )

    if strike is None:
        raise ValueError(
            f"Massive normalized row missing strike: {row}"
        )

    return (
        symbol,
        str(expiration),
        float(strike),
        normalize_right(right),
    )


def in_requested_expiry_window(
    key: tuple[str, str, float, str],
    trading_date: date,
    min_dte: int,
    max_dte: int,
) -> bool:
    expiration = date.fromisoformat(key[1])
    return (
        trading_date + timedelta(days=min_dte)
        <= expiration
        <= trading_date + timedelta(days=max_dte)
    )


def main() -> int:
    args = parse_args()

    if args.min_dte < 0:
        print("FAIL: --min-dte cannot be negative.")
        return 2

    if args.max_dte < args.min_dte:
        print("FAIL: --max-dte cannot be smaller than --min-dte.")
        return 2

    trading_date = date.fromisoformat(args.date)
    symbol = args.symbol.upper()

    print("Christiania - Massive <-> ThetaData reconciliation v2")
    print("=====================================================")
    print("Read-only. No database writes. No Saxo calls.")
    print(f"Symbol: {symbol}")
    print(f"Historical ThetaData date: {trading_date.isoformat()}")
    print(
        "Important: Massive is a current snapshot source here; ThetaData "
        "is historical EOD."
    )
    print()

    massive = MassiveClient(
        api_key=get_required_setting("MASSIVE_API_KEY")
    )

    try:
        # Use the historical date only to define the requested expiry window.
        # Massive still returns its current snapshot, so already-expired
        # contracts may legitimately be absent.
        massive_payload = massive.get_option_chain(
            symbol,
            min_dte=args.min_dte,
            max_dte=args.max_dte,
            page_limit=250,
            max_pages=50,
            as_of_date=trading_date,
            require_complete=True,
        )

        _, massive_rows = normalize_massive_option_chain(
            symbol,
            massive_payload,
        )

    except Exception as exc:
        print(f"FAIL Massive: {exc}")
        return 1

    try:
        theta_rows = ThetaDataClient().option_eod_chain_flat(
            symbol,
            trading_date,
            max_dte=args.max_dte,
        )
    except ThetaDataError as exc:
        print(f"FAIL ThetaData: {exc}")
        return 1

    massive_keys: list[tuple[str, str, float, str]] = []
    theta_keys: list[tuple[str, str, float, str]] = []

    massive_failures: list[str] = []
    theta_failures: list[str] = []

    for row in massive_rows:
        try:
            key = massive_identity_key(symbol, row)
            if in_requested_expiry_window(
                key,
                trading_date,
                args.min_dte,
                args.max_dte,
            ):
                massive_keys.append(key)
        except Exception as exc:
            massive_failures.append(str(exc))

    for row in theta_rows:
        try:
            key = theta_identity_key(row)
            if in_requested_expiry_window(
                key,
                trading_date,
                args.min_dte,
                args.max_dte,
            ):
                theta_keys.append(key)
        except Exception as exc:
            theta_failures.append(str(exc))

    massive_counter = Counter(massive_keys)
    theta_counter = Counter(theta_keys)

    massive_dupes = {
        key: count
        for key, count in massive_counter.items()
        if count > 1
    }
    theta_dupes = {
        key: count
        for key, count in theta_counter.items()
        if count > 1
    }

    massive_set = set(massive_keys)
    theta_set = set(theta_keys)

    matched = massive_set & theta_set
    massive_only = massive_set - theta_set
    theta_only = theta_set - massive_set

    expired_by_now_theta_only = {
        key
        for key in theta_only
        if date.fromisoformat(key[1]) < date.today()
    }

    theta_only_not_expired = theta_only - expired_by_now_theta_only

    print("COUNTS")
    print(f"Massive normalized rows:       {len(massive_rows)}")
    print(f"ThetaData flattened rows:      {len(theta_rows)}")
    print(f"Massive comparable identities: {len(massive_set)}")
    print(f"ThetaData comparable identities:{len(theta_set)}")
    print(f"Exact identity matches:        {len(matched)}")
    print(f"Massive only:                  {len(massive_only)}")
    print(f"ThetaData only:                {len(theta_only)}")
    print(
        f"ThetaData-only already expired:{len(expired_by_now_theta_only)}"
    )
    print(
        f"ThetaData-only not expired:    {len(theta_only_not_expired)}"
    )
    print(f"Massive key failures:          {len(massive_failures)}")
    print(f"ThetaData key failures:        {len(theta_failures)}")
    print(f"Massive duplicate identities:  {len(massive_dupes)}")
    print(f"ThetaData duplicate identities:{len(theta_dupes)}")
    print()

    union = massive_set | theta_set
    jaccard = len(matched) / len(union) if union else 1.0

    massive_coverage = (
        len(matched) / len(massive_set)
        if massive_set
        else 1.0
    )

    theta_coverage = (
        len(matched) / len(theta_set)
        if theta_set
        else 1.0
    )

    nonexpired_theta_denominator = (
        theta_set - expired_by_now_theta_only
    )
    theta_nonexpired_coverage = (
        len(matched & nonexpired_theta_denominator)
        / len(nonexpired_theta_denominator)
        if nonexpired_theta_denominator
        else 1.0
    )

    print("IDENTITY COVERAGE")
    print(f"Jaccard exact-match ratio:     {jaccard:.4f}")
    print(f"Massive covered by ThetaData:  {massive_coverage:.4f}")
    print(f"ThetaData covered by Massive:  {theta_coverage:.4f}")
    print(
        "ThetaData nonexpired covered: "
        f"{theta_nonexpired_coverage:.4f}"
    )
    print()

    sample_n = max(0, args.sample)

    if massive_only:
        print("SAMPLE MASSIVE-ONLY IDENTITIES")
        for key in sorted(massive_only)[:sample_n]:
            print(key)
        print()

    if theta_only_not_expired:
        print("SAMPLE THETADATA-ONLY, NOT-EXPIRED IDENTITIES")
        for key in sorted(theta_only_not_expired)[:sample_n]:
            print(key)
        print()

    if expired_by_now_theta_only:
        print("SAMPLE THETADATA-ONLY, ALREADY-EXPIRED IDENTITIES")
        for key in sorted(expired_by_now_theta_only)[:sample_n]:
            print(key)
        print()

    if massive_failures:
        print("SAMPLE MASSIVE KEY FAILURES")
        for failure in massive_failures[:sample_n]:
            print(failure)
        print()

    if theta_failures:
        print("SAMPLE THETADATA KEY FAILURES")
        for failure in theta_failures[:sample_n]:
            print(failure)
        print()

    if massive_failures or theta_failures:
        print("FAIL: identity-key construction failures exist.")
        return 2

    if massive_dupes or theta_dupes:
        print("FAIL: duplicate canonical identities exist.")
        return 2

    print("RECONCILIATION COMPLETE.")
    print(
        "Historical/current-snapshot timing differences remain expected. "
        "Review the not-expired unmatched population before ingestion."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
