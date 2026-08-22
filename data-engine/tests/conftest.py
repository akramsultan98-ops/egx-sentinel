"""Shared deterministic fixtures.

Every test pins an explicit clock. Nothing here reads the wall clock, so the
suite behaves identically on any machine at any time.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from egx_engine.config import RiskPolicy
from egx_engine.models import MarketSnapshot, PortfolioState
from egx_engine.liquidity import TradedValueLiquidityGate

# A Wednesday inside an EGX trading session (12:00 Cairo == 10:00 UTC).
NOW = datetime(2026, 3, 11, 10, 0, 0, tzinfo=timezone.utc)


def make_snapshot(**overrides) -> MarketSnapshot:
    base = dict(
        instrument_id="TEST",
        ticker="TEST",
        timestamp_utc=NOW,
        session_date=NOW.date(),
        last_price=Decimal("10"),
        open=Decimal("9.5"),
        high=Decimal("10.5"),
        low=Decimal("9.5"),
        traded_value_egp=Decimal("5000000"),
        source="fixture",
        source_timestamp=NOW,
        freshness_seconds=10,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def snapshot():
    return make_snapshot()


@pytest.fixture
def portfolio():
    return PortfolioState(
        equity_egp=Decimal("5000"),
        cash_egp=Decimal("5000"),
        open_positions=0,
    )


@pytest.fixture
def zero_fee_policy():
    """Isolates the risk-per-trade rule from the fee model."""
    return RiskPolicy(fee_rate_fraction=Decimal("0"), min_fee_egp=Decimal("0"))


@pytest.fixture
def liquid_gate():
    """Generous gate so liquidity is not the binding constraint by accident."""
    return TradedValueLiquidityGate(max_participation_fraction=Decimal("1"))
