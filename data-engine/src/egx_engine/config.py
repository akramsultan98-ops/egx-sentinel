"""Single source of truth for EGX Sentinel's deterministic constants.

CANONICAL UNIT RULE
-------------------
Every ratio in this module is stored as a **decimal fraction of 1**, never as a
percentage. ``Decimal("0.015")`` means 1.5%.

This rule exists because the same number previously lived in three places in two
different unit systems (``risk.py`` used ``0.015``, ``config/risk-policy.md``
said "1.5%", and ``portfolio.risk_budget_pct`` in SQL defaults to ``1.5``).
Percentages are a *presentation* format only: use :func:`as_percent` when writing
to a percent-typed database column or rendering a message. Never feed a percent
value back into a calculation.

Nothing in this module reads the environment, the filesystem, or the network, so
every value here is deterministic and safe to use inside pure calculations.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


def as_percent(fraction: Decimal) -> Decimal:
    """Convert a canonical fraction to a percentage for display/storage only."""
    return fraction * Decimal("100")


class RiskPolicy(BaseModel):
    """Deterministic risk limits. Mirrors ``config/risk-policy.md``.

    All fractions are fractions of 1 (see the module docstring).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Fraction of *current equity* that may be lost if a single tactical
    # position is stopped out. 0.015 == 1.5% == EGP 75 on EGP 5,000.
    risk_per_trade_fraction: Decimal = Field(default=Decimal("0.015"), gt=0, le=Decimal("1"))

    # Minimum reward-to-risk before a BUY is permitted, measured *net of fees*.
    min_risk_reward: Decimal = Field(default=Decimal("2"), gt=0)

    # Maximum simultaneous tactical positions.
    max_open_positions: int = Field(default=2, ge=0)

    # Maximum fraction of equity a single position's notional value may occupy.
    # Derived from max_open_positions: 2 positions x 0.30 leaves a 40% cash
    # buffer. Risk-per-trade alone does NOT bound notional exposure, so this is
    # a separate gate: a 1%-wide stop would otherwise justify 100% of capital.
    max_position_concentration_fraction: Decimal = Field(
        default=Decimal("0.30"), gt=0, le=Decimal("1")
    )

    # How far a proposed entry may sit from the validated last traded price.
    # This is what stops an unvalidated/invented price from reaching sizing.
    max_entry_deviation_fraction: Decimal = Field(
        default=Decimal("0.02"), ge=0, le=Decimal("1")
    )

    # --- Fees -------------------------------------------------------------
    # UNVERIFIED PLACEHOLDER. The real Telda/broker commission, EGX levy, and
    # stamp-duty schedule has not been confirmed yet. This default is used only
    # because ignoring fees would *understate* risk; a conservative non-zero
    # rate can only shrink position size, never inflate it. It must be replaced
    # with the verified schedule before real-money use.
    fee_rate_fraction: Decimal = Field(default=Decimal("0.0025"), ge=0, le=Decimal("1"))
    min_fee_egp: Decimal = Field(default=Decimal("0"), ge=0)

    @property
    def risk_per_trade_percent(self) -> Decimal:
        """Percent form, for percent-typed DB columns and user-facing text."""
        return as_percent(self.risk_per_trade_fraction)

    @property
    def max_position_concentration_percent(self) -> Decimal:
        return as_percent(self.max_position_concentration_fraction)


class DataPolicy(BaseModel):
    """Deterministic market-data validation thresholds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # A snapshot older than this is not eligible for a trading decision.
    max_freshness_seconds: int = Field(default=120, ge=0)

    # Allowed disagreement between the provider's self-reported
    # ``freshness_seconds`` and the age actually implied by ``source_timestamp``.
    # A provider that misreports beyond this tolerance is treated as INVALID,
    # never merely stale: self-reported freshness is a claim, not evidence.
    freshness_tolerance_seconds: int = Field(default=30, ge=0)

    # Clock-skew allowance before a timestamp counts as "in the future".
    future_tolerance_seconds: int = Field(default=30, ge=0)

    # How far back a session_date may sit relative to the current market date.
    max_session_age_days: int = Field(default=5, ge=0)

    # Allowed gap between session_date and the market-local date implied by
    # timestamp_utc (1 day absorbs post-close/pre-open boundary cases).
    max_session_timestamp_gap_days: int = Field(default=1, ge=0)

    market_timezone: str = "Africa/Cairo"


DEFAULT_RISK_POLICY = RiskPolicy()
DEFAULT_DATA_POLICY = DataPolicy()
