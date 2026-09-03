from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from src.database.provider_evidence import (
    create_provider_model_observations,
)
from src.database.repository import (
    assert_schema_version,
    create_market_snapshot,
    get_connection,
    record_provider_observation_availabilities,
)
from src.research.live_pipeline import (
    build_live_join,
    diagnose_admission,
    theta_timing_diagnostics,
)
from src.research.reference_persistence import (
    persist_massive_reference_and_snapshot,
)
from src.research.thetadata_live_adapter import (
    fetch_live_first_order_greek_rows,
    fetch_live_quote_rows,
    filter_dte_window,
)
from src.research.thetadata_live_evidence import (
    find_thetadata_unmatched_evidence,
    persist_thetadata_unmatched_evidence,
)

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

RUNNER_VERSION = "INDEPENDENT_RESEARCH_RUNNER_V1"
ADMISSION_POLICY_VERSION = "STRUCTURAL_ADMISSION_V1"


class IndependentResearchRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class UnderlyingResearchSummary:
    underlying: str
    reference_contracts: int
    massive_snapshot_rows: int
    theta_quote_rows: int
    theta_greek_rows: int
    snapshot_present: int
    snapshot_absent: int
    snapshot_only: int
    theta_unmatched: int
    quote_freshness: dict[str, int]
    greek_quality: dict[str, int]
    structurally_ready: int
    structurally_blocked: int
    market_snapshot_id: int


@dataclass(frozen=True)
class IndependentResearchRunResult:
    run_id: int
    status: str
    us_session_date: str
    us_session_state: str
    summaries: tuple[UnderlyingResearchSummary, ...]


def iso_utc_now() -> str:
    return datetime.now(UTC).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def git_head(repo_root: Path) -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    if completed.returncode != 0:
        raise IndependentResearchRunnerError(
            "Cannot determine Git HEAD: "
            + (
                completed.stderr.strip()
                or completed.stdout.strip()
            )
        )

    value = completed.stdout.strip()
    if not value:
        raise IndependentResearchRunnerError(
            "Git HEAD is blank."
        )

    return value


def classify_us_session(
    observed_at: datetime,
) -> str:
    """
    Simple weekday/clock classifier for evidence labelling.

    This is deliberately not an exchange-holiday calendar. A later market
    calendar should replace it before session-state-sensitive automation.
    """

    if observed_at.tzinfo is None:
        raise ValueError(
            "observed_at must be timezone-aware."
        )

    local = observed_at.astimezone(NY)

    if local.weekday() >= 5:
        return "NON_TRADING_DAY"

    local_time = local.time().replace(
        tzinfo=None
    )

    if local_time < time(9, 30):
        return "PRE_OPEN"

    if local_time <= time(16, 0):
        return "INTRADAY"

    return "POST_CLOSE"


def normalized_run_config(
    *,
    symbols: Iterable[str],
    min_dte: int,
    max_dte: int,
) -> dict[str, Any]:
    normalized_symbols = sorted(
        {
            str(symbol).strip().upper()
            for symbol in symbols
            if str(symbol).strip()
        }
    )

    if not normalized_symbols:
        raise ValueError(
            "At least one underlying is required."
        )

    if min_dte < 0:
        raise ValueError(
            "min_dte cannot be negative."
        )

    if max_dte < min_dte:
        raise ValueError(
            "max_dte cannot be smaller than min_dte."
        )

    return {
        "runner_version":
            RUNNER_VERSION,
        "admission_policy_version":
            ADMISSION_POLICY_VERSION,
        "symbols":
            normalized_symbols,
        "min_dte":
            int(min_dte),
        "max_dte":
            int(max_dte),
        "candidate_creation":
            False,
        "automated_orders":
            False,
    }


