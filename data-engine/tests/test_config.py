"""Configuration tests: the canonical-unit rule must stay enforceable."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from egx_engine.config import (
    DEFAULT_DATA_POLICY,
    DEFAULT_RISK_POLICY,
    DataPolicy,
    RiskPolicy,
    as_percent,
)


def test_risk_per_trade_is_stored_as_a_fraction():
    """0.015, never 1.5. The percent form is derived, never stored."""
    assert DEFAULT_RISK_POLICY.risk_per_trade_fraction == Decimal("0.015")
    assert DEFAULT_RISK_POLICY.risk_per_trade_percent == Decimal("1.500")


def test_percent_helper_matches_the_documented_database_value():
    """portfolio.risk_budget_pct defaults to 1.5 in SQL; same number, other unit."""
    assert as_percent(DEFAULT_RISK_POLICY.risk_per_trade_fraction) == Decimal("1.500")
    assert as_percent(DEFAULT_RISK_POLICY.max_position_concentration_fraction) == Decimal("30.00")


def test_risk_budget_on_initial_capital_is_75_egp():
    assert Decimal("5000") * DEFAULT_RISK_POLICY.risk_per_trade_fraction == Decimal("75.000")


def test_policy_defaults_match_the_written_risk_policy():
    assert DEFAULT_RISK_POLICY.min_risk_reward == Decimal("2")
    assert DEFAULT_RISK_POLICY.max_open_positions == 2


def test_a_percent_value_is_rejected_as_a_fraction():
    """Passing 1.5 where a fraction belongs must fail loudly, not silently."""
    with pytest.raises(ValidationError):
        RiskPolicy(risk_per_trade_fraction=Decimal("1.5"))
    with pytest.raises(ValidationError):
        RiskPolicy(max_position_concentration_fraction=Decimal("30"))


def test_policies_are_immutable():
    with pytest.raises(ValidationError):
        DEFAULT_RISK_POLICY.min_risk_reward = Decimal("1")
    with pytest.raises(ValidationError):
        DEFAULT_DATA_POLICY.max_freshness_seconds = 99999


def test_unknown_policy_fields_are_rejected():
    with pytest.raises(ValidationError):
        RiskPolicy(risk_pct=Decimal("0.015"))
    with pytest.raises(ValidationError):
        DataPolicy(max_freshness=120)


def test_data_policy_defaults():
    assert DEFAULT_DATA_POLICY.max_freshness_seconds == 120
    assert DEFAULT_DATA_POLICY.market_timezone == "Africa/Cairo"
