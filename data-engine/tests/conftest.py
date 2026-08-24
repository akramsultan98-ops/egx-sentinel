"""Shared deterministic fixtures.

Every test pins an explicit clock. Nothing here reads the wall clock, so the
suite behaves identically on any machine at any time.

Database fixtures require ``EGX_TEST_DATABASE_URL`` pointing at a **throwaway**
database; the tables are truncated between tests. Without it the integration
tests skip rather than fail, so the pure-logic suite still runs anywhere.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from egx_engine.config import RiskPolicy
from egx_engine.models import DailyBar, MarketSnapshot, PortfolioState
from egx_engine.liquidity import TradedValueLiquidityGate

# A Wednesday inside an EGX trading session (12:00 Cairo == 10:00 UTC).
NOW = datetime(2026, 3, 11, 10, 0, 0, tzinfo=timezone.utc)


def make_bars(
    count: int,
    *,
    ticker: str = "TEST",
    close: str = "10",
    spread: str = "0.20",
    source: str = "fixture",
    end=None,
) -> list[DailyBar]:
    """A flat series with a constant daily range.

    Constant range makes the ATR exactly ``spread``, so tests can assert on
    derived levels arithmetically instead of against a magic number.
    """
    last_session = end or (NOW.date() - timedelta(days=1))
    price = Decimal(close)
    half = Decimal(spread) / 2

    return [
        DailyBar(
            ticker=ticker,
            session_date=last_session - timedelta(days=offset),
            open=price,
            high=price + half,
            low=price - half,
            close=price,
            volume=100_000,
            source=source,
        )
        for offset in reversed(range(count))
    ]


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


# --- database fixtures --------------------------------------------------

# Every table carrying test data, truncated between tests.
DATA_TABLES = (
    "risk_plans",
    "validation_results",
    "signals",
    "executions",
    "portfolio_positions",
    "market_snapshots",
    "daily_bars",
    "fundamentals",
    "news_events",
    "portfolio",
    "instruments",
)


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("EGX_TEST_DATABASE_URL")
    if not url:
        pytest.skip("EGX_TEST_DATABASE_URL is not set")
    pytest.importorskip("psycopg")
    return url


@pytest.fixture(scope="session")
def migrated_database(database_url):
    from egx_engine.db.connection import connect
    from egx_engine.db.migrate import migrate

    with connect(database_url) as conn:
        migrate(conn)
    return database_url


@pytest.fixture
def conn(migrated_database):
    """A clean, uncommitted connection against a freshly truncated schema."""
    from egx_engine.db.connection import connect

    with connect(migrated_database) as connection:
        with connection.cursor() as cur:
            cur.execute(
                f"TRUNCATE {', '.join(DATA_TABLES)} RESTART IDENTITY CASCADE"
            )
        connection.commit()
        yield connection
        connection.rollback()


@pytest.fixture
def repo(conn):
    from egx_engine.db.repository import Repository

    return Repository(conn)


@pytest.fixture
def instrument(repo, conn):
    """A single registered, Telda-verified instrument matching the snapshot fixture.

    Telda availability is a hard gate as of Phase 2, so the default fixture
    carries it; tests that care about the gate withdraw it explicitly.

    Committed, so a test that rolls back is measuring only its own writes.
    """
    repo.upsert_instrument(
        instrument_id="TEST",
        ticker="TEST",
        name="Test Instrument",
        source="fixture",
        source_updated_at=NOW,
        telda_available=True,
        telda_verified_at=NOW,
    )
    conn.commit()
    return "TEST"


@pytest.fixture
def portfolio_id(repo, conn, instrument):
    identifier = repo.create_portfolio(
        name="test-portfolio", initial_capital_egp=Decimal("5000")
    )
    conn.commit()
    return identifier
