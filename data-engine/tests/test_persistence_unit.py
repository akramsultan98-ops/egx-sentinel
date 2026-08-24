"""Persistence unit tests that need no database."""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import egx_engine
from egx_engine.cli import default_universe_file
from egx_engine.db.connection import get_dsn
from egx_engine.db.errors import (
    DuplicateExecutionError,
    InsufficientSharesError,
    PersistenceError,
    PortfolioStateUnavailableError,
)
from egx_engine.db.migrate import (
    MIGRATION_PATTERN,
    check_files,
    default_migrations_dir,
    discover,
)
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


# --- packaging: resources must travel with the distribution --------------
#
# These cover the bug where migrations and the seed universe were repository
# files located by walking upward from __file__. That works in a source
# checkout, where the repo root is an ancestor of the package, and fails for
# every installed package, whose site-packages location shares no ancestor with
# the repository. The container found it; a wheel would have too.


def test_migrations_ship_inside_the_package():
    """The invariant: resolution must not depend on anything above the package."""
    package_dir = Path(egx_engine.__file__).resolve().parent
    assert default_migrations_dir().resolve().parent == package_dir


def test_seed_universe_ships_inside_the_package():
    package_dir = Path(egx_engine.__file__).resolve().parent
    assert default_universe_file().resolve().parent.parent == package_dir


def test_package_data_is_declared_for_every_resource_directory():
    """A missed declaration ships an empty directory and breaks the install."""
    pyproject = (
        Path(egx_engine.__file__).resolve().parents[2] / "pyproject.toml"
    )
    if not pyproject.is_file():  # pragma: no cover - installed without sources
        pytest.skip("pyproject.toml is not part of an installed distribution")

    declared = pyproject.read_text(encoding="utf-8")
    assert "migrations/*.sql" in declared
    assert "data/*.csv" in declared


def test_check_files_accepts_the_shipped_migrations():
    versions = [m.version for m in check_files()]
    assert versions == sorted(versions)
    assert versions[0] == 1


def test_resources_resolve_with_no_repository_above_the_package(tmp_path):
    """Reproduces the container layout exactly.

    The package is copied somewhere with no repository root above it — the
    situation `pip install` creates — and imported in a fresh interpreter. The
    old parent-walk raised PersistenceError here; resolution through the
    package does not care where the package sits.
    """
    site = tmp_path / "site-packages"
    site.mkdir()
    shutil.copytree(Path(egx_engine.__file__).resolve().parent, site / "egx_engine")

    probe = (
        "import egx_engine, json\n"
        "from egx_engine.db.migrate import default_migrations_dir, discover\n"
        "from egx_engine.cli import default_universe_file\n"
        "print(json.dumps({\n"
        "  'package': egx_engine.__file__,\n"
        "  'migrations': len(discover(default_migrations_dir())),\n"
        "  'universe': default_universe_file().is_file(),\n"
        "}))\n"
    )

    env = dict(os.environ, PYTHONPATH=str(site))
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, cwd=tmp_path, env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    # Guard the test itself: it is meaningless unless the copy was imported
    # rather than the development checkout.
    assert str(site) in payload["package"]
    assert payload["migrations"] >= 3
    assert payload["universe"] is True
