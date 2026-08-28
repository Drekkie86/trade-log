from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from src.database.provider_evidence import (
    create_provider_model_observation,
    create_saxo_option_observation,
    create_saxo_resolution_failure,
    create_saxo_underlying_observation,
    utc_now_iso,
)
from src.database.repository import (
    create_market_snapshot,
    get_market_snapshot,
)
from src.providers.bridge import (
    bridge_massive_quote_to_saxo,
)
from src.providers.massive import (
    normalize_massive_option_chain_for_research,
)
from src.research.cohort_001 import (
    CohortQuote,
    assign_resolution_sequence,
    select_primary_contracts,
)
from src.research.cohort_001_persistence import (
    create_research_run,
    freeze_selection_manifest,
    persist_normalization_drops,
    set_massive_collection_counts,
    set_run_status,
)


@dataclass(frozen=True)
class CohortRunResult:
    run_id: int
    snapshot_id: int | None
    selected_contract_count: int
    saxo_resolution_success_count: int
    saxo_resolution_failure_count: int
    status: str


def _record_provider_attempt(
    conn,
    *,
    run_id: int,
    provider: str,
    operation: str,
    underlying: str | None,
    attempted_at: str,
    completed_at: str | None,
    succeeded: bool,
    retry_count: int = 0,
    request_id: str | None = None,
    failure_code: str | None = None,
    failure_reason: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO research_provider_attempts (
            run_id,
            provider,
            operation,
            underlying,
            attempted_at,
            completed_at,
            succeeded,
            retry_count,
            request_id,
            failure_code,
            failure_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            run_id,
            provider,
            operation,
            underlying,
            attempted_at,
            completed_at,
            int(succeeded),
            retry_count,
            request_id,
            failure_code,
            failure_reason,
        ),
    )

    conn.execute(
        """
        UPDATE research_runs
        SET
            provider_requests_attempted =
                provider_requests_attempted + 1,
            provider_requests_succeeded =
                provider_requests_succeeded + ?,
            provider_requests_failed =
                provider_requests_failed + ?
        WHERE id = ?;
        """,
        (
            int(succeeded),
            int(not succeeded),
            run_id,
        ),
    )


def _start_underlying_attempt(
    conn,
    *,
    run_id: int,
    underlying: str,
    attempted_at: str,
) -> None:
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


def _finish_underlying_attempt(
    conn,
    *,
    run_id: int,
    underlying: str,
    completed_at: str,
    succeeded: bool,
    failure_code: str | None = None,
    failure_reason: str | None = None,
) -> None:
    status = (
        "SUCCESS"
        if succeeded
        else "FAILED"
    )

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
            failure_code,
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


