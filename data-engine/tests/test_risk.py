from decimal import Decimal

from egx_engine.risk import build_risk_plan


def test_position_size_respects_risk_budget():
    plan = build_risk_plan(
        ticker="TEST",
        entry=Decimal("10"),
        stop_loss=Decimal("9.50"),
        target=Decimal("11"),
        equity_egp=Decimal("5000"),
        cash_egp=Decimal("5000"),
    )

    assert plan.action == "BUY"
    assert plan.shares == 150
    assert plan.risk_egp == Decimal("75.00")
    assert plan.risk_reward == Decimal("2")


def test_rejects_bad_risk_reward():
    plan = build_risk_plan(
        ticker="TEST",
        entry=Decimal("10"),
        stop_loss=Decimal("9"),
        target=Decimal("11"),
        equity_egp=Decimal("5000"),
        cash_egp=Decimal("5000"),
        min_rr=Decimal("1.5"),
    )

    assert plan.action == "NO_TRADE"
    assert plan.reason == "RISK_REWARD_BELOW_MINIMUM"
