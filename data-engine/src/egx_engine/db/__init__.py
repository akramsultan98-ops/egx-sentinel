"""PostgreSQL persistence for the EGX Sentinel engine.

The engine's decision logic lives in :mod:`egx_engine.validator` and
:mod:`egx_engine.risk` and is unchanged by persistence. This package only stores
and retrieves what those modules produce, transactionally and auditably.
"""

from .errors import (
    DuplicateExecutionError,
    InsufficientSharesError,
    PersistenceError,
    PortfolioStateUnavailableError,
)

__all__ = [
    "DuplicateExecutionError",
    "InsufficientSharesError",
    "PersistenceError",
    "PortfolioStateUnavailableError",
]
