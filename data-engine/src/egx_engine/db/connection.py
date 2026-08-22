"""Database connection helpers.

Credentials come from the environment only. Nothing in this repository stores a
DSN, a password, or a host name.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from .errors import PersistenceError

DSN_ENV_VAR = "DATABASE_URL"


def get_dsn(env_var: str = DSN_ENV_VAR) -> str:
    dsn = os.environ.get(env_var)
    if not dsn:
        raise PersistenceError(
            f"{env_var} is not set; refusing to guess database connection details"
        )
    return dsn


@contextmanager
def connect(dsn: str | None = None) -> Iterator["psycopg.Connection"]:  # noqa: F821
    """Open a connection with autocommit disabled.

    Transaction boundaries are the caller's decision, so a partially written
    decision can always be rolled back as a unit.
    """
    try:
        import psycopg
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on install
        raise PersistenceError("psycopg is required for database access") from exc

    try:
        conn = psycopg.connect(dsn or get_dsn(), autocommit=False)
    except psycopg.Error as exc:
        raise PersistenceError(f"could not connect to the database: {exc}") from exc

    try:
        yield conn
    finally:
        conn.close()
