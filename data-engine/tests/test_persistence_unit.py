"""Persistence unit tests that need no database."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from egx_engine.db.connection import get_dsn
from egx_engine.db.errors import (
    DuplicateExecutionError,
    InsufficientSharesError,
    PersistenceError,
    PortfolioStateUnavailableError,
)
from egx_engine.db.migrate import MIGRATION_PATTERN, discover
from egx_engine.db.repository import require_utc
from egx_engine.pipeline import PERSISTENCE_UNAVAILABLE, _persistence_unavailable_plan

from conftest import NOW, make_snapshot


def test_naive_timestamps_are_refused():
    """A naive datetime has no defined instant and must never be stored."""
    with pytest.raises(PersistenceError):
        require_utc(datetime(2026, 3, 11, 10, 0, 0), "timestamp_utc")


def test_non_utc_timestamps_are_normalised():
    cairo = timezone(timedelta(hours=2))
    local = datetime(2026, 3, 11, 12, 0, 0, tzinfo=cairo)
    stored = require_utc(local, "timestamp_utc")
    assert stored.tzinfo == timezone.utc
    assert stored == NOW


def test_missing_dsn_fails_loudly(monkeypatch):
    """The system must never invent connection details."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(PersistenceError):
        get_dsn()


def test_all_persistence_errors_are_safe_failures():
    for error in (
        DuplicateExecutionError,
        InsufficientSharesError,
        PortfolioStateUnavailableError,
    ):
        assert issubclass(error, PersistenceError)


def test_persistence_failure_plan_is_no_trade():
    plan = _persistence_unavailable_plan(make_snapshot())
    assert plan.action == "NO_TRADE"
    assert plan.reason == PERSISTENCE_UNAVAILABLE
    assert plan.shares == 0


def test_migrations_are_discovered_in_order():
    migrations = discover()
    versions = [m.version for m in migrations]
    assert versions == sorted(versions)
    assert len(versions) == len(set(versions)), "duplicate migration versions"
    assert versions[0] == 1


def test_migration_checksums_are_stable_per_content():
    migrations = {m.version: m for m in discover()}
    assert migrations[1].checksum == migrations[1].checksum
    assert migrations[1].checksum != migrations[2].checksum


def test_migration_filename_pattern():
    assert MIGRATION_PATTERN.match("0001_initial_schema.sql")
    assert MIGRATION_PATTERN.match("0002_phase1_persistence.sql")
    assert not MIGRATION_PATTERN.match("1_bad.sql")
    assert not MIGRATION_PATTERN.match("0001-bad.sql")
