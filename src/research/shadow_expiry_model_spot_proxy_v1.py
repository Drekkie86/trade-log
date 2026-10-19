"""Read-only retrospective expiry *model-spot proxy* for admitted shadows.

Never updates immutable market snapshots, inserts trading outcomes, or treats
Theta's model input as an independent stock execution quote. This is an
explicitly lower-confidence diagnostic, distinct from validated package P&L.
"""
from __future__ import annotations

import math
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from statistics import median
from typing import Any

from src.database.repository import get_connection
from src.research.historical_replay_recovery_v1 import HistoricalReplayError, theoretical_expiry_value_usd_minor
from src.research.shadow_outcome_collector_v2 import ShadowOutcomeCollectorError, _entry_cashflow_usd_minor

PROXY_ROLE = "THETADATA_PROVIDER_MODEL_SPOT_PROXY_NON_SETTLEMENT"
MIN_DISTINCT_CONTRACTS = 8
MAX_SPOT_DISAGREEMENT_FRACTION = 0.0005
MAX_INGEST_CAPTURE_SKEW_SECONDS = 120


def _utc(value: object) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def select_model_spot_proxy(
    rows: list[dict[str, Any]], *, captured_at: str
) -> dict[str, Any] | None:
    """Concordant same-provider model inputs. Not independent price samples."""
    capture = _utc(captured_at)
    if capture is None:
        return None
    selected: dict[int, tuple[int, float]] = {}
    for row in rows:
        ingested = _utc(row.get("ingested_at"))
        price = row.get("model_underlying_price")
        if (
            row.get("provider") != "THETADATA"
            or row.get("source") != "PROVIDER_DERIVED"
            or ingested is None
            or price is None
        ):
            continue
        try:
            p = float(price)
            qid = int(row["option_quote_id"])
            oid = int(row["model_observation_id"])
        except (ValueError, TypeError, OverflowError):
            continue
        skew = (capture - ingested).total_seconds()
        if not math.isfinite(p) or p <= 0 or not (
            0 <= skew <= MAX_INGEST_CAPTURE_SKEW_SECONDS
        ):
            continue
        selected.setdefault(qid, (oid, p))
    if len(selected) < MIN_DISTINCT_CONTRACTS:
        return None
    values = [x[1] for x in selected.values()]
    reference = median(values)
    if max(abs(v-reference) for v in values) > MAX_SPOT_DISAGREEMENT_FRACTION * reference:
        return None
    return {
        "proxy_price": float(reference),
        "distinct_option_contracts": len(selected),
        "model_observation_ids": [x[0] for x in selected.values()],
        "max_model_spot_disagreement": max(abs(v-reference) for v in values),
        "measurement_role": PROXY_ROLE,
        "provider": "THETADATA",
        "disclaimer": (
            "Same-provider option-Greek model underlying inputs, not independent "
            "underlying ticks, official settlement, option exit fills, or "
            "validated trading P&L."
        ),
    }


def _latest_qualifying_proxy(
    conn: sqlite3.Connection, symbol: str, expiration: str
) -> dict[str, Any] | None:
    snaps = conn.execute(
        """SELECT id,captured_at FROM market_snapshots
           WHERE underlying=? AND us_session_date=? AND us_session_state='INTRADAY'
             AND provider='THETADATA'
           ORDER BY captured_at DESC,id DESC LIMIT 5""",
        (symbol, expiration),
    ).fetchall()
    if not snaps:
        return None
    newest = _utc(snaps[0]["captured_at"])
    if newest is None:
        return None
    for snap in snaps:
        captured = _utc(snap["captured_at"])
        if captured is None or (newest-captured).total_seconds() > 3600:
            continue
        rows = conn.execute(
            """SELECT pmo.id AS model_observation_id, oq.id AS option_quote_id,
                      pmo.model_underlying_price,pmo.ingested_at,pmo.provider,pmo.source
               FROM option_quotes oq
               JOIN provider_model_observations pmo ON pmo.option_quote_id=oq.id
               WHERE oq.snapshot_id=?
               ORDER BY oq.id DESC,pmo.id DESC LIMIT 120""",
            (int(snap["id"]),),
        ).fetchall()
        estimate = select_model_spot_proxy(
            [dict(r) for r in rows], captured_at=str(snap["captured_at"])
        )
        if estimate is not None:
            return {
                **estimate,
                "source_snapshot_id": int(snap["id"]),
                "captured_at": str(snap["captured_at"]),
                "expiration": expiration,
                "underlying": symbol,
            }
    return None


