"""Forward-only, checksummed SQL migrations.

Rules:

* Migrations are files named ``NNNN_description.sql`` and run in numeric order.
* Each migration runs inside its own transaction: it applies completely or not
  at all.
* Every applied migration's checksum is recorded. Editing a migration that has
  already run is an error, not a silent divergence — write a new one instead.

Run with ``python -m egx_engine.db.migrate`` (uses ``DATABASE_URL``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .connection import connect
from .errors import PersistenceError

MIGRATION_PATTERN = re.compile(r"^(\d{4})_([A-Za-z0-9_\-]+)\.sql$")

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  checksum TEXT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def default_migrations_dir() -> Path:
    """Locate ``db/migrations`` relative to this checkout."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "db" / "migrations"
        if candidate.is_dir():
            return candidate
    raise PersistenceError("could not locate db/migrations")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover(directory: Path | None = None) -> list[Migration]:
    directory = directory or default_migrations_dir()
    migrations: list[Migration] = []
    seen: dict[int, str] = {}

    for path in sorted(directory.iterdir()):
        if path.suffix != ".sql":
            continue
        match = MIGRATION_PATTERN.match(path.name)
        if not match:
            raise PersistenceError(f"migration filename is not NNNN_name.sql: {path.name}")
        version = int(match.group(1))
        if version in seen:
            raise PersistenceError(
                f"duplicate migration version {version}: {seen[version]} and {path.name}"
            )
        seen[version] = path.name
        migrations.append(
            Migration(
                version=version,
                name=match.group(2),
                path=path,
                sql=path.read_text(encoding="utf-8"),
            )
        )

    return sorted(migrations, key=lambda m: m.version)


def applied_versions(conn) -> dict[int, str]:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_MIGRATIONS_DDL)
        cur.execute("SELECT version, checksum FROM schema_migrations")
        return {row[0]: row[1] for row in cur.fetchall()}


def migrate(conn, directory: Path | None = None) -> list[int]:
    """Apply every pending migration. Returns the versions applied.

    The caller's connection is used so tests can run this against a throwaway
    database. Each migration commits on its own.
    """
    migrations = discover(directory)
    already = applied_versions(conn)
    conn.commit()

    for migration in migrations:
        recorded = already.get(migration.version)
        if recorded is not None and recorded != migration.checksum:
            raise PersistenceError(
                f"migration {migration.version:04d}_{migration.name} changed after it was "
                "applied; add a new migration instead of editing history"
            )

    pending = [m for m in migrations if m.version not in already]
    applied: list[int] = []

    for migration in pending:
        try:
            with conn.cursor() as cur:
                cur.execute(migration.sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) "
                    "VALUES (%s, %s, %s)",
                    (migration.version, migration.name, migration.checksum),
                )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise PersistenceError(
                f"migration {migration.version:04d}_{migration.name} failed and was "
                f"rolled back: {exc}"
            ) from exc
        applied.append(migration.version)

    return applied


def main() -> int:  # pragma: no cover - CLI entry point
    with connect() as conn:
        applied = migrate(conn)
    if applied:
        print("applied migrations:", ", ".join(f"{v:04d}" for v in applied))
    else:
        print("database is up to date")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
