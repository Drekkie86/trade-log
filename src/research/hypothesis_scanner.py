from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.database.repository import (
    get_connection,
)
from src.research.deterministic_scanner import (
    ScannerObservation,
    ScannerRunSummary,
    scan_research_run,
)

UTC = ZoneInfo("UTC")

SCANNER_FAMILY_ID = "LOCAL_IV_RESIDUAL_V1"
SCANNER_VERSION = "1.0.1"
RULE_VERSION = "LOCAL_IV_RESIDUAL_RULES_V1"
HYPOTHESIS_FAMILY = "LOCAL_SURFACE_IV_RESIDUAL"
HYPOTHESIS_VERSION = "1.0.0"

DEFAULT_MIN_ABS_DELTA = 0.10
DEFAULT_MAX_ABS_DELTA = 0.80
DEFAULT_RESIDUAL_THRESHOLD = 0.03


class HypothesisScannerError(RuntimeError):
    pass


@dataclass(frozen=True)
class HypothesisEvaluation:
    reference_contract_id: int
    option_quote_id: int
    underlying: str
    expiration: str
    strike: float
    right: str
    delta: float | None
    implied_volatility: float | None
    lower_strike: float | None
    lower_iv: float | None
    upper_strike: float | None
    upper_iv: float | None
    interpolated_iv: float | None
    iv_residual: float | None
    abs_iv_residual: float | None
    residual_threshold: float
    evaluation_state: str
    reason_code: str
    surfaced_direction: str | None


@dataclass(frozen=True)
class HypothesisScannerResult:
    research_run_id: int
    scanner_family_id: str
    scanner_version: str
    rule_version: str
    hypothesis_family: str
    hypothesis_version: str
    config_hash: str
    structural_input_count: int
    evaluable_count: int
    surfaced_count: int
    evaluations: tuple[HypothesisEvaluation, ...]
    persisted_scanner_run_id: int | None


def _config(
    *,
    max_spread_to_mid: float,
    min_abs_delta: float,
    max_abs_delta: float,
    residual_threshold: float,
) -> dict[str, Any]:
    if not (
        0 <= min_abs_delta
        < max_abs_delta
        <= 1
    ):
        raise ValueError(
            "Delta band must satisfy "
            "0 <= min < max <= 1."
        )

    if residual_threshold <= 0:
        raise ValueError(
            "residual_threshold must be positive."
        )

    return {
        "scanner_family_id":
            SCANNER_FAMILY_ID,
        "scanner_version":
            SCANNER_VERSION,
        "rule_version":
            RULE_VERSION,
        "hypothesis_family":
            HYPOTHESIS_FAMILY,
        "hypothesis_version":
            HYPOTHESIS_VERSION,
        "max_spread_to_mid":
            float(max_spread_to_mid),
        "min_abs_delta":
            float(min_abs_delta),
        "max_abs_delta":
            float(max_abs_delta),
        "residual_threshold":
            float(residual_threshold),
        "candidate_creation":
            False,
        "edge_claim":
            False,
    }