def config_hash(config: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(config),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _create_research_run(
    *,
    config: Mapping[str, Any],
    code_git_sha: str,
    observed_at: datetime,
    db_path=None,
) -> int:
    started_at = observed_at.astimezone(
        UTC
    ).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")

    ny = observed_at.astimezone(NY)
    session_state = classify_us_session(
        observed_at
    )

    notes = json.dumps(
        {
            "purpose":
                "independent evidence collection",
            "config":
                dict(config),
            "session_calendar_note":
                "weekday/clock classification only; "
                "exchange holiday calendar not yet integrated",
        },
        sort_keys=True,
    )

    with get_connection(
        db_path
    ) as conn:
        cursor = conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id,
                preregistration_hash,
                code_git_sha,
                started_at,
                us_session_date,
                us_session_state,
                status,
                notes
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                'COLLECTING',
                ?
            );
            """,
            (
                RUNNER_VERSION,
                config_hash(config),
                code_git_sha,
                started_at,
                ny.date().isoformat(),
                session_state,
                notes,
            ),
        )
        run_id = int(
            cursor.lastrowid
        )
        conn.commit()

    return run_id


def _start_underlying(
    *,
    run_id: int,
    underlying: str,
    attempted_at: str,
    db_path=None,
) -> None:
    with get_connection(
        db_path
    ) as conn:
        conn.execute(
            """
            INSERT INTO research_run_underlyings (
                run_id,
                underlying,
                attempted_at,
                status,
                retry_count
            )
            VALUES (?, ?, ?, 'ATTEMPTED', 0);
            """,
            (
                run_id,
                underlying,
                attempted_at,
            ),
        )

        conn.execute(
            """
            UPDATE research_runs
            SET attempted_underlyings =
                attempted_underlyings + 1
            WHERE id = ?;
            """,
            (run_id,),
        )
        conn.commit()


def _finish_underlying(
    *,
    run_id: int,
    underlying: str,
    completed_at: str,
    succeeded: bool,
    failure_reason: str | None = None,
    db_path=None,
) -> None:
    status = (
        "SUCCESS"
        if succeeded
        else "FAILED"
    )

    with get_connection(
        db_path
    ) as conn:
        conn.execute(
            """
            UPDATE research_run_underlyings
            SET
                completed_at = ?,
                status = ?,
                failure_code = ?,
                failure_reason = ?
            WHERE run_id = ?
              AND underlying = ?;
            """,
            (
                completed_at,
                status,
                (
                    None
                    if succeeded
                    else "UNDERLYING_COLLECTION_FAILED"
                ),
                failure_reason,
                run_id,
                underlying,
            ),
        )

        conn.execute(
            """
            UPDATE research_runs
            SET
                succeeded_underlyings =
                    succeeded_underlyings + ?,
                failed_underlyings =
                    failed_underlyings + ?
            WHERE id = ?;
            """,
            (
                int(succeeded),
                int(not succeeded),
                run_id,
            ),
        )

        conn.commit()


def _finish_run(
    *,
    run_id: int,
    status: str,
    notes: str,
    db_path=None,
) -> None:
    if status not in {
        "COMPLETED",
        "FAILED",
    }:
        raise ValueError(
            "Independent runner terminal status must "
            "be COMPLETED or FAILED."
        )

    with get_connection(
        db_path
    ) as conn:
        conn.execute(
            """
            UPDATE research_runs
            SET
                status = ?,
                ended_at = ?,
                notes = notes || ?
            WHERE id = ?;
            """,
            (
                status,
                iso_utc_now(),
                "\n" + notes,
                run_id,
            ),
        )
        conn.commit()


def _reference_contracts_for_join(
    *,
    underlying: str,
    reference_rows: list[dict[str, Any]],
    reference_ids: Mapping[str, int],
) -> list[dict[str, Any]]:
    rows: list[
        dict[str, Any]
    ] = []

    for row in reference_rows:
        ticker = str(
            row["ticker"]
        ).upper()

        contract_type = str(
            row["contract_type"]
        ).lower()

        right = (
            "C"
            if contract_type == "call"
            else "P"
            if contract_type == "put"
            else None
        )

        if right is None:
            raise IndependentResearchRunnerError(
                "Unsupported reference contract_type: "
                f"{contract_type}"
            )

        rows.append(
            {
                "id":
                    int(reference_ids[ticker]),
                "underlying":
                    underlying.upper(),
                "expiration":
                    str(
                        row["expiration_date"]
                    ),
                "strike":
                    float(
                        row["strike_price"]
                    ),
                "right":
                    right,
            }
        )

    return rows


def _theta_option_quote_records(
    quote_rows: tuple[
        dict[str, Any],
        ...
    ],
) -> list[dict[str, Any]]:
    records: list[
        dict[str, Any]
    ] = []

    for row in quote_rows:
        bid = row.get("bid")
        ask = row.get("ask")

        records.append(
            {
                "provider_contract_id":
                    "THETA:"
                    f"{row['underlying']}:"
                    f"{row['expiration']}:"
                    f"{float(row['strike'])}:"
                    f"{row['right']}",
                "option_symbol":
                    None,
                "right":
                    str(row["right"]),
                "strike":
                    float(row["strike"]),
                "expiration":
                    str(row["expiration"]),
                "quote_at":
                    row.get("raw_timestamp"),
                "bid":
                    bid,
                "bid_source":
                    (
                        "FETCHED"
                        if bid is not None
                        else "UNKNOWN"
                    ),
                "bid_at":
                    (
                        row.get("raw_timestamp")
                        if bid is not None
                        else None
                    ),
                "ask":
                    ask,
                "ask_source":
                    (
                        "FETCHED"
                        if ask is not None
                        else "UNKNOWN"
                    ),
                "ask_at":
                    (
                        row.get("raw_timestamp")
                        if ask is not None
                        else None
                    ),
                "last":
                    None,
                "last_source":
                    "UNKNOWN",
                "last_at":
                    None,
                "implied_volatility":
                    None,
                "iv_source":
                    "UNKNOWN",
                "iv_at":
                    None,
                "delta":
                    None,
                "delta_source":
                    "UNKNOWN",
                "delta_at":
                    None,
                "gamma":
                    None,
                "gamma_source":
                    "UNKNOWN",
                "gamma_at":
                    None,
                "theta":
                    None,
                "theta_source":
                    "UNKNOWN",
                "theta_at":
                    None,
                "vega":
                    None,
                "vega_source":
                    "UNKNOWN",
                "vega_at":
                    None,
                "volume":
                    None,
                "volume_source":
                    "UNKNOWN",
                "volume_at":
                    None,
                "open_interest":
                    None,
                "open_interest_source":
                    "UNKNOWN",
                "open_interest_at":
                    None,
            }
        )

    return records


def _persist_theta_market_evidence(
    *,
    run_id: int,
    underlying: str,
    quote_rows: tuple[
        dict[str, Any],
        ...
    ],
    greek_rows: tuple[
        dict[str, Any],
        ...
    ],
    captured_at: datetime,
    us_session_state: str,
    db_path=None,
) -> int:
    captured_utc = captured_at.astimezone(
        UTC
    ).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")

    snapshot_id = create_market_snapshot(
        {
            "captured_at":
                captured_utc,
            "underlying":
                underlying.upper(),
            "provider":
                "THETADATA",
            "provider_snapshot_id":
                None,
            "research_run_id":
                run_id,
            "us_session_date":
                captured_at.astimezone(
                    NY
                ).date().isoformat(),
            "us_session_state":
                us_session_state,
            "underlying_price":
                None,
            "underlying_source":
                "UNKNOWN",
            "underlying_at":
                None,
            "fx_to_eur":
                None,
            "fx_source":
                "UNKNOWN",
            "fx_at":
                None,
            "notes":
                "Independent runner v1 ThetaData "
                "quote snapshot; provider Greeks "
                "persist separately.",
        },
        _theta_option_quote_records(
            quote_rows
        ),
        db_path=db_path,
    )

    with get_connection(
        db_path
    ) as conn:
        quote_id_by_identity = {
            (
                underlying.upper(),
                str(row["expiration"]),
                float(row["strike"]),
                str(row["right"]),
            ):
                int(row["id"])
            for row in conn.execute(
                """
                SELECT
                    id,
                    expiration,
                    strike,
                    right
                FROM option_quotes
                WHERE snapshot_id = ?;
                """,
                (snapshot_id,),
            ).fetchall()
        }

        model_observations: list[dict[str, Any]] = []
        quote_row_by_identity = {
            (
                underlying.upper(),
                str(quote["expiration"]),
                float(quote["strike"]),
                str(quote["right"]),
            ): quote
            for quote in quote_rows
        }

        for greek in greek_rows:
            identity = (
                underlying.upper(),
                str(greek["expiration"]),
                float(greek["strike"]),
                str(greek["right"]),
            )

            option_quote_id = (
                quote_id_by_identity.get(
                    identity
                )
            )

            if option_quote_id is None:
                # The unmatched-provider anomaly path separately preserves
                # this identity. Do not invent an option_quote linkage.
                continue

            timing = theta_timing_diagnostics(
                quote_row=quote_row_by_identity.get(identity),
                greek_row=greek,
                observed_at=captured_at,
            )

            values = {
                "implied_volatility":
                    greek.get("implied_vol"),
                "delta":
                    greek.get("delta"),
                "gamma":
                    greek.get("gamma"),
                "theta":
                    greek.get("theta"),
                "vega":
                    greek.get("vega"),
            }

            if all(
                value is None
                for value in values.values()
            ):
                continue

            model_observations.append(
                {
                    "option_quote_id":
                        option_quote_id,
                    "provider":
                        "THETADATA",
                    "implied_volatility":
                        values[
                            "implied_volatility"
                        ],
                    "delta":
                        values["delta"],
                    "gamma":
                        values["gamma"],
                    "theta":
                        values["theta"],
                    "vega":
                        values["vega"],
                    "ingested_at":
                        captured_utc,
                    "observed_at":
                        greek.get(
                            "raw_timestamp"
                        ),
                    "model_name":
                        "ThetaData first_order snapshot",
                    "model_underlying_price":
                        greek.get(
                            "underlying_price"
                        ),
                    "model_input_notes":
                        json.dumps(
                            {
                                "iv_error":
                                    greek.get(
                                        "iv_error"
                                    ),
                                "underlying_timestamp":
                                    greek.get(
                                        "underlying_timestamp"
                                    ),
                                "provider_raw_timestamp":
                                    greek.get(
                                        "raw_timestamp"
                                    ),
                                "timing_status":
                                    timing["timing_status"],
                            },
                            sort_keys=True,
                            default=str,
                        ),
                    "timing_diagnostic_version":
                        timing["timing_diagnostic_version"],
                    "greek_age_seconds":
                        timing["greek_age_seconds"],
                    "quote_greek_skew_seconds":
                        timing["quote_greek_skew_seconds"],
                    "underlying_greek_skew_seconds":
                        timing["underlying_greek_skew_seconds"],
                }
            )

        create_provider_model_observations(
            model_observations,
            conn=conn,
        )

        conn.commit()

    return snapshot_id


def _persist_theta_availability_batch(
    *,
    joined,
    observed_at: str,
    db_path=None,
) -> int:
    rows: list[
        dict[str, Any]
    ] = []

    for item in joined:
        rows.append(
            {
                "reference_contract_id":
                    item.reference_contract_id,
                "provider":
                    "THETADATA",
                "evidence_family":
                    "THETADATA_QUOTE",
                "state":
                    item.quote_state,
                "reason_code":
                    (
                        None
                        if item.quote_state
                        == "PRESENT"
                        else
                        "QUOTE_OBSERVATION_ABSENT"
                    ),
                "reason_detail":
                    "freshness="
                    f"{item.quote_freshness.value}",
                "observed_at":
                    observed_at,
                "raw_timestamp":
                    (
                        None
                        if item.quote_row
                        is None
                        else
                        item.quote_row.get(
                            "raw_timestamp"
                        )
                    ),
            }
        )

        rows.append(
            {
                "reference_contract_id":
                    item.reference_contract_id,
                "provider":
                    "THETADATA",
                "evidence_family":
                    "THETADATA_GREEKS",
                "state":
                    item.greek_state,
                "reason_code":
                    (
                        None
                        if item.greek_state
                        == "PRESENT"
                        else
                        "MODEL_OBSERVATION_ABSENT"
                    ),
                "reason_detail":
                    "greek_quality="
                    f"{item.greek_quality.value}",
                "observed_at":
                    observed_at,
                "raw_timestamp":
                    (
                        None
                        if item.greek_row
                        is None
                        else
                        item.greek_row.get(
                            "raw_timestamp"
                        )
                    ),
            }
        )

    return (
        record_provider_observation_availabilities(
            rows,
            db_path=db_path,
        )
    )


def collect_underlying(
    *,
    run_id: int,
    underlying: str,
    massive_client,
    theta_client,
    min_dte: int,
    max_dte: int,
    observed_at: datetime,
    observation_clock=None,
    db_path=None,
) -> UnderlyingResearchSummary:
    underlying = (
        underlying.strip().upper()
    )

    reference_date = observed_at.astimezone(
        NY
    ).date()

    observed_utc = observed_at.astimezone(
        UTC
    ).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")

    reference_response = (
        massive_client.get_option_contracts_reference(
            underlying,
            min_dte=min_dte,
            max_dte=max_dte,
            as_of_date=reference_date,
            require_complete=True,
        )
    )

    reference_rows = list(
        reference_response.get(
            "results"
        )
        or []
    )

    snapshot_response = (
        massive_client.get_option_chain(
            underlying,
            min_dte=min_dte,
            max_dte=max_dte,
            as_of_date=reference_date,
            require_complete=True,
        )
    )

    snapshot_rows = list(
        snapshot_response.get(
            "results"
        )
        or []
    )

    reference_persistence = (
        persist_massive_reference_and_snapshot(
            research_run_id=run_id,
            underlying=underlying,
            reference_rows=reference_rows,
            snapshot_rows=snapshot_rows,
            observed_at=observed_utc,
            db_path=db_path,
        )
    )

    reference_ids = (
        reference_persistence[
            "reference_ids"
        ]
    )

    reference_contracts = (
        _reference_contracts_for_join(
            underlying=underlying,
            reference_rows=reference_rows,
            reference_ids=reference_ids,
        )
    )

    quote_rows = filter_dte_window(
        fetch_live_quote_rows(
            theta_client,
            underlying,
        ),
        reference_date=reference_date,
        min_dte=min_dte,
        max_dte=max_dte,
    )

    theta_quote_observed_at = (
        observation_clock()
        if observation_clock is not None
        else datetime.now(NY)
    )
    if theta_quote_observed_at.tzinfo is None:
        raise ValueError(
            "observation_clock must return a timezone-aware datetime."
        )
    theta_quote_observed_at = theta_quote_observed_at.astimezone(NY)
    theta_quote_observed_utc = (
        theta_quote_observed_at.astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )

    greek_rows = filter_dte_window(
        fetch_live_first_order_greek_rows(
            theta_client,
            underlying,
        ),
        reference_date=reference_date,
        min_dte=min_dte,
        max_dte=max_dte,
    )

    joined = build_live_join(
        reference_contracts=
            reference_contracts,
        quote_rows=quote_rows,
        greek_rows=greek_rows,
        observed_at=theta_quote_observed_at,
    )

    diagnostics = diagnose_admission(
        joined
    )

    _persist_theta_availability_batch(
        joined=joined,
        observed_at=theta_quote_observed_utc,
        db_path=db_path,
    )

    unmatched = (
        find_thetadata_unmatched_evidence(
            reference_contracts=
                reference_contracts,
            quote_rows=list(
                quote_rows
            ),
            greek_rows=list(
                greek_rows
            ),
        )
    )

    persist_thetadata_unmatched_evidence(
        research_run_id=run_id,
        unmatched=unmatched,
        observed_at=theta_quote_observed_utc,
        db_path=db_path,
    )

    market_snapshot_id = (
        _persist_theta_market_evidence(
            run_id=run_id,
            underlying=underlying,
            quote_rows=quote_rows,
            greek_rows=greek_rows,
            captured_at=theta_quote_observed_at,
            us_session_state=
                classify_us_session(
                    theta_quote_observed_at
                ),
            db_path=db_path,
        )
    )

    reconciliation = (
        reference_persistence[
            "reconciliation"
        ]
    )

    freshness = Counter(
        item.quote_freshness.value
        for item in diagnostics
    )

    greek_quality = Counter(
        item.greek_quality.value
        for item in diagnostics
    )

    structurally_ready = sum(
        item.structurally_ready
        for item in diagnostics
    )

    return UnderlyingResearchSummary(
        underlying=underlying,
        reference_contracts=
            len(reference_rows),
        massive_snapshot_rows=
            len(snapshot_rows),
        theta_quote_rows=
            len(quote_rows),
        theta_greek_rows=
            len(greek_rows),
        snapshot_present=
            int(
                reconciliation[
                    "snapshot_present_count"
                ]
            ),
        snapshot_absent=
            int(
                reconciliation[
                    "snapshot_absent_count"
                ]
            ),
        snapshot_only=
            int(
                reconciliation[
                    "snapshot_only_count"
                ]
            ),
        theta_unmatched=
            len(unmatched),
        quote_freshness=
            dict(freshness),
        greek_quality=
            dict(greek_quality),
        structurally_ready=
            structurally_ready,
        structurally_blocked=
            len(diagnostics)
            - structurally_ready,
        market_snapshot_id=
            market_snapshot_id,
    )


def run_independent_research(
    *,
    symbols: Iterable[str],
    massive_client,
    theta_client,
    min_dte: int = 7,
    max_dte: int = 45,
    observed_at: datetime | None = None,
    observation_clock=None,
    repo_root: Path | None = None,
    code_git_sha: str | None = None,
    db_path=None,
) -> IndependentResearchRunResult:
    assert_schema_version(
        db_path
    )

    observed_at = (
        observed_at
        or datetime.now(NY)
    )

    if observed_at.tzinfo is None:
        raise ValueError(
            "observed_at must be timezone-aware."
        )

    config = normalized_run_config(
        symbols=symbols,
        min_dte=min_dte,
        max_dte=max_dte,
    )

    sha = (
        code_git_sha
        or git_head(
            repo_root
            or Path(__file__)
            .resolve()
            .parents[2]
        )
    )

    run_id = _create_research_run(
        config=config,
        code_git_sha=sha,
        observed_at=observed_at,
        db_path=db_path,
    )

    summaries: list[
        UnderlyingResearchSummary
    ] = []

    try:
        for underlying in config["symbols"]:
            attempted_at = iso_utc_now()

            _start_underlying(
                run_id=run_id,
                underlying=underlying,
                attempted_at=attempted_at,
                db_path=db_path,
            )

            try:
                summary = collect_underlying(
                    run_id=run_id,
                    underlying=underlying,
                    massive_client=
                        massive_client,
                    theta_client=
                        theta_client,
                    min_dte=min_dte,
                    max_dte=max_dte,
                    observed_at=
                        observed_at,
                    observation_clock=
                        observation_clock,
                    db_path=db_path,
                )
            except Exception as exc:
                _finish_underlying(
                    run_id=run_id,
                    underlying=underlying,
                    completed_at=
                        iso_utc_now(),
                    succeeded=False,
                    failure_reason=
                        f"{type(exc).__name__}: {exc}",
                    db_path=db_path,
                )
                raise
            else:
                summaries.append(
                    summary
                )
                _finish_underlying(
                    run_id=run_id,
                    underlying=underlying,
                    completed_at=
                        iso_utc_now(),
                    succeeded=True,
                    db_path=db_path,
                )

    except Exception as exc:
        _finish_run(
            run_id=run_id,
            status="FAILED",
            notes=(
                "Independent research runner failed: "
                f"{type(exc).__name__}: {exc}"
            ),
            db_path=db_path,
        )
        raise

    _finish_run(
        run_id=run_id,
        status="COMPLETED",
        notes=(
            "Independent evidence collection completed. "
            "No candidate creation or trading action performed."
        ),
        db_path=db_path,
    )

    return IndependentResearchRunResult(
        run_id=run_id,
        status="COMPLETED",
        us_session_date=
            observed_at.astimezone(
                NY
            ).date().isoformat(),
        us_session_state=
            classify_us_session(
                observed_at
            ),
        summaries=
            tuple(summaries),
    )
