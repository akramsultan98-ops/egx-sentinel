"""Liquidity gate interface.

The risk policy makes liquidity a hard gate, but the data needed to evaluate it
depends on a market-data provider that has not been selected or verified yet.
This module therefore supplies the *contract* plus a fail-closed default, in the
same spirit as :class:`egx_engine.provider.UnconfiguredProvider`.

The gate answers one question: what is the largest EGP notional this instrument
can absorb right now? Sizing then treats that as one more binding constraint,
alongside the risk budget, available cash, and the concentration cap.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from .models import MarketSnapshot


class LiquidityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    # Largest position notional this instrument may absorb, in EGP.
    # None whenever ``ok`` is False.
    max_position_value_egp: Decimal | None = None
    reason: str


@runtime_checkable
class LiquidityGate(Protocol):
    """Contract every liquidity implementation must satisfy."""

    name: str

    def assess(self, snapshot: MarketSnapshot) -> LiquidityAssessment: ...


class UnconfiguredLiquidityGate:
    """Explicit fail-closed gate used until liquidity inputs are verified.

    This is the default. A caller that has not supplied a real gate gets
    ``NO_TRADE``, never an unchecked BUY.
    """

    name = "unconfigured"

    def assess(self, snapshot: MarketSnapshot) -> LiquidityAssessment:
        return LiquidityAssessment(ok=False, reason="LIQUIDITY_NOT_VERIFIED")


class TradedValueLiquidityGate:
    """Cap position size at a fraction of the session's traded value.

    Deterministic and provider-agnostic: it consumes only fields the snapshot
    model already carries. If ``traded_value_egp`` is absent the gate fails
    closed rather than assuming the instrument is liquid.
    """

    name = "traded_value"

    def __init__(
        self,
        max_participation_fraction: Decimal = Decimal("0.01"),
        min_traded_value_egp: Decimal = Decimal("0"),
    ):
        if max_participation_fraction <= 0:
            raise ValueError("max_participation_fraction must be > 0")
        self.max_participation_fraction = max_participation_fraction
        self.min_traded_value_egp = min_traded_value_egp

    def assess(self, snapshot: MarketSnapshot) -> LiquidityAssessment:
        traded_value = snapshot.traded_value_egp
        if traded_value is None:
            return LiquidityAssessment(ok=False, reason="LIQUIDITY_DATA_UNAVAILABLE")

        if traded_value < self.min_traded_value_egp:
            return LiquidityAssessment(ok=False, reason="LIQUIDITY_INSUFFICIENT")

        max_value = (traded_value * self.max_participation_fraction).quantize(
            Decimal("0.0001"), rounding=ROUND_FLOOR
        )
        if max_value <= 0:
            return LiquidityAssessment(ok=False, reason="LIQUIDITY_INSUFFICIENT")

        return LiquidityAssessment(
            ok=True,
            max_position_value_egp=max_value,
            reason="LIQUIDITY_OK",
        )
