"""Persistence error types.

Every one of these is a *safe* failure: callers must translate them into
NO_TRADE, never into an executable decision.
"""

from __future__ import annotations


class PersistenceError(RuntimeError):
    """Base class for any failure to read or write durable state."""


class DuplicateExecutionError(PersistenceError):
    """An execution with the same idempotency key was already recorded.

    Raised instead of silently applying the same fill twice.
    """


class InsufficientSharesError(PersistenceError):
    """A SELL was reported for more shares than the portfolio holds."""


class PortfolioStateUnavailableError(PersistenceError):
    """Portfolio equity could not be established.

    Raised when an open position has no validated price, so total equity is
    unknown. Position sizing must not run against a guessed equity figure.
    """