def modeled_expiry_payoff_mechanism(
    *, entry_cashflow_usd_minor: int, terminal_intrinsic_usd_minor: int,
    assumed_fees_usd_minor: int,
) -> str:
    """Classify a *proxy*, not a validated loss cause or independently filled trade.

    The frozen cashflow already crosses every option leg at ask/bid. Thus a
    gross negative includes adverse entry spread *and* terminal payoff; this
    function cannot distinguish those two mechanisms without midquote evidence.
    """
    if assumed_fees_usd_minor < 0:
        raise ValueError("Assumed fees cannot be negative")
    gross = entry_cashflow_usd_minor + terminal_intrinsic_usd_minor
    net = gross - assumed_fees_usd_minor
    if gross < 0:
        return "GROSS_LOSS_AFTER_ENTRY_SPREAD_BEFORE_FEES"
    if gross == 0 and net < 0:
        return "ZERO_GROSS_PAYOFF_ERODED_BY_FEES"
    if net < 0:
        return "POSITIVE_GROSS_PAYOFF_OVERTURNED_BY_FEES"
    if net == 0:
        return "MODELED_BREAK_EVEN_AFTER_FEES"
    return "MODELED_NET_POSITIVE_AFTER_FEES"


def _economic_bet_key(underlying: str, expiration: str, structure: dict[str, Any]) -> tuple:
    """Deduplicate identical option payoffs across frozen snapshot observations.

    This does not declare the remaining keys statistically independent.
    """
    legs = tuple(sorted(
        (str(leg["right"]), float(leg["strike"]), str(leg["side"]),
         int(leg["quantity"]), float(leg["shares_per_contract"]))
        for leg in structure["legs"]
    ))
    return underlying, expiration, str(structure.get("structure_id")), legs


