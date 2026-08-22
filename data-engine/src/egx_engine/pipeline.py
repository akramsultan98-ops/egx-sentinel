"""Audited decision flow: validate, size, persist — in that order, atomically.

This module adds persistence around the Phase 0 engine. It does not change how
decisions are made: :func:`egx_engine.validator.validate_snapshot` and
:func:`egx_engine.risk.build_risk_plan` are called unmodified and their verdict
is final.

What it adds is the guarantee that a decision you can act on is a decision that
was durably recorded. If any part of persistence fails, the returned plan is
``NO_TRADE`` with reason ``PERSISTENCE_UNAVAILABLE`` — an unrecorded BUY is
never handed back to a caller.
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
from .risk import build_risk_plan
from .validator import validate_snapshot

PERSISTENCE_UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"


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
    stop_loss: Decimal,
    target: Decimal,
    portfolio_id: int,
    entry: Decimal | None = None,
    risk_policy: RiskPolicy = DEFAULT_RISK_POLICY,
    data_policy: DataPolicy = DEFAULT_DATA_POLICY,
    max_freshness_seconds: int | None = None,
    liquidity_gate: LiquidityGate | None = None,
    now: datetime | None = None,
) -> DecisionRecord:
    """Run one decision end to end and commit it as a single transaction.

    Order matters: the portfolio must be readable before sizing, and the plan
    must be committed before it is returned.
    """
    now = now or datetime.now(timezone.utc)
    gate = liquidity_gate if liquidity_gate is not None else UnconfiguredLiquidityGate()
    repo = Repository(conn)

    try:
        # 1. Sizing inputs come from the database, never from a caller's guess.
        portfolio = repo.get_portfolio_state(portfolio_id)

        # 2. Phase 0 validation, unmodified.
        validation = validate_snapshot(
            snapshot,
            max_freshness_seconds=max_freshness_seconds,
            policy=data_policy,
            now=now,
        )

        # 3. Record the source data and the verdict, including a rejection:
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

        # 4. Phase 0 sizing, unmodified.
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

        # 5. Only a committed decision may be returned as actionable.
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


def _persistence_unavailable_plan(snapshot: MarketSnapshot) -> RiskPlan:
    return RiskPlan(
        ticker=snapshot.ticker,
        action="NO_TRADE",
        reason=PERSISTENCE_UNAVAILABLE,
        snapshot_source=snapshot.source,
        snapshot_timestamp_utc=snapshot.timestamp_utc,
    )


__all__ = [
    "PERSISTENCE_UNAVAILABLE",
    "DecisionRecord",
    "PersistenceError",
    "evaluate_and_persist",
]
