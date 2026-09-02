from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.database.repository import (
    get_connection,
    transaction,
)


QUOTE_CLASSIFIER_VERSION = (
    "SAXO_QUOTE_CLASSIFIER_V1"
)

QUOTE_QUALITIES = {
    "EXECUTABLE",
    "DELAYED",
    "INDICATIVE",
    "STALE",
    "UNAVAILABLE",
}

FAILURE_STAGES = {
    "ROOT_RESOLUTION",
    "CONTRACT_RESOLUTION",
    "IDENTITY_VALIDATION",
    "QUOTE_FETCH",
    "UNDERLYING_FETCH",
    "AUTHENTICATION",
    "NETWORK",
    "UNKNOWN",
}


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_iso(
    value: str | None,
) -> datetime | None:
    if not value:
        return None

    normalized = value.strip()

    if normalized.endswith("Z"):
        normalized = (
            normalized[:-1]
            + "+00:00"
        )

    parsed = datetime.fromisoformat(
        normalized
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


def _gap_seconds(
    later: str | None,
    earlier: str | None,
) -> float | None:
    later_dt = _parse_iso(
        later
    )

    earlier_dt = _parse_iso(
        earlier
    )

    if (
        later_dt is None
        or earlier_dt is None
    ):
        return None

    gap = (
        later_dt
        - earlier_dt
    ).total_seconds()

    if gap < 0:
        return None

    return gap


def _normalise_right(
    value: str,
) -> str:
    normalized = (
        value.strip()
        .upper()
    )

    if normalized in {
        "C",
        "CALL",
    }:
        return "C"

    if normalized in {
        "P",
        "PUT",
    }:
        return "P"

    raise ValueError(
        f"Unsupported option right: "
        f"{value!r}"
    )


def _validate_quality(
    quality: str,
) -> None:
    if quality not in QUOTE_QUALITIES:
        raise ValueError(
            "Invalid quote quality: "
            f"{quality}"
        )


def create_provider_model_observation(
    *,
    option_quote_id: int,
    provider: str,
    implied_volatility:
        float | None = None,
    delta:
        float | None = None,
    gamma:
        float | None = None,
    theta:
        float | None = None,
    vega:
        float | None = None,
    ingested_at:
        str | None = None,
    observed_at:
        str | None = None,
    model_name:
        str | None = None,
    provider_request_id:
        str | None = None,
    model_underlying_price:
        float | None = None,
    model_rate:
        float | None = None,
    model_dividend_yield:
        float | None = None,
    model_input_notes:
        str | None = None,
    db_path=None,
    conn=None,
) -> int:

    if not provider.strip():
        raise ValueError(
            "Provider cannot be blank."
        )

    values = (
        implied_volatility,
        delta,
        gamma,
        theta,
        vega,
    )

    if all(
        value is None
        for value in values
    ):
        raise ValueError(
            "Provider model observation "
            "requires at least one model value."
        )

    ingested_at = (
        ingested_at
        or utc_now_iso()
    )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:

        cursor = connection.execute(
            """
            INSERT INTO provider_model_observations (
                option_quote_id,
                provider,
                ingested_at,
                observed_at,
                source,
                model_name,
                provider_request_id,
                implied_volatility,
                delta,
                gamma,
                theta,
                vega,
                model_underlying_price,
                model_rate,
                model_dividend_yield,
                model_input_notes
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                'PROVIDER_DERIVED',
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            );
            """,
            (
                option_quote_id,
                provider.strip(),
                ingested_at,
                observed_at,
                model_name,
                provider_request_id,
                implied_volatility,
                delta,
                gamma,
                theta,
                vega,
                model_underlying_price,
                model_rate,
                model_dividend_yield,
                model_input_notes,
            ),
        )

        return cursor.lastrowid



def create_provider_model_observations(
    observations: list[dict[str, Any]],
    *,
    db_path=None,
    conn=None,
) -> int:
    """
    Persist provider-derived model observations in one transaction.

    This is the bulk companion to create_provider_model_observation().
    Validation intentionally mirrors the single-row API while avoiding a
    connection/transaction per Greek row during live chain persistence.
    """
    if not observations:
        return 0

    rows: list[tuple[Any, ...]] = []

    for observation in observations:
        provider = str(
            observation.get("provider")
            or ""
        ).strip()

        if not provider:
            raise ValueError(
                "Provider cannot be blank."
            )

        values = (
            observation.get(
                "implied_volatility"
            ),
            observation.get("delta"),
            observation.get("gamma"),
            observation.get("theta"),
            observation.get("vega"),
        )

        if all(
            value is None
            for value in values
        ):
            raise ValueError(
                "Provider model observation "
                "requires at least one model value."
            )

        ingested_at = (
            observation.get("ingested_at")
            or utc_now_iso()
        )

        rows.append(
            (
                int(
                    observation[
                        "option_quote_id"
                    ]
                ),
                provider,
                ingested_at,
                observation.get(
                    "observed_at"
                ),
                observation.get(
                    "model_name"
                ),
                observation.get(
                    "provider_request_id"
                ),
                observation.get(
                    "implied_volatility"
                ),
                observation.get("delta"),
                observation.get("gamma"),
                observation.get("theta"),
                observation.get("vega"),
                observation.get(
                    "model_underlying_price"
                ),
                observation.get(
                    "model_rate"
                ),
                observation.get(
                    "model_dividend_yield"
                ),
                observation.get(
                    "model_input_notes"
                ),
            )
        )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:
        connection.executemany(
            """
            INSERT INTO provider_model_observations (
                option_quote_id,
                provider,
                ingested_at,
                observed_at,
                source,
                model_name,
                provider_request_id,
                implied_volatility,
                delta,
                gamma,
                theta,
                vega,
                model_underlying_price,
                model_rate,
                model_dividend_yield,
                model_input_notes
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                'PROVIDER_DERIVED',
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            );
            """,
            rows,
        )

    return len(rows)


def create_saxo_underlying_observation(
    *,
    research_snapshot_id: int,
    underlying: str,
    quote,
    source_snapshot_captured_at: str,
    massive_observed_at:
        str | None = None,
    ingested_at:
        str | None = None,
    retry_count: int = 0,
    quote_quality_version:
        str = QUOTE_CLASSIFIER_VERSION,
    db_path=None,
    conn=None,
) -> int:

    if not underlying.strip():
        raise ValueError(
            "Underlying cannot be blank."
        )

    if retry_count < 0:
        raise ValueError(
            "retry_count cannot be negative."
        )

    quality = (
        quote.quality.value
    )

    _validate_quality(
        quality
    )

    ingested_at = (
        ingested_at
        or utc_now_iso()
    )

    ingestion_gap_seconds = (
        _gap_seconds(
            ingested_at,
            source_snapshot_captured_at,
        )
    )

    observation_gap_seconds = (
        _gap_seconds(
            quote.last_updated,
            massive_observed_at,
        )
    )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:

        cursor = connection.execute(
            """
            INSERT INTO saxo_underlying_observations (
                research_snapshot_id,
                underlying,
                uic,
                asset_type,
                ingested_at,
                observed_at,
                source_snapshot_captured_at,
                ingestion_gap_seconds,
                bid,
                ask,
                provider_mid,
                computed_mid,
                reference_price,
                bid_size,
                ask_size,
                delayed_by_minutes,
                market_state,
                price_source,
                price_source_type,
                price_type_bid,
                price_type_ask,
                quote_quality,
                is_executable,
                quote_quality_version,
                is_stale,
                is_indicative,
                is_delayed,
                is_locked,
                is_crossed,
                observation_gap_seconds,
                retry_count
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            );
            """,
            (
                research_snapshot_id,
                underlying.strip().upper(),
                quote.uic,
                quote.asset_type,
                ingested_at,
                quote.last_updated,
                source_snapshot_captured_at,
                ingestion_gap_seconds,
                quote.bid,
                quote.ask,
                quote.mid,
                quote.computed_mid,
                quote.reference_price,
                quote.bid_size,
                quote.ask_size,
                quote.delayed_by_minutes,
                quote.market_state,
                quote.price_source,
                quote.price_source_type,
                quote.price_type_bid,
                quote.price_type_ask,
                quality,
                int(
                    quote.is_executable
                ),
                quote_quality_version,
                int(
                    quote.is_stale
                ),
                int(
                    quote.is_indicative
                ),
                int(
                    quote.is_delayed
                ),
                int(
                    quote.is_locked
                ),
                int(
                    quote.is_crossed
                ),
                observation_gap_seconds,
                retry_count,
            ),
        )

        return cursor.lastrowid


def create_saxo_option_observation(
    *,
    option_quote_id: int,
    contract,
    quote,
    source_snapshot_captured_at: str,
    source_quote_at:
        str | None = None,
    massive_observed_at:
        str | None = None,
    ingested_at:
        str | None = None,
    retry_count: int = 0,
    resolution_sequence:
        int | None = None,
    quote_quality_version:
        str = QUOTE_CLASSIFIER_VERSION,
    db_path=None,
    conn=None,
) -> int:

    if retry_count < 0:
        raise ValueError(
            "retry_count cannot be negative."
        )

    if (
        resolution_sequence is not None
        and resolution_sequence <= 0
    ):
        raise ValueError(
            "resolution_sequence must "
            "be positive."
        )

    quality = (
        quote.quality.value
    )

    _validate_quality(
        quality
    )

    ingested_at = (
        ingested_at
        or utc_now_iso()
    )

    ingestion_gap_seconds = (
        _gap_seconds(
            ingested_at,
            source_snapshot_captured_at,
        )
    )

    observation_gap_seconds = (
        _gap_seconds(
            quote.last_updated,
            massive_observed_at,
        )
    )

    right = _normalise_right(
        contract.put_call
    )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:

        cursor = connection.execute(
            """
            INSERT INTO saxo_option_observations (
                option_quote_id,
                ingested_at,
                observed_at,
                source_snapshot_captured_at,
                source_quote_at,
                ingestion_gap_seconds,
                uic,
                option_root_id,
                underlying_uic,
                underlying,
                right,
                strike,
                expiration,
                trading_status,
                contract_size,
                bid,
                ask,
                provider_mid,
                computed_mid,
                bid_size,
                ask_size,
                delayed_by_minutes,
                market_state,
                price_source,
                price_source_type,
                price_type_bid,
                price_type_ask,
                quote_quality,
                is_executable,
                quote_quality_version,
                is_stale,
                is_indicative,
                is_delayed,
                is_locked,
                is_crossed,
                observation_gap_seconds,
                retry_count,
                resolution_sequence
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            );
            """,
            (
                option_quote_id,
                ingested_at,
                quote.last_updated,
                source_snapshot_captured_at,
                source_quote_at,
                ingestion_gap_seconds,
                contract.uic,
                contract.option_root_id,
                contract.underlying_uic,
                contract.underlying.upper(),
                right,
                contract.strike,
                contract.expiration,
                contract.trading_status,
                contract.contract_size,
                quote.bid,
                quote.ask,
                quote.mid,
                quote.computed_mid,
                quote.bid_size,
                quote.ask_size,
                quote.delayed_by_minutes,
                quote.market_state,
                quote.price_source,
                quote.price_source_type,
                quote.price_type_bid,
                quote.price_type_ask,
                quality,
                int(
                    quote.is_executable
                ),
                quote_quality_version,
                int(
                    quote.is_stale
                ),
                int(
                    quote.is_indicative
                ),
                int(
                    quote.is_delayed
                ),
                int(
                    quote.is_locked
                ),
                int(
                    quote.is_crossed
                ),
                observation_gap_seconds,
                retry_count,
                resolution_sequence,
            ),
        )

        return cursor.lastrowid


def create_saxo_resolution_failure(
    *,
    research_snapshot_id: int,
    option_quote_id: int,
    underlying: str,
    right: str,
    strike: float,
    expiration: str,
    failure_stage: str,
    failure_reason: str,
    provider_contract_id:
        str | None = None,
    option_symbol:
        str | None = None,
    shares_per_contract:
        float | None = None,
    failure_code:
        str | None = None,
    attempted_at:
        str | None = None,
    retry_count: int = 0,
    resolution_sequence:
        int | None = None,
    db_path=None,
    conn=None,
) -> int:

    if failure_stage not in FAILURE_STAGES:
        raise ValueError(
            "Invalid Saxo failure stage: "
            f"{failure_stage}"
        )

    if not failure_reason.strip():
        raise ValueError(
            "Failure reason cannot be blank."
        )

    if retry_count < 0:
        raise ValueError(
            "retry_count cannot be negative."
        )

    if (
        resolution_sequence is not None
        and resolution_sequence <= 0
    ):
        raise ValueError(
            "resolution_sequence must "
            "be positive."
        )

    attempted_at = (
        attempted_at
        or utc_now_iso()
    )

    normalized_right = (
        _normalise_right(
            right
        )
    )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:

        cursor = connection.execute(
            """
            INSERT INTO saxo_resolution_failures (
                research_snapshot_id,
                option_quote_id,
                attempted_at,
                underlying,
                provider_contract_id,
                option_symbol,
                right,
                strike,
                expiration,
                shares_per_contract,
                failure_stage,
                failure_code,
                failure_reason,
                retry_count,
                resolution_sequence
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            );
            """,
            (
                research_snapshot_id,
                option_quote_id,
                attempted_at,
                underlying.strip().upper(),
                provider_contract_id,
                option_symbol,
                normalized_right,
                float(strike),
                expiration[:10],
                shares_per_contract,
                failure_stage,
                failure_code,
                failure_reason.strip(),
                retry_count,
                resolution_sequence,
            ),
        )

        return cursor.lastrowid


def get_saxo_option_observations(
    option_quote_id: int,
    *,
    db_path=None,
    conn=None,
) -> list[dict[str, Any]]:

    own_connection = (
        conn is None
    )

    connection = (
        get_connection(
            db_path
        )
        if own_connection
        else conn
    )

    try:
        rows = (
            connection.execute(
                """
                SELECT *
                FROM saxo_option_observations
                WHERE option_quote_id = ?
                ORDER BY
                    ingested_at,
                    id;
                """,
                (
                    option_quote_id,
                ),
            )
            .fetchall()
        )

        return [
            dict(row)
            for row in rows
        ]

    finally:
        if own_connection:
            connection.close()


def get_saxo_resolution_failures(
    research_snapshot_id: int,
    *,
    db_path=None,
    conn=None,
) -> list[dict[str, Any]]:

    own_connection = (
        conn is None
    )

    connection = (
        get_connection(
            db_path
        )
        if own_connection
        else conn
    )

    try:
        rows = (
            connection.execute(
                """
                SELECT *
                FROM saxo_resolution_failures
                WHERE research_snapshot_id = ?
                ORDER BY
                    attempted_at,
                    id;
                """,
                (
                    research_snapshot_id,
                ),
            )
            .fetchall()
        )

        return [
            dict(row)
            for row in rows
        ]

    finally:
        if own_connection:
            connection.close()