def load_expiry_model_proxy_report(*, db_path=None, as_of_day: str | None = None):
    """Bounded independent retrospective diagnostic; never writes to SQLite."""
    import json
    today = (as_of_day or datetime.now(UTC).date().isoformat())
    conn = get_connection(db_path)
    try:
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            """SELECT sc.id AS candidate_id,sc.underlying,sc.structure_json,
                      lrc.expiration,sad.proposal_id,sad.estimated_cost_usd_minor,
                      ssp.entry_pricing_json,fx.rate AS entry_eur_to_usd
               FROM shadow_candidates sc
               JOIN listing_reference_contracts lrc ON lrc.id=sc.reference_contract_id
               JOIN v_shadow_admission_decisions_all sad
                 ON sad.candidate_id=sc.id AND sad.decision='ADMITTED'
               JOIN shadow_structure_proposals ssp ON ssp.id=sad.proposal_id
               JOIN fx_observations fx ON fx.id=sad.fx_observation_id
               WHERE lrc.expiration < ?
               ORDER BY sc.id""",
            (today,),
        ).fetchall()
        if len(rows) > 5000:
            raise RuntimeError("PROXY_CANDIDATE_POPULATION_EXCEEDS_BOUNDED_READ")
        pool: dict[tuple[str,str],dict[str,Any]|None] = {}
        results = []
        for row in rows:
            key = (str(row["underlying"]),str(row["expiration"]))
            if key not in pool:
                pool[key] = _latest_qualifying_proxy(conn,*key)
            spot = pool[key]
            item = {
                "candidate_id": int(row["candidate_id"]),
                "underlying":key[0],"expiration":key[1],
                "proposal_id":int(row["proposal_id"]),
                "measurement_role":PROXY_ROLE,
                "verified_trading_outcome":False,
                "outcome_state":"UNRESOLVED",
                "reason_code":"NO_CONSISTENT_ASOF_PROVIDER_MODEL_SPOT",
            }
            if spot is None:
                results.append(item)
                continue
            try:
                structure=json.loads(str(row["structure_json"]))
                pricing=json.loads(str(row["entry_pricing_json"]))
                entry=_entry_cashflow_usd_minor(
                    structure=structure,entry_pricing=pricing
                )
                terminal=theoretical_expiry_value_usd_minor(
                    structure=structure,underlying_price=spot["proxy_price"]
                )
                costs=int(row["estimated_cost_usd_minor"])
                fx=float(row["entry_eur_to_usd"])
                if not math.isfinite(fx) or fx<=0 or costs<0:
                    raise ValueError("INVALID_COST_OR_FX_EVIDENCE")
                gross_after_spread=int(entry)+int(terminal)
                net=gross_after_spread-costs
                mechanism=modeled_expiry_payoff_mechanism(
                    entry_cashflow_usd_minor=int(entry),
                    terminal_intrinsic_usd_minor=int(terminal),
                    assumed_fees_usd_minor=costs,
                )
                bet_key=_economic_bet_key(key[0], key[1], structure)
                item.update({
                    "structure_id":str(structure.get("structure_id") or "UNKNOWN"),
                    "economic_bet_key":bet_key,
                    "modeled_payoff_mechanism":mechanism,
                    "gross_after_entry_spread_before_fees_usd_minor":gross_after_spread,
                    "outcome_state":"MODELED_PROXY_NOT_VALIDATED",
                    "reason_code":"PROVIDER_MODEL_INPUT_PROXY_NOT_SETTLEMENT",
                    "proxy_price":spot["proxy_price"],
                    "snapshot_id":spot["source_snapshot_id"],
                    "snapshot_captured_at":spot["captured_at"],
                    "distinct_model_option_contracts":spot["distinct_option_contracts"],
                    "model_observation_ids":spot["model_observation_ids"],
                    "max_model_spot_disagreement":spot["max_model_spot_disagreement"],
                    "entry_cashflow_usd_minor":int(entry),
                    "terminal_intrinsic_usd_minor":int(terminal),
                    "assumed_round_trip_cost_usd_minor":costs,
                    "modeled_net_pnl_usd_minor":net,
                    "modeled_net_pnl_eur_minor":int(round(net/fx)),
                })
            except (ValueError,TypeError,KeyError,ArithmeticError,
                    ShadowOutcomeCollectorError,HistoricalReplayError) as exc:
                item["reason_code"]="CANNOT_RECONSTRUCT_FROZEN_ENTRY_OR_FX"
                item["evidence_error_type"]=type(exc).__name__
            results.append(item)
        resolved=[r for r in results if r["outcome_state"]=="MODELED_PROXY_NOT_VALIDATED"]
        mechanisms=Counter(r["modeled_payoff_mechanism"] for r in resolved)
        family_counts=Counter(r["structure_id"] for r in resolved)
        distinct_bets={r["economic_bet_key"] for r in resolved}
        return {
            "measurement_role":PROXY_ROLE,
            "total_expired_admitted":len(results),
            "modeled_proxy_count":len(resolved),
            "unresolved_count":len(results)-len(resolved),
            "wins":sum(r["modeled_net_pnl_usd_minor"]>0 for r in resolved),
            "losses":sum(r["modeled_net_pnl_usd_minor"]<0 for r in resolved),
            "independent_expiry_dates":len({r["expiration"] for r in resolved}),
            "distinct_economic_bet_shapes":len(distinct_bets),
            "modeled_payoff_mechanism_counts":dict(sorted(mechanisms.items())),
            "modeled_structure_family_counts":dict(sorted(family_counts.items())),
            "mechanism_scope_note":(
                "Gross includes original bid/ask crossing but excludes the separately "
                "assumed fees. Cannot allocate gross losses between spread, adverse "
                "underlying move or mistaken alpha without further quote evidence. "
                "Repeated shapes and expiry dates are not independent trials."
            ),
            "total_modeled_net_eur_minor":sum(
                r["modeled_net_pnl_eur_minor"] for r in resolved
            ),
            "rows":results,
            "disclaimer":(
                "Retrospective model-spot proxy diagnostics, not independently "
                "verified underlying quotes or cash-settlement prices; not "
                "actual options fills, held-to-expiry exercise accounting, "
                "or validated trading returns."
            ),
        }
    finally:
        conn.close()
