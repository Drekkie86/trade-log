from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
from typing import Any, Mapping

from src.config import get_required_setting
from src.providers.massive import MassiveClient, normalize_massive_option_chain
from src.providers.thetadata import ThetaDataClient, ThetaDataError, theta_identity_key


DEFAULT_SYMBOLS = ("AAPL", "XOM", "JPM")


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
    expiration = row.get("expiration")
    strike = row.get("strike")
    right = row.get("right")

    if expiration in (None, ""):
        raise ValueError("missing expiration")
    if strike is None:
        raise ValueError("missing strike")

    return (
        underlying.upper(),
        str(expiration),
        float(strike),
        normalize_right(right),
    )


def in_window(
    key: tuple[str, str, float, str],
    as_of: date,
    min_dte: int,
    max_dte: int,
) -> bool:
    expiry = date.fromisoformat(key[1])
    return (
        as_of + timedelta(days=min_dte)
        <= expiry
        <= as_of + timedelta(days=max_dte)
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read-only multi-underlying Massive/ThetaData reconciliation."
    )
    p.add_argument(
        "date",
        help="Historical ThetaData date YYYY-MM-DD",
    )
    p.add_argument(
        "--symbols",
        nargs="+",
        default=list(DEFAULT_SYMBOLS),
    )
    p.add_argument("--min-dte", type=int, default=0)
    p.add_argument("--max-dte", type=int, default=45)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    historical_date = date.fromisoformat(args.date)

    massive = MassiveClient(
        api_key=get_required_setting("MASSIVE_API_KEY")
    )
    theta = ThetaDataClient()

    overall_fail = False

    print("Christiania - multi-underlying provider reconciliation")
    print("=====================================================")
    print("Read-only. No database writes. No Saxo calls.")
    print(f"Historical date: {historical_date}")
    print()

    for raw_symbol in args.symbols:
        symbol = raw_symbol.upper()
        print(symbol)
        print("-" * len(symbol))

        try:
            massive_payload = massive.get_option_chain(
                symbol,
                min_dte=args.min_dte,
                max_dte=args.max_dte,
                page_limit=250,
                max_pages=50,
                as_of_date=historical_date,
                require_complete=True,
            )
            _, massive_rows = normalize_massive_option_chain(
                symbol,
                massive_payload,
            )
        except Exception as exc:
            print(f"FAIL Massive: {exc}")
            overall_fail = True
            print()
            continue

        try:
            theta_rows = theta.option_eod_chain_flat(
                symbol,
                historical_date,
                max_dte=args.max_dte,
            )
        except ThetaDataError as exc:
            print(f"FAIL ThetaData: {exc}")
            overall_fail = True
            print()
            continue

        massive_failures: list[str] = []
        theta_failures: list[str] = []

        massive_keys: list[tuple[str, str, float, str]] = []
        theta_keys: list[tuple[str, str, float, str]] = []

        for row in massive_rows:
            try:
                key = massive_identity_key(symbol, row)
                if in_window(
                    key,
                    historical_date,
                    args.min_dte,
                    args.max_dte,
                ):
                    massive_keys.append(key)
            except Exception as exc:
                massive_failures.append(str(exc))

        for row in theta_rows:
            try:
                key = theta_identity_key(row)
                if in_window(
                    key,
                    historical_date,
                    args.min_dte,
                    args.max_dte,
                ):
                    theta_keys.append(key)
            except Exception as exc:
                theta_failures.append(str(exc))

        massive_counter = Counter(massive_keys)
        theta_counter = Counter(theta_keys)

        massive_dupes = sum(
            1 for count in massive_counter.values() if count > 1
        )
        theta_dupes = sum(
            1 for count in theta_counter.values() if count > 1
        )

        massive_set = set(massive_keys)
        theta_set = set(theta_keys)

        matched = massive_set & theta_set
        massive_only = massive_set - theta_set
        theta_only = theta_set - massive_set

        theta_only_expired = {
            key
            for key in theta_only
            if date.fromisoformat(key[1]) < date.today()
        }
        theta_only_live = theta_only - theta_only_expired

        m_cov = len(matched) / len(massive_set) if massive_set else 1.0

        nonexpired_theta = theta_set - theta_only_expired
        t_cov = (
            len(matched & nonexpired_theta) / len(nonexpired_theta)
            if nonexpired_theta
            else 1.0
        )

        print(f"Massive identities:            {len(massive_set)}")
        print(f"ThetaData identities:          {len(theta_set)}")
        print(f"Exact matches:                 {len(matched)}")
        print(f"Massive only:                  {len(massive_only)}")
        print(f"ThetaData only expired:        {len(theta_only_expired)}")
        print(f"ThetaData only nonexpired:     {len(theta_only_live)}")
        print(f"Massive coverage by ThetaData: {m_cov:.4f}")
        print(f"Theta nonexpired coverage:     {t_cov:.4f}")
        print(f"Massive key failures:          {len(massive_failures)}")
        print(f"Theta key failures:            {len(theta_failures)}")
        print(f"Massive duplicate identities:  {massive_dupes}")
        print(f"Theta duplicate identities:    {theta_dupes}")

        if (
            massive_failures
            or theta_failures
            or massive_dupes
            or theta_dupes
            or massive_only
            or theta_only_live
        ):
            overall_fail = True
            print("RESULT: REVIEW")
        else:
            print("RESULT: PASS")

        print()

    if overall_fail:
        print("OVERALL RESULT: REVIEW")
        return 2

    print("OVERALL RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
