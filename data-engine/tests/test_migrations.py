"""Migration runner behaviour against a real database."""

from pathlib import Path

import pytest

from egx_engine.db.errors import PersistenceError
from egx_engine.db.migrate import discover, migrate

pytestmark = pytest.mark.integration


def test_migrations_apply_and_are_idempotent(conn):
    """A second run must be a no-op, not a re-application."""
    assert migrate(conn) == []  # session fixture already applied them

    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        applied = [row[0] for row in cur.fetchall()]

    assert applied == [m.version for m in discover()]


def test_every_expected_object_exists(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        objects = {row[0] for row in cur.fetchall()}

    assert {
        "instruments",
        "market_snapshots",
        "validation_results",
        "risk_plans",
        "portfolio",
        "portfolio_positions",
        "executions",
        "signals",
        "schema_migrations",
        "portfolio_state",
    } <= objects


def test_tampered_checksum_is_detected(conn, tmp_path):
    """Editing an applied migration must fail rather than silently diverge."""
    with conn.cursor() as cur:
        cur.execute("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = 1")
    conn.commit()

    try:
        with pytest.raises(PersistenceError, match="changed after it was applied"):
            migrate(conn)
    finally:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE schema_migrations SET checksum = %s WHERE version = 1",
                (discover()[0].checksum,),
            )
        conn.commit()


def test_failed_migration_rolls_back(conn, tmp_path):
    """A migration that errors must leave no partial schema behind."""
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0900_partial.sql").write_text(
        "CREATE TABLE rollback_probe (id INTEGER);\n"
        "CREATE TABLE rollback_probe_two (id INTEGER, bad SYNTAX HERE);\n"
    )

    with pytest.raises(PersistenceError, match="failed and was rolled back"):
        migrate(conn, directory)

    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.rollback_probe')")
        assert cur.fetchone()[0] is None
        cur.execute("SELECT count(*) FROM schema_migrations WHERE version = 900")
        assert cur.fetchone()[0] == 0


def test_bad_filename_is_rejected(conn, tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "nope.sql").write_text("SELECT 1;")

    with pytest.raises(PersistenceError, match="not NNNN_name.sql"):
        migrate(conn, directory)


def test_duplicate_version_is_rejected(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_one.sql").write_text("SELECT 1;")
    (directory / "0001_two.sql").write_text("SELECT 2;")

    with pytest.raises(PersistenceError, match="duplicate migration version"):
        discover(directory)
