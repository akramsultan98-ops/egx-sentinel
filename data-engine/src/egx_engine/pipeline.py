"""Audited decision flow: validate, size, persist — in that order, atomically.

This module adds persistence around the Phase 0 engine. It does not change how
decisions are made: :func:`egx_engine.validator.validate_snapshot` and
:func:`egx_engine.risk.build_risk_plan` are called unmodified and their verdict
is final.

What it adds is the guarantee that a decision you can act on is a decision that
was durably recorded. If any part of persistence fails, the returned plan is
``NO_TRADE`` with reason ``PERSISTENCE_UNAVAILABLE`` — an unrecorded BUY is
never handed back to a caller.

Phase 2 adds two gates that sit *in front of* the risk engine because they
depend on state the pure engine deliberately cannot see:

* **Telda universe.** Availability is operator-verified database state, not a
  market fact, so the check belongs here rather than inside ``risk.py``.
* **Derived levels.** When the caller could not derive a stop and target from
  volatility, there is nothing for ``build_risk_plan`` to size against.

Both refusals are persisted as ordinary NO_TRADE plans with the full snapshot
and validation chain behind them. A rejection is exactly as auditable as a BUY.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from .config import (
    DEFAULT_DATA_POLICY,
    DEFAULT_RISK_POLICY,
    DataPolicy,
    RiskPolicy,
)
from .db.errors import PersistenceError
from .db.repository import Repository
from .liquidity import LiquidityGate, UnconfiguredLiquidityGate
from .models import MarketSnapshot, RiskPlan
from .risk import DATA_NOT_VERIFIED_NO_TRADE, build_risk_plan
from .universe import INSTRUMENT_NOT_REGISTERED, check_universe
from .validator import validate_snapshot

PERSISTENCE_UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"
LEVELS_UNAVAILABLE = "LEVELS_UNAVAILABLE"


@dataclass(frozen=True)
class DecisionRecord:
    """A decision and the audit rows that back it.

    ``persisted`` is false only when the plan could not be written, in which
    case ``plan`` is always a NO_TRADE.
    """

    plan: RiskPlan
    persisted: bool
    snapshot_id: int | None = None
    validation_result_id: int | None = None
    risk_plan_id: int | None = None
    error: str | None = None

    @property
    def is_actionable(self) -> bool:
        """True only for a BUY that is durably recorded."""
        return self.persisted and self.plan.action == "BUY"


def evaluate_and_persist(
    conn,
    snapshot: MarketSnapshot,
    *,
    stop_loss: Decimal | None = None,
    target: Decimal | None = None,
    portfolio_id: int,
    entry: Decimal | None = None,
    levels_reason: str | None = None,
    risk_policy: RiskPolicy = DEFAULT_RISK_POLICY,
    data_policy: DataPolicy = DEFAULT_DATA_POLICY,
    max_freshness_seconds: int | None = None,
    liquidity_gate: LiquidityGate | None = None,
    now: datetime | None = None,
) -> DecisionRecord:
    """Run one decision end to end and commit it as a single transaction.

    Order matters: the portfolio must be readable before sizing, and the plan
    must be committed before it is returned.

    ``stop_loss`` and ``target`` may be ``None`` when the caller could not
    derive them (see :mod:`egx_engine.levels`). That is a refusal, not an
    error: the snapshot and its verdict are still recorded, and the decision is
    stored as NO_TRADE carrying ``levels_reason``.
    """
    now = now or datetime.now(timezone.utc)
    gate = liquidity_gate if liquidity_gate is not None else UnconfiguredLiquidityGate()
    repo = Repository(conn)

    try:
        # 1. Sizing inputs come from the database, never from a caller's guess.
        portfolio = repo.get_portfolio_state(portfolio_id)

        # 2. Telda universe. An unregistered instrument has no row to hang an
        #    audit trail from, so it cannot be recorded at all — that is a
        #    persistence failure, not a decision.
        universe = check_universe(repo.get_instrument(snapshot.instrument_id))
        if universe.reason == INSTRUMENT_NOT_REGISTERED:
            raise PersistenceError(
                f"instrument {snapshot.instrument_id!r} is not registered; a "
                "decision about it cannot be recorded"
            )

        # 3. Phase 0 validation, unmodified.
        validation = validate_snapshot(
            snapshot,
            max_freshness_seconds=max_freshness_seconds,
            policy=data_policy,
            now=now,
        )

        # 4. Record the source data and the verdict, including a rejection:
        #    a NO_TRADE must be as auditable as a BUY.
        snapshot_id = repo.save_snapshot(validation.snapshot)
        validation_result_id = repo.save_validation_result(
            snapshot_id=snapshot_id,
            result=validation,
            data_policy=data_policy,
            max_freshness_seconds=(
                data_policy.max_freshness_seconds
                if max_freshness_seconds is None
                else max_freshness_seconds
            ),
            validated_at=now,
        )

        # 5. Gates that precede sizing, then Phase 0 sizing unmodified.
        gate_reason: str | None = None
        if not universe.ok:
            gate_reason = universe.reason
        elif stop_loss is None or target is None:
            gate_reason = levels_reason or LEVELS_UNAVAILABLE

        if gate_reason is not None:
            # Data validity outranks every later gate (the decision hierarchy in
            # config/risk-policy.md), so an unusable snapshot is still reported
            # as a data failure rather than as whatever gate happened to run.
            if not validation.valid:
                gate_reason = DATA_NOT_VERIFIED_NO_TRADE
            plan = _no_trade_plan(snapshot, gate_reason)
        else:
            plan = build_risk_plan(
                validation,
                stop_loss=stop_loss,
                target=target,
                portfolio=portfolio,
                entry=entry,
                policy=risk_policy,
                liquidity_gate=gate,
            )

        risk_plan_id = repo.save_risk_plan(
            plan=plan,
            validation_result_id=validation_result_id,
            instrument_id=snapshot.instrument_id,
            portfolio_id=portfolio_id,
            portfolio=portfolio,
            risk_policy=risk_policy,
            liquidity_gate=getattr(gate, "name", type(gate).__name__),
        )

        # 6. Only a committed decision may be returned as actionable.
        conn.commit()

    except Exception as exc:  # noqa: BLE001 - every failure must fail closed
        try:
            conn.rollback()
        except Exception:  # pragma: no cover - connection already unusable
            pass
        return DecisionRecord(
            plan=_persistence_unavailable_plan(snapshot),
            persisted=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    return DecisionRecord(
        plan=plan,
        persisted=True,
        snapshot_id=snapshot_id,
        validation_result_id=validation_result_id,
        risk_plan_id=risk_plan_id,
    )


def _no_trade_plan(snapshot: MarketSnapshot, reason: str) -> RiskPlan:
    """A refusal that still carries the provenance of what it refused."""
    return RiskPlan(
        ticker=snapshot.ticker,
        action="NO_TRADE",
        reason=reason,
        snapshot_source=snapshot.source,
        snapshot_timestamp_utc=snapshot.timestamp_utc,
    )


def _persistence_unavailable_plan(snapshot: MarketSnapshot) -> RiskPlan:
    return _no_trade_plan(snapshot, PERSISTENCE_UNAVAILABLE)


__all__ = [
    "LEVELS_UNAVAILABLE",
    "PERSISTENCE_UNAVAILABLE",
    "DecisionRecord",
    "PersistenceError",
    "evaluate_and_persist",
]
