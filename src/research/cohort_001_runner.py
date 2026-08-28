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
    ContractIdentityError,
    OptionBridgeError,
    bridge_massive_quote_to_saxo,
)
from src.providers.saxo import (
    SaxoApiAuthenticationError,
    SaxoContractResolutionError,
    SaxoError,
    SaxoNetworkError,
    SaxoQuoteFetchError,
    SaxoRateLimitError,
    SaxoRootResolutionError,
    SaxoUnderlyingResolutionError,
)
from src.providers.saxo_auth import (
    SaxoAuthenticationError,
)
from src.providers.massive import (
    normalize_massive_option_chain_for_research,
)
from src.research.cohort_001 import (
    SelectionUniverseInput,
    assign_resolution_sequence,
    evaluate_selection_universe,
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


def _selection_inputs_from_model_evidence(
    *,
    snapshot_record: dict[str, Any],
    model_observations,
    provider: str,
    underlying: str,
) -> list[SelectionUniverseInput]:
    """
    Build one selection-stage input for every
    normalized option_quote row.

    Iterating the normalized population first is
    the key integrity rule: a contract cannot
    disappear merely because provider-model delta
    evidence is absent.
    """

    quote_rows = (
        snapshot_record.get("quotes")
        or []
    )

    inputs: list[
        SelectionUniverseInput
    ] = []

    for row in quote_rows:
        identity = (
            row.get("option_symbol")
            or row.get(
                "provider_contract_id"
            )
        )

        matching_models = []

        if identity:
            matching_models = [
                model
                for model
                in model_observations
                if (
                    (
                        model.option_symbol
                        or
                        model.provider_contract_id
                    )
                    == identity
                )
            ]

        delta = None

        if len(
            matching_models
        ) == 1:
            delta = (
                matching_models[0]
                .delta
            )

        inputs.append(
            SelectionUniverseInput(
                option_quote_id=int(
                    row["id"]
                ),
                provider=provider,
                underlying=underlying,
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
                delta=delta,
                model_observation_count=(
                    len(
                        matching_models
                    )
                ),
            )
        )

    return inputs


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
    if isinstance(
        exc,
        (
            SaxoAuthenticationError,
            SaxoApiAuthenticationError,
        ),
    ):
        return (
            "AUTHENTICATION",
            exc.__class__.__name__,
        )

    if isinstance(
        exc,
        SaxoRootResolutionError,
    ):
        return (
            "ROOT_RESOLUTION",
            exc.__class__.__name__,
        )

    if isinstance(
        exc,
        SaxoContractResolutionError,
    ):
        return (
            "CONTRACT_RESOLUTION",
            exc.__class__.__name__,
        )

    if isinstance(
        exc,
        ContractIdentityError,
    ):
        return (
            "IDENTITY_VALIDATION",
            exc.__class__.__name__,
        )

    if isinstance(
        exc,
        SaxoQuoteFetchError,
    ):
        return (
            "QUOTE_FETCH",
            exc.__class__.__name__,
        )

    if isinstance(
        exc,
        (
            SaxoNetworkError,
            SaxoRateLimitError,
        ),
    ):
        return (
            "NETWORK",
            exc.__class__.__name__,
        )

    if isinstance(
        exc,
        SaxoUnderlyingResolutionError,
    ):
        return (
            "UNDERLYING_FETCH",
            exc.__class__.__name__,
        )

    if isinstance(
        exc,
        OptionBridgeError,
    ):
        return (
            "IDENTITY_VALIDATION",
            exc.__class__.__name__,
        )

    if isinstance(exc, SaxoError):
        return (
            getattr(exc, "failure_stage", "UNKNOWN"),
            exc.__class__.__name__,
        )

    return (
        "UNKNOWN",
        exc.__class__.__name__,
    )


def _retry_count_from_client_or_exception(
    saxo_client,
    exc: Exception | None = None,
) -> int:
    if exc is not None:
        value = getattr(exc, "retry_count", None)
        if value is not None:
            return int(value)

    consumer = getattr(
        saxo_client,
        "consume_retry_count",
        None,
    )
    if callable(consumer):
        return int(consumer())

    return 0


def _reset_saxo_retry_counter(
    saxo_client,
) -> None:
    resetter = getattr(
        saxo_client,
        "reset_retry_counter",
        None,
    )
    if callable(resetter):
        resetter()


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
    run_notes: str | None = None,
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
            run_notes
            or (
                "Cohort 001 data-quality "
                "baseline collection."
            )
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
                (
                    f"{run_notes} "
                    if run_notes
                    else ""
                )
                + "Massive universe fetch failed."
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

    selection_inputs = (
        _selection_inputs_from_model_evidence(
            snapshot_record=(
                snapshot_record
            ),
            model_observations=(
                normalized
                .model_observations
            ),
            provider="MASSIVE",
            underlying=symbol,
        )
    )

    selection_universe = (
        evaluate_selection_universe(
            selection_inputs
        )
    )

    if (
        selection_universe
        .normalized_count
        != normalized
        .normalized_contract_count
    ):
        raise RuntimeError(
            "Selection-stage population "
            "does not reconcile to the "
            "normalized Massive universe."
        )

    selection_result = (
        select_primary_contracts(
            selection_universe.eligible,
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
        snapshot_id=snapshot_id,
        selections=sequenced,
        empty_strata=(
            selection_result.empty
        ),
        selection_eligible_count=(
            selection_universe
            .eligible_count
        ),
        selection_exclusions=(
            selection_universe
            .exclusions
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
    run_invalid = False
    invalid_reason: str | None = None

    # B4: collect exactly one independent Saxo
    # underlying observation after the Massive-only
    # selection is frozen, but before randomized
    # option resolution begins.
    underlying_attempted_at = utc_now_iso()
    _reset_saxo_retry_counter(saxo_client)

    try:
        underlying_quote = (
            saxo_client
            .get_underlying_quote_for_symbol(
                symbol
            )
        )
        underlying_completed_at = utc_now_iso()
        underlying_retry_count = (
            _retry_count_from_client_or_exception(
                saxo_client
            )
        )

        create_saxo_underlying_observation(
            research_snapshot_id=snapshot_id,
            underlying=symbol,
            quote=underlying_quote,
            source_snapshot_captured_at=(
                source_captured_at
            ),
            massive_observed_at=(
                snapshot_record[
                    "snapshot"
                ].get("underlying_at")
            ),
            retry_count=underlying_retry_count,
            conn=conn,
        )

        _record_provider_attempt(
            conn,
            run_id=run_id,
            provider="SAXO",
            operation="UNDERLYING_QUOTE",
            underlying=symbol,
            attempted_at=underlying_attempted_at,
            completed_at=underlying_completed_at,
            succeeded=True,
            retry_count=underlying_retry_count,
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

    except Exception as exc:
        underlying_completed_at = utc_now_iso()
        failure_stage, failure_code = (
            _classify_resolution_failure(exc)
        )
        retry_count = (
            _retry_count_from_client_or_exception(
                saxo_client,
                exc,
            )
        )

        _record_provider_attempt(
            conn,
            run_id=run_id,
            provider="SAXO",
            operation="UNDERLYING_QUOTE",
            underlying=symbol,
            attempted_at=underlying_attempted_at,
            completed_at=underlying_completed_at,
            succeeded=False,
            retry_count=retry_count,
            failure_code=failure_code,
            failure_reason=str(exc),
        )

        conn.execute(
            """
            UPDATE research_runs
            SET underlying_observation_status =
                'FAILED'
            WHERE id = ?;
            """,
            (run_id,),
        )

        run_invalid = True
        invalid_reason = (
            "Independent Saxo underlying "
            f"observation failed ({failure_stage})."
        )

    for selection in sequenced:
        option_symbol = (
            selection.quote.option_symbol
            or selection.quote.provider_contract_id
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
        _reset_saxo_retry_counter(saxo_client)

        try:
            bridged = bridge_func(
                saxo_client,
                symbol,
                massive_quote,
            )
        except Exception as exc:
            completed_at = utc_now_iso()
            failure_stage, failure_code = (
                _classify_resolution_failure(exc)
            )
            retry_count = (
                _retry_count_from_client_or_exception(
                    saxo_client,
                    exc,
                )
            )

            create_saxo_resolution_failure(
                research_snapshot_id=snapshot_id,
                option_quote_id=(
                    selection.quote.option_quote_id
                ),
                underlying=symbol,
                right=selection.quote.right,
                strike=selection.quote.strike,
                expiration=(
                    selection.quote.expiration
                ),
                provider_contract_id=(
                    selection.quote.provider_contract_id
                ),
                option_symbol=(
                    selection.quote.option_symbol
                ),
                shares_per_contract=(
                    massive_quote.get(
                        "shares_per_contract"
                    )
                ),
                failure_stage=failure_stage,
                failure_code=failure_code,
                failure_reason=str(exc),
                attempted_at=attempted_at,
                retry_count=retry_count,
                resolution_sequence=(
                    selection.resolution_sequence
                ),
                conn=conn,
            )

            _record_provider_attempt(
                conn,
                run_id=run_id,
                provider="SAXO",
                operation="OPTION_RESOLUTION",
                underlying=symbol,
                attempted_at=attempted_at,
                completed_at=completed_at,
                succeeded=False,
                retry_count=retry_count,
                failure_code=failure_code,
                failure_reason=str(exc),
            )

            failure_count += 1

            if failure_stage == "AUTHENTICATION":
                run_invalid = True
                invalid_reason = (
                    "Saxo authentication failed "
                    "during randomized resolution."
                )
                break

            continue

        completed_at = utc_now_iso()
        retry_count = (
            _retry_count_from_client_or_exception(
                saxo_client
            )
        )

        # Persistence is intentionally outside the
        # provider-resolution exception handler.
        # A database failure must never become fake
        # evidence that Saxo failed to resolve.
        create_saxo_option_observation(
            option_quote_id=(
                selection.quote.option_quote_id
            ),
            contract=bridged.saxo_contract,
            quote=bridged.saxo_quote,
            source_snapshot_captured_at=(
                source_captured_at
            ),
            source_quote_at=(
                massive_quote.get("quote_at")
            ),
            massive_observed_at=(
                massive_quote.get("quote_at")
            ),
            retry_count=retry_count,
            resolution_sequence=(
                selection.resolution_sequence
            ),
            conn=conn,
        )

        _record_provider_attempt(
            conn,
            run_id=run_id,
            provider="SAXO",
            operation="OPTION_RESOLUTION",
            underlying=symbol,
            attempted_at=attempted_at,
            completed_at=completed_at,
            succeeded=True,
            retry_count=retry_count,
        )

        success_count += 1

    if not sequenced:
        run_invalid = True
        invalid_reason = (
            "Cohort produced zero selected contracts."
        )

    if sequenced and success_count == 0:
        run_invalid = True
        invalid_reason = (
            invalid_reason
            or "Zero Saxo resolutions succeeded."
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
        succeeded=(not run_invalid),
        failure_code=(
            "RUN_INVALID"
            if run_invalid
            else None
        ),
        failure_reason=invalid_reason,
    )

    final_status = (
        "INVALID"
        if run_invalid
        else "COMPLETED"
    )

    set_run_status(
        conn,
        run_id=run_id,
        status=final_status,
        ended_at=ended_at,
        notes=invalid_reason,
    )

    return CohortRunResult(
        run_id=run_id,
        snapshot_id=snapshot_id,
        selected_contract_count=len(sequenced),
        saxo_resolution_success_count=success_count,
        saxo_resolution_failure_count=failure_count,
        status=final_status,
    )