def _config_hash(
    config: dict[str, Any],
) -> str:
    encoded = json.dumps(
        config,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _load_reference_and_iv(
    *,
    research_run_id: int,
    option_quote_ids: list[int],
    db_path=None,
) -> dict[int, dict[str, Any]]:
    if not option_quote_ids:
        return {}

    # A literal "oq.id IN (?, ?, ?, ...)" with thousands of placeholders is
    # a known-bad pattern in SQLite: cost scales with the size of the list
    # itself, independent of any index on the joined tables. Measured on a
    # dataset sized like production (189k reference rows): a 2,000-item
    # literal IN-list took 80s; the same result set joined through a temp
    # table took 10s, and 8x faster again once
    # idx_listing_reference_scanner_join (migration 015) is present.
    # Loading the target ids into a temp table and joining against it
    # avoids building the giant literal predicate at all.
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            CREATE TEMP TABLE _scanner_target_quote_ids (
                id INTEGER PRIMARY KEY
            );
            """
        )

        conn.executemany(
            """
            INSERT INTO _scanner_target_quote_ids (id)
            VALUES (?);
            """,
            (
                (quote_id,)
                for quote_id in option_quote_ids
            ),
        )

        rows = conn.execute(
            """
            SELECT
                oq.id AS option_quote_id,
                oq.expiration,
                oq.strike,
                oq.right,
                ms.underlying,
                pmo.implied_volatility,
                lrc.id AS reference_contract_id
            FROM _scanner_target_quote_ids AS target
            JOIN option_quotes AS oq
              ON oq.id = target.id
            JOIN market_snapshots AS ms
              ON ms.id = oq.snapshot_id
            JOIN listing_reference_contracts AS lrc
              ON lrc.research_run_id = ms.research_run_id
             AND lrc.provider = 'MASSIVE'
             AND lrc.underlying = ms.underlying
             AND lrc.expiration = oq.expiration
             AND lrc.strike = oq.strike
             AND lrc.right = oq.right
            LEFT JOIN provider_model_observations AS pmo
              ON pmo.option_quote_id = oq.id
             AND pmo.provider = 'THETADATA'
            WHERE ms.research_run_id = ?;
            """,
            (research_run_id,),
        ).fetchall()
    finally:
        try:
            conn.execute(
                "DROP TABLE IF EXISTS _scanner_target_quote_ids;"
            )
        finally:
            conn.close()

    result: dict[
        int,
        dict[str, Any],
    ] = {}

    for row in rows:
        quote_id = int(
            row["option_quote_id"]
        )

        if quote_id in result:
            raise HypothesisScannerError(
                "Ambiguous canonical reference/model join "
                f"for option_quote_id={quote_id}."
            )

        result[quote_id] = {
            "reference_contract_id":
                int(
                    row[
                        "reference_contract_id"
                    ]
                ),
            "implied_volatility":
                (
                    None
                    if row[
                        "implied_volatility"
                    ]
                    is None
                    else float(
                        row[
                            "implied_volatility"
                        ]
                    )
                ),
        }

    # Quotes absent from the Massive reference frame are already
    # preserved upstream as provider-disagreement evidence. This
    # reference-dependent hypothesis simply cannot evaluate them.
    # Genuine duplicate/ambiguous joins above remain hard failures.
    return result


def _interpolate(
    *,
    x: float,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> float:
    if x1 <= x0:
        raise HypothesisScannerError(
            "Neighbor strikes must be strictly increasing."
        )

    weight = (
        (x - x0)
        / (x1 - x0)
    )

    return y0 + (
        weight
        * (y1 - y0)
    )


def _evaluate_group(
    observations: list[
        tuple[
            ScannerObservation,
            int,
            float | None,
        ]
    ],
    *,
    min_abs_delta: float,
    max_abs_delta: float,
    residual_threshold: float,
) -> list[HypothesisEvaluation]:
    observations = sorted(
        observations,
        key=lambda item:
            item[0].strike,
    )

    evaluations: list[
        HypothesisEvaluation
    ] = []

    usable_indices: list[int] = []

    for index, (
        observation,
        _reference_id,
        iv,
    ) in enumerate(observations):
        delta = observation.delta

        if (
            delta is not None
            and iv is not None
            and min_abs_delta
            <= abs(delta)
            <= max_abs_delta
        ):
            usable_indices.append(
                index
            )

    usable_position = {
        index: position
        for position, index in enumerate(
            usable_indices
        )
    }

    for index, (
        observation,
        reference_id,
        iv,
    ) in enumerate(observations):
        delta = observation.delta

        common = {
            "reference_contract_id":
                reference_id,
            "option_quote_id":
                observation.option_quote_id,
            "underlying":
                observation.underlying,
            "expiration":
                observation.expiration,
            "strike":
                observation.strike,
            "right":
                observation.right,
            "delta":
                delta,
            "implied_volatility":
                iv,
            "residual_threshold":
                residual_threshold,
        }

        if delta is None:
            evaluations.append(
                HypothesisEvaluation(
                    **common,
                    lower_strike=None,
                    lower_iv=None,
                    upper_strike=None,
                    upper_iv=None,
                    interpolated_iv=None,
                    iv_residual=None,
                    abs_iv_residual=None,
                    evaluation_state=
                        "NOT_EVALUABLE",
                    reason_code=
                        "DELTA_MISSING",
                    surfaced_direction=None,
                )
            )
            continue

        if not (
            min_abs_delta
            <= abs(delta)
            <= max_abs_delta
        ):
            evaluations.append(
                HypothesisEvaluation(
                    **common,
                    lower_strike=None,
                    lower_iv=None,
                    upper_strike=None,
                    upper_iv=None,
                    interpolated_iv=None,
                    iv_residual=None,
                    abs_iv_residual=None,
                    evaluation_state=
                        "NOT_EVALUABLE",
                    reason_code=
                        "DELTA_OUT_OF_BAND",
                    surfaced_direction=None,
                )
            )
            continue

        if iv is None:
            evaluations.append(
                HypothesisEvaluation(
                    **common,
                    lower_strike=None,
                    lower_iv=None,
                    upper_strike=None,
                    upper_iv=None,
                    interpolated_iv=None,
                    iv_residual=None,
                    abs_iv_residual=None,
                    evaluation_state=
                        "NOT_EVALUABLE",
                    reason_code=
                        "IV_MISSING",
                    surfaced_direction=None,
                )
            )
            continue

        position = usable_position[
            index
        ]

        if (
            position == 0
            or position
            == len(usable_indices) - 1
        ):
            evaluations.append(
                HypothesisEvaluation(
                    **common,
                    lower_strike=None,
                    lower_iv=None,
                    upper_strike=None,
                    upper_iv=None,
                    interpolated_iv=None,
                    iv_residual=None,
                    abs_iv_residual=None,
                    evaluation_state=
                        "NOT_EVALUABLE",
                    reason_code=
                        "NO_BRACKETING_NEIGHBORS",
                    surfaced_direction=None,
                )
            )
            continue

        lower = observations[
            usable_indices[
                position - 1
            ]
        ]
        upper = observations[
            usable_indices[
                position + 1
            ]
        ]

        lower_observation = lower[0]
        lower_iv = lower[2]
        upper_observation = upper[0]
        upper_iv = upper[2]

        if (
            lower_iv is None
            or upper_iv is None
        ):
            raise HypothesisScannerError(
                "Usable-neighbor invariant violated."
            )

        interpolated = _interpolate(
            x=observation.strike,
            x0=lower_observation.strike,
            y0=lower_iv,
            x1=upper_observation.strike,
            y1=upper_iv,
        )

        residual = (
            iv - interpolated
        )

        abs_residual = abs(
            residual
        )

        surfaced = (
            abs_residual
            >= residual_threshold
        )

        direction = (
            "IV_RICH_LOCAL"
            if surfaced and residual > 0
            else "IV_CHEAP_LOCAL"
            if surfaced and residual < 0
            else None
        )

        evaluations.append(
            HypothesisEvaluation(
                **common,
                lower_strike=
                    lower_observation.strike,
                lower_iv=
                    lower_iv,
                upper_strike=
                    upper_observation.strike,
                upper_iv=
                    upper_iv,
                interpolated_iv=
                    interpolated,
                iv_residual=
                    residual,
                abs_iv_residual=
                    abs_residual,
                evaluation_state=
                    (
                        "SURFACED"
                        if surfaced
                        else
                        "EVALUATED_NOT_SURFACED"
                    ),
                reason_code=
                    (
                        "LOCAL_IV_RESIDUAL_ABOVE_THRESHOLD"
                        if surfaced
                        else
                        "LOCAL_IV_RESIDUAL_BELOW_THRESHOLD"
                    ),
                surfaced_direction=
                    direction,
            )
        )

    return evaluations


def _persist(
    *,
    research_run_id: int,
    config: dict[str, Any],
    evaluations: list[
        HypothesisEvaluation
    ],
    structural_input_count: int | None = None,
    db_path=None,
) -> int:
    evaluated_at = datetime.now(
        UTC
    ).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")

    evaluable_count = sum(
        item.evaluation_state
        != "NOT_EVALUABLE"
        for item in evaluations
    )

    surfaced_count = sum(
        item.evaluation_state
        == "SURFACED"
        for item in evaluations
    )

    config_json = json.dumps(
        config,
        sort_keys=True,
        separators=(",", ":"),
    )

    config_hash = _config_hash(
        config
    )

    conn = get_connection(db_path)

    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO hypothesis_scanner_runs (
                    research_run_id,
                    scanner_family_id,
                    scanner_version,
                    rule_version,
                    hypothesis_family,
                    hypothesis_version,
                    config_hash,
                    config_json,
                    evaluated_at,
                    structural_input_count,
                    evaluable_count,
                    surfaced_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    research_run_id,
                    SCANNER_FAMILY_ID,
                    SCANNER_VERSION,
                    RULE_VERSION,
                    HYPOTHESIS_FAMILY,
                    HYPOTHESIS_VERSION,
                    config_hash,
                    config_json,
                    evaluated_at,
                    (
                        len(evaluations)
                        if structural_input_count is None
                        else structural_input_count
                    ),
                    evaluable_count,
                    surfaced_count,
                ),
            )

            scanner_run_id = int(
                cursor.lastrowid
            )

            conn.executemany(
                """
                INSERT INTO hypothesis_scanner_evaluations (
                    scanner_run_id,
                    reference_contract_id,
                    option_quote_id,
                    underlying,
                    expiration,
                    strike,
                    right,
                    delta,
                    implied_volatility,
                    lower_strike,
                    lower_iv,
                    upper_strike,
                    upper_iv,
                    interpolated_iv,
                    iv_residual,
                    abs_iv_residual,
                    residual_threshold,
                    evaluation_state,
                    reason_code,
                    surfaced_direction,
                    evidence_json
                )
                VALUES (
                    :scanner_run_id,
                    :reference_contract_id,
                    :option_quote_id,
                    :underlying,
                    :expiration,
                    :strike,
                    :right,
                    :delta,
                    :implied_volatility,
                    :lower_strike,
                    :lower_iv,
                    :upper_strike,
                    :upper_iv,
                    :interpolated_iv,
                    :iv_residual,
                    :abs_iv_residual,
                    :residual_threshold,
                    :evaluation_state,
                    :reason_code,
                    :surfaced_direction,
                    :evidence_json
                );
                """,
                [
                    {
                        "scanner_run_id":
                            scanner_run_id,
                        **asdict(item),
                        "evidence_json":
                            json.dumps(
                                {
                                    "scanner_family_id":
                                        SCANNER_FAMILY_ID,
                                    "scanner_version":
                                        SCANNER_VERSION,
                                    "rule_version":
                                        RULE_VERSION,
                                    "hypothesis_family":
                                        HYPOTHESIS_FAMILY,
                                    "hypothesis_version":
                                        HYPOTHESIS_VERSION,
                                },
                                sort_keys=True,
                            ),
                    }
                    for item in evaluations
                ],
            )

        return scanner_run_id
    finally:
        conn.close()


def scan_local_iv_residuals(
    *,
    research_run_id: int,
    max_spread_to_mid: float = 0.20,
    min_abs_delta: float =
        DEFAULT_MIN_ABS_DELTA,
    max_abs_delta: float =
        DEFAULT_MAX_ABS_DELTA,
    residual_threshold: float =
        DEFAULT_RESIDUAL_THRESHOLD,
    persist: bool = True,
    structural_summary: ScannerRunSummary | None = None,
    db_path=None,
) -> HypothesisScannerResult:
    structural = (
        structural_summary
        if structural_summary is not None
        else scan_research_run(
            research_run_id=
                research_run_id,
            max_spread_to_mid=
                max_spread_to_mid,
            db_path=db_path,
        )
    )

    eligible = [
        item
        for item in structural.observations
        if item.structurally_eligible
    ]

    config = _config(
        max_spread_to_mid=
            max_spread_to_mid,
        min_abs_delta=
            min_abs_delta,
        max_abs_delta=
            max_abs_delta,
        residual_threshold=
            residual_threshold,
    )

    if not eligible:
        scanner_run_id = (
            _persist(
                research_run_id=
                    research_run_id,
                config=config,
                evaluations=[],
                db_path=db_path,
            )
            if persist
            else None
        )

        return HypothesisScannerResult(
            research_run_id=
                research_run_id,
            scanner_family_id=
                SCANNER_FAMILY_ID,
            scanner_version=
                SCANNER_VERSION,
            rule_version=
                RULE_VERSION,
            hypothesis_family=
                HYPOTHESIS_FAMILY,
            hypothesis_version=
                HYPOTHESIS_VERSION,
            config_hash=
                _config_hash(config),
            structural_input_count=0,
            evaluable_count=0,
            surfaced_count=0,
            evaluations=(),
            persisted_scanner_run_id=
                scanner_run_id,
        )

    metadata = _load_reference_and_iv(
        research_run_id=
            research_run_id,
        option_quote_ids=[
            item.option_quote_id
            for item in eligible
        ],
        db_path=db_path,
    )

    groups: dict[
        tuple[str, str, str],
        list[
            tuple[
                ScannerObservation,
                int,
                float | None,
            ]
        ],
    ] = {}

    for item in eligible:
        detail = metadata.get(
            item.option_quote_id
        )

        if detail is None:
            continue

        key = (
            item.underlying,
            item.expiration,
            item.right,
        )

        groups.setdefault(
            key,
            [],
        ).append(
            (
                item,
                detail[
                    "reference_contract_id"
                ],
                detail[
                    "implied_volatility"
                ],
            )
        )

    evaluations: list[
        HypothesisEvaluation
    ] = []

    for group in groups.values():
        evaluations.extend(
            _evaluate_group(
                group,
                min_abs_delta=
                    min_abs_delta,
                max_abs_delta=
                    max_abs_delta,
                residual_threshold=
                    residual_threshold,
            )
        )

    evaluations.sort(
        key=lambda item: (
            item.underlying,
            item.expiration,
            item.right,
            item.strike,
        )
    )

    scanner_run_id = (
        _persist(
            research_run_id=
                research_run_id,
            config=config,
            evaluations=
                evaluations,
            structural_input_count=
                len(eligible),
            db_path=db_path,
        )
        if persist
        else None
    )

    evaluable_count = sum(
        item.evaluation_state
        != "NOT_EVALUABLE"
        for item in evaluations
    )

    surfaced_count = sum(
        item.evaluation_state
        == "SURFACED"
        for item in evaluations
    )

    return HypothesisScannerResult(
        research_run_id=
            research_run_id,
        scanner_family_id=
            SCANNER_FAMILY_ID,
        scanner_version=
            SCANNER_VERSION,
        rule_version=
            RULE_VERSION,
        hypothesis_family=
            HYPOTHESIS_FAMILY,
        hypothesis_version=
            HYPOTHESIS_VERSION,
        config_hash=
            _config_hash(config),
        structural_input_count=
            len(eligible),
        evaluable_count=
            evaluable_count,
        surfaced_count=
            surfaced_count,
        evaluations=
            tuple(evaluations),
        persisted_scanner_run_id=
            scanner_run_id,
    )
