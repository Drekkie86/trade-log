"""Bounded read-only research-run adapter for thesis-first candidate discovery.

This is intentionally NOT used by the daemon or Streamlit rendering loop.
No schema migration, broker actions, candidate admissions, or historical
reclassification. Missing independent stock evidence remains a visible blocker.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.operations.sqlite_runtime import open_readonly_connection
from src.research.independent_family_discovery_v1 import (
    FrozenChain, FrozenQuote, IndependentDiscovery,
    _stock_reference_valid, discover_independent_families,
)
from src.research.massive_underlying_observation_v1 import STOCK_PRICE_SOURCE
from src.research.strategy_competition_v1 import _fx_asof, _quote_time_asof
from src.research.strategy_falsification_v1 import QuoteCostPolicy, dec

VERSION = "INDEPENDENT_FAMILY_READ_MODEL_V1"
MAX_SNAPSHOTS = 48
MAX_QUOTES_PER_SNAPSHOT = 2500


@dataclass(frozen=True)
class IndependentRunReport:
    research_run_id: int | None
    snapshots_seen: int
    snapshots_with_independent_spot: int
    families_constructed: int
    shadow_experiments_authorized: int
    live_trades_authorized: int
    outcomes: tuple[IndependentDiscovery, ...]
    authority: str = "NONE"


def _read_chain(
    conn, row, *, research_run_id: int,
    bounded_live_selection: bool = False,
) -> FrozenChain:
    # A 'FETCHED' enum alone is not a source receipt. Require the persisted
    # independent underlying provenance note from the actual research runner.
    notes = str(row["notes"] or "")
    stock_source = (
        STOCK_PRICE_SOURCE
        if row["underlying_source"] == "FETCHED"
        and f"stock price source={STOCK_PRICE_SOURCE};" in notes
        else None
    )
    if stock_source is None:
        return FrozenChain(
            int(row["id"]), str(row["underlying"]), str(row["captured_at"]),
            None, None, None, (),
        )
    selection_blocker = None
    if bounded_live_selection:
        from src.research.bounded_chain_selection_v1 import (
            read_bounded_strategy_source_rows,
        )
        source_rows, selection_blocker = read_bounded_strategy_source_rows(
            conn, snapshot_id=int(row["id"]),
            research_run_id=research_run_id,
            underlying=str(row["underlying"]),
            captured_at=str(row["captured_at"]),
            spot=dec(row["underlying_price"]),
        )
    else:
        source_rows = conn.execute(
            """SELECT oq.id,oq.snapshot_id,oq.right,oq.strike,oq.expiration,
                      oq.quote_at,oq.bid,oq.ask,
                      oq.shares_per_contract AS quote_multiplier,
                      lrc.shares_per_contract AS reference_multiplier
               FROM option_quotes oq
               LEFT JOIN listing_reference_contracts lrc
                 ON lrc.research_run_id=? AND lrc.provider='MASSIVE'
                AND lrc.underlying=? AND lrc.expiration=oq.expiration
                AND lrc.right=oq.right AND lrc.strike=oq.strike
               WHERE oq.snapshot_id=? ORDER BY oq.id LIMIT ?""",
            (research_run_id, row["underlying"], row["id"],
             MAX_QUOTES_PER_SNAPSHOT + 1),
        ).fetchall()
    if len(source_rows) > MAX_QUOTES_PER_SNAPSHOT:
        return FrozenChain(
            int(row["id"]), str(row["underlying"]), str(row["captured_at"]),
            None if row["underlying_price"] is None else dec(row["underlying_price"]),
            stock_source, row["underlying_at"], (),
            source_blocker="OPTION_CHAIN_EXCEEDS_BOUNDED_DISCOVERY",
        )
    quotes = []
    for q in source_rows:
        try:
            when = _quote_time_asof(q["quote_at"])
        except (ValueError, TypeError):
            when = None
        quotes.append(FrozenQuote(
            source_id=int(q["id"]), snapshot_id=int(q["snapshot_id"]),
            expiration=str(q["expiration"]), right=str(q["right"]),
            strike=dec(q["strike"]),
            bid=None if q["bid"] is None else dec(q["bid"]),
            ask=None if q["ask"] is None else dec(q["ask"]),
            quote_at=when,
            reference_multiplier=(
                None if q["reference_multiplier"] is None
                else dec(q["reference_multiplier"])
            ),
            quoted_multiplier=(
                None if q["quote_multiplier"] is None
                else dec(q["quote_multiplier"])
            ),
            # No quote-side depth in this table. Never synthesize it.
            bid_size=None, ask_size=None,
        ))
    return FrozenChain(
        snapshot_id=int(row["id"]), underlying=str(row["underlying"]),
        captured_at=str(row["captured_at"]),
        spot=None if row["underlying_price"] is None
             else dec(row["underlying_price"]),
        spot_source=stock_source, spot_at=row["underlying_at"],
        quotes=tuple(quotes),
        source_blocker=selection_blocker,
    )


def inspect_latest_run(
    *, db_path=None, max_snapshots: int = MAX_SNAPSHOTS,
    allocated_eur: str = "500",
) -> IndependentRunReport:
    """No new candidates/admissions, only auditable source-backed diagnostics."""
    if not 1 <= max_snapshots <= MAX_SNAPSHOTS:
        raise ValueError("SNAPSHOT_BOUND_OUT_OF_RANGE")
    allocation = dec(allocated_eur)
    if not Decimal(0) < allocation <= Decimal(500):
        raise ValueError("RESEARCH_CAP_OUTSIDE_500_EUR")
    conn = open_readonly_connection(db_path)
    try:
        run = conn.execute(
            """SELECT id FROM research_runs WHERE status='COMPLETED'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        if run is None:
            return IndependentRunReport(None, 0, 0, 0, 0, 0, ())
        run_id = int(run["id"])
        rows = conn.execute(
            """SELECT id,underlying,captured_at,underlying_price,
                      underlying_source,underlying_at,notes
               FROM market_snapshots
               WHERE research_run_id=? AND provider='THETADATA'
               ORDER BY id LIMIT ?""",
            (run_id, max_snapshots + 1),
        ).fetchall()
        if len(rows) > max_snapshots:
            raise ValueError("LATEST_RUN_SNAPSHOT_COUNT_EXCEEDS_BOUND")
        reports = []
        spot_count = 0
        for row in rows:
            chain = _read_chain(conn, row, research_run_id=run_id)
            if _stock_reference_valid(chain):
                spot_count += 1
            fx, fx_at, fx_source = _fx_asof(conn, str(row["captured_at"]))
            policy = QuoteCostPolicy(
                option_cost_per_contract_side_usd=Decimal("3"),
                stock_round_trip_cost_usd=None,
                eur_to_usd=None if fx is None else dec(fx),
                cost_provenance="SAXO_SHADOW_ASSUMED_NOT_BROKER",
                fx_provenance=fx_source,
                max_quote_age_seconds=15,
                max_leg_quote_skew_seconds=15,
                bankroll_eur=allocation,
                additional_round_trip_cost_usd=None, tax_cost_usd=None,
                fx_observed_at=fx_at,
            )
            reports.append(discover_independent_families(chain, policy))
        return IndependentRunReport(
            run_id, len(rows), spot_count,
            sum(len(x.decisions) for x in reports),
            sum(d.state == "SHADOW_RESEARCH_ONLY_NOT_TRADING_AUTHORITY"
                for x in reports for d in x.decisions),
            0, tuple(reports),
        )
    finally:
        conn.close()