def _quote_rows_by_symbol(
    snapshot_record: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    mapped: dict[
        str,
        dict[str, Any],
    ] = {}

    for row in (
        snapshot_record.get("quotes")
        or []
    ):
        symbol = (
            row.get("option_symbol")
            or row.get(
                "provider_contract_id"
            )
        )

        if symbol:
            mapped[str(symbol)] = row

    return mapped


def _normalized_quotes_by_symbol(
    quotes: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    mapped: dict[
        str,
        dict[str, Any],
    ] = {}

    for quote in quotes:
        symbol = (
            quote.get("option_symbol")
            or quote.get(
                "provider_contract_id"
            )
        )

        if symbol:
            mapped[str(symbol)] = quote

    return mapped


def _model_rows_by_symbol(
    model_observations,
):
    return {
        str(
            model.option_symbol
            or model.provider_contract_id
        ): model
        for model in model_observations
        if (
            model.option_symbol
            or model.provider_contract_id
        )
    }


def _cohort_quotes_from_model_evidence(
    *,
    snapshot_record: dict[str, Any],
    model_observations,
) -> list[CohortQuote]:
    quote_rows = (
        _quote_rows_by_symbol(
            snapshot_record
        )
    )

    models = _model_rows_by_symbol(
        model_observations
    )

    cohort_quotes: list[
        CohortQuote
    ] = []

    for symbol, model in models.items():
        if model.delta is None:
            continue

        row = quote_rows.get(
            symbol
        )

        if row is None:
            continue

        cohort_quotes.append(
            CohortQuote(
                option_quote_id=int(
                    row["id"]
                ),
                provider_contract_id=(
                    row.get(
                        "provider_contract_id"
                    )
                ),
                option_symbol=(
                    row.get(
                        "option_symbol"
                    )
                ),
                right=str(
                    row["right"]
                ),
                strike=float(
                    row["strike"]
                ),
                expiration=str(
                    row["expiration"]
                ),
                delta=float(
                    model.delta
                ),
            )
        )

    return cohort_quotes


def _persist_model_observations(
    conn,
    *,
    snapshot_record: dict[str, Any],
    model_observations,
) -> None:
    quote_rows = (
        _quote_rows_by_symbol(
            snapshot_record
        )
    )

    for model in model_observations:
        symbol = (
            model.option_symbol
            or model.provider_contract_id
        )

        if not symbol:
            continue

        row = quote_rows.get(
            str(symbol)
        )

        if row is None:
            continue

        create_provider_model_observation(
            option_quote_id=int(
                row["id"]
            ),
            provider=model.provider,
            implied_volatility=(
                model.implied_volatility
            ),
            delta=model.delta,
            gamma=model.gamma,
            theta=model.theta,
            vega=model.vega,
            observed_at=(
                model.observed_at
            ),
            model_name=(
                "MASSIVE_PROVIDER_MODEL"
            ),
            provider_request_id=(
                model.provider_request_id
            ),
            model_underlying_price=(
                model.model_underlying_price
            ),
            model_rate=(
                model.model_rate
            ),
            model_dividend_yield=(
                model.model_dividend_yield
            ),
            model_input_notes=(
                model.model_input_notes
            ),
            conn=conn,
        )


def _classify_resolution_failure(
    exc: Exception,
) -> tuple[str, str]:
    name = (
        exc.__class__.__name__
        .upper()
    )

    if "AUTH" in name:
        return (
            "AUTHENTICATION",
            name,
        )

    if (
        "NETWORK" in name
        or "URL" in name
    ):
        return (
            "NETWORK",
            name,
        )

    if "IDENTITY" in name:
        return (
            "IDENTITY_VALIDATION",
            name,
        )

    if "CONTRACT" in name:
        return (
            "CONTRACT_RESOLUTION",
            name,
        )

    return (
        "UNKNOWN",
        name,
    )


def run_cohort_001_collection(
    *,
    conn,
    massive_client,
    saxo_client,
    preregistration_hash: str,
    code_git_sha: str,
    us_session_date: str,
    us_session_state: str,
    underlying: str = "AAPL",
    started_at: str | None = None,
    bridge_func: Callable[
        [Any, str, dict[str, Any]],
        Any,
    ] = bridge_massive_quote_to_saxo,
) -> CohortRunResult:
    """
    Execute one Cohort 001 collection in the frozen
    preregistration order:

      1. create run manifest
      2. fetch complete Massive universe
      3. normalize + account for drops
      4. persist snapshot + provider model evidence
      5. select contracts using Massive evidence only
      6. freeze selected set + randomized resolution order
      7. only now resolve selected contracts through Saxo
      8. persist Saxo evidence/failures
      9. terminalize the run

    No Christiania P(profit) is calculated here.
    """

    started_at = (
        started_at
        or utc_now_iso()
    )

    symbol = (
        underlying
        .strip()
        .upper()
    )

    session_date = (
        date.fromisoformat(
            us_session_date[:10]
        )
    )

    run_id = create_research_run(
        conn,
        preregistration_hash=(
            preregistration_hash
        ),
        code_git_sha=code_git_sha,
        started_at=started_at,
        us_session_date=(
            us_session_date[:10]
        ),
        us_session_state=(
            us_session_state
        ),
        notes=(
            "Cohort 001 data-quality "
            "baseline collection."
        ),
    )

    _start_underlying_attempt(
        conn,
        run_id=run_id,
        underlying=symbol,
        attempted_at=started_at,
    )

    massive_attempted_at = (
        utc_now_iso()
    )

    try:
        payload = (
            massive_client
            .get_option_chain(
                symbol,
                min_dte=7,
                max_dte=45,
                contract_type=None,
                require_complete=True,
            )
        )

    except Exception as exc:
        failed_at = utc_now_iso()

        _record_provider_attempt(
            conn,
            run_id=run_id,
            provider="MASSIVE",
            operation=(
                "OPTION_CHAIN_7_45_DTE"
            ),
            underlying=symbol,
            attempted_at=(
                massive_attempted_at
            ),
            completed_at=failed_at,
            succeeded=False,
            failure_code=(
                exc.__class__.__name__
            ),
            failure_reason=str(exc),
        )

        _finish_underlying_attempt(
            conn,
            run_id=run_id,
            underlying=symbol,
            completed_at=failed_at,
            succeeded=False,
            failure_code=(
                exc.__class__.__name__
            ),
            failure_reason=str(exc),
        )

        set_run_status(
            conn,
            run_id=run_id,
            status="FAILED",
            ended_at=failed_at,
            notes=(
                "Massive universe fetch failed."
            ),
        )

        return CohortRunResult(
            run_id=run_id,
            snapshot_id=None,
            selected_contract_count=0,
            saxo_resolution_success_count=0,
            saxo_resolution_failure_count=0,
            status="FAILED",
        )

    massive_completed_at = (
        utc_now_iso()
    )

    request_ids = (
        payload.get("request_ids")
        or []
    )

    if request_ids:
        for request_id in request_ids:
            _record_provider_attempt(
                conn,
                run_id=run_id,
                provider="MASSIVE",
                operation=(
                    "OPTION_CHAIN_PAGE"
                ),
                underlying=symbol,
                attempted_at=(
                    massive_attempted_at
                ),
                completed_at=(
                    massive_completed_at
                ),
                succeeded=True,
                request_id=str(
                    request_id
                ),
            )
    else:
        _record_provider_attempt(
            conn,
            run_id=run_id,
            provider="MASSIVE",
            operation=(
                "OPTION_CHAIN_7_45_DTE"
            ),
            underlying=symbol,
            attempted_at=(
                massive_attempted_at
            ),
            completed_at=(
                massive_completed_at
            ),
            succeeded=True,
            request_id=(
                payload.get(
                    "request_id"
                )
            ),
        )

    normalized = (
        normalize_massive_option_chain_for_research(
            symbol,
            payload,
        )
    )

    set_massive_collection_counts(
        conn,
        run_id=run_id,
        raw_contracts=(
            normalized.raw_contract_count
        ),
        normalized_contracts=(
            normalized
            .normalized_contract_count
        ),
        normalization_drop_count=(
            normalized.drop_count
        ),
    )

    snapshot = dict(
        normalized.snapshot
    )

    snapshot[
        "research_run_id"
    ] = run_id

    snapshot[
        "us_session_date"
    ] = us_session_date[:10]

    snapshot[
        "us_session_state"
    ] = us_session_state

    snapshot_id = (
        create_market_snapshot(
            snapshot,
            normalized.quotes,
            conn=conn,
        )
    )

    persist_normalization_drops(
        conn,
        run_id=run_id,
        snapshot_id=snapshot_id,
        drops=normalized.drops,
        dropped_at=utc_now_iso(),
    )

    snapshot_record = (
        get_market_snapshot(
            snapshot_id,
            conn=conn,
        )
    )

    if snapshot_record is None:
        raise RuntimeError(
            "Freshly created snapshot "
            "could not be reloaded."
        )

    _persist_model_observations(
        conn,
        snapshot_record=snapshot_record,
        model_observations=(
            normalized
            .model_observations
        ),
    )

    cohort_quotes = (
        _cohort_quotes_from_model_evidence(
            snapshot_record=(
                snapshot_record
            ),
            model_observations=(
                normalized
                .model_observations
            ),
        )
    )

    selection_result = (
        select_primary_contracts(
            cohort_quotes,
            session_date=session_date,
        )
    )

    sequenced = (
        assign_resolution_sequence(
            selection_result.selected
        )
    )

    freeze_selection_manifest(
        conn,
        run_id=run_id,
        selections=sequenced,
        empty_strata=(
            selection_result.empty
        ),
        selected_at=utc_now_iso(),
        preregistration_hash=(
            preregistration_hash
        ),
        code_git_sha=code_git_sha,
    )

    normalized_by_symbol = (
        _normalized_quotes_by_symbol(
            normalized.quotes
        )
    )

    source_captured_at = str(
        snapshot_record["snapshot"][
            "captured_at"
        ]
    )

    success_count = 0
    failure_count = 0
    underlying_observed = False

    for selection in sequenced:
        option_symbol = (
            selection.quote.option_symbol
            or
            selection.quote.provider_contract_id
        )

        massive_quote = (
            normalized_by_symbol.get(
                str(option_symbol)
            )
        )

        if massive_quote is None:
            raise RuntimeError(
                "Frozen selection has no "
                "normalized Massive quote."
            )

        attempted_at = utc_now_iso()

        try:
            bridged = bridge_func(
                saxo_client,
                symbol,
                massive_quote,
            )

            completed_at = utc_now_iso()

            create_saxo_option_observation(
                option_quote_id=(
                    selection
                    .quote
                    .option_quote_id
                ),
                contract=(
                    bridged.saxo_contract
                ),
                quote=(
                    bridged.saxo_quote
                ),
                source_snapshot_captured_at=(
                    source_captured_at
                ),
                source_quote_at=(
                    massive_quote.get(
                        "quote_at"
                    )
                ),
                massive_observed_at=(
                    massive_quote.get(
                        "quote_at"
                    )
                ),
                resolution_sequence=(
                    selection
                    .resolution_sequence
                ),
                conn=conn,
            )

            _record_provider_attempt(
                conn,
                run_id=run_id,
                provider="SAXO",
                operation=(
                    "OPTION_RESOLUTION"
                ),
                underlying=symbol,
                attempted_at=attempted_at,
                completed_at=completed_at,
                succeeded=True,
            )

            success_count += 1

            if not underlying_observed:
                try:
                    underlying_quote = (
                        saxo_client
                        .get_option_underlying_quote(
                            bridged.saxo_contract
                        )
                    )

                    create_saxo_underlying_observation(
                        research_snapshot_id=(
                            snapshot_id
                        ),
                        underlying=symbol,
                        quote=(
                            underlying_quote
                        ),
                        source_snapshot_captured_at=(
                            source_captured_at
                        ),
                        massive_observed_at=(
                            snapshot_record[
                                "snapshot"
                            ].get(
                                "underlying_at"
                            )
                        ),
                        conn=conn,
                    )

                    conn.execute(
                        """
                        UPDATE research_runs
                        SET underlying_observation_status =
                            'SUCCESS'
                        WHERE id = ?;
                        """,
                        (run_id,),
                    )

                    underlying_observed = True

                except Exception:
                    conn.execute(
                        """
                        UPDATE research_runs
                        SET underlying_observation_status =
                            'FAILED'
                        WHERE id = ?;
                        """,
                        (run_id,),
                    )

        except Exception as exc:
            completed_at = utc_now_iso()

            (
                failure_stage,
                failure_code,
            ) = _classify_resolution_failure(
                exc
            )

            create_saxo_resolution_failure(
                research_snapshot_id=(
                    snapshot_id
                ),
                option_quote_id=(
                    selection
                    .quote
                    .option_quote_id
                ),
                underlying=symbol,
                right=(
                    selection.quote.right
                ),
                strike=(
                    selection.quote.strike
                ),
                expiration=(
                    selection
                    .quote
                    .expiration
                ),
                provider_contract_id=(
                    selection
                    .quote
                    .provider_contract_id
                ),
                option_symbol=(
                    selection
                    .quote
                    .option_symbol
                ),
                shares_per_contract=(
                    massive_quote.get(
                        "shares_per_contract"
                    )
                ),
                failure_stage=(
                    failure_stage
                ),
                failure_code=(
                    failure_code
                ),
                failure_reason=str(exc),
                attempted_at=attempted_at,
                resolution_sequence=(
                    selection
                    .resolution_sequence
                ),
                conn=conn,
            )

            _record_provider_attempt(
                conn,
                run_id=run_id,
                provider="SAXO",
                operation=(
                    "OPTION_RESOLUTION"
                ),
                underlying=symbol,
                attempted_at=attempted_at,
                completed_at=completed_at,
                succeeded=False,
                failure_code=(
                    failure_code
                ),
                failure_reason=str(exc),
            )

            failure_count += 1

    if not sequenced:
        conn.execute(
            """
            UPDATE research_runs
            SET underlying_observation_status =
                'NOT_ATTEMPTED'
            WHERE id = ?;
            """,
            (run_id,),
        )

    ended_at = utc_now_iso()

    conn.execute(
        """
        UPDATE research_runs
        SET
            saxo_resolution_success_count = ?,
            saxo_resolution_failure_count = ?
        WHERE id = ?;
        """,
        (
            success_count,
            failure_count,
            run_id,
        ),
    )

    _finish_underlying_attempt(
        conn,
        run_id=run_id,
        underlying=symbol,
        completed_at=ended_at,
        succeeded=True,
    )

    set_run_status(
        conn,
        run_id=run_id,
        status="COMPLETED",
        ended_at=ended_at,
    )

    return CohortRunResult(
        run_id=run_id,
        snapshot_id=snapshot_id,
        selected_contract_count=(
            len(sequenced)
        ),
        saxo_resolution_success_count=(
            success_count
        ),
        saxo_resolution_failure_count=(
            failure_count
        ),
        status="COMPLETED",
    )
