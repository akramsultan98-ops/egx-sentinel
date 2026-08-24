"""The Telda investment universe: a hard, database-backed execution gate.

``config/telda-universe.md`` makes Telda availability a precondition for any
BUY. The universe is operator-verified state rather than a market fact, so it
lives in the database and the gate lives here rather than inside the pure risk
engine.

Two halves:

* :func:`check_universe` — pure. It is handed the instrument row (or ``None``)
  and returns a verdict. Nothing about it touches a database, so the gate's
  behaviour is testable without one.
* :func:`load_universe_csv` — parses the operator-maintained seed file.

Fail closed in every direction. An unknown instrument, an instrument whose
availability was never verified, and an instrument explicitly marked
unavailable are all refused. There is no path where silence means "tradeable".
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Mapping

# Verdict reasons. These are persisted as ``risk_plans.reason``, so they are
# part of the audit vocabulary and must stay stable.
TELDA_UNIVERSE_OK = "TELDA_UNIVERSE_OK"
NOT_IN_TELDA_UNIVERSE = "NOT_IN_TELDA_UNIVERSE"
TELDA_AVAILABILITY_UNVERIFIED = "TELDA_AVAILABILITY_UNVERIFIED"
INSTRUMENT_NOT_REGISTERED = "INSTRUMENT_NOT_REGISTERED"

CSV_COLUMNS = (
    "instrument_id",
    "ticker",
    "name",
    "asset_type",
    "sector",
    "telda_available",
    "telda_verified_on",
)

_TRUE = frozenset({"true", "yes", "1"})
_FALSE = frozenset({"false", "no", "0", ""})


class UniverseError(ValueError):
    """The universe seed file is malformed and must not be loaded."""


@dataclass(frozen=True)
class UniverseVerdict:
    ok: bool
    reason: str


@dataclass(frozen=True)
class UniverseEntry:
    """One operator-verified row of the Telda universe."""

    instrument_id: str
    ticker: str
    name: str
    asset_type: str
    sector: str | None
    telda_available: bool
    telda_verified_at: datetime | None


def check_universe(instrument: Mapping[str, Any] | None) -> UniverseVerdict:
    """Decide whether an instrument may be traded through Telda.

    Args:
        instrument: the ``instruments`` row, or ``None`` when the instrument is
            not registered at all.
    """
    if instrument is None:
        return UniverseVerdict(ok=False, reason=INSTRUMENT_NOT_REGISTERED)

    if not instrument.get("telda_available"):
        return UniverseVerdict(ok=False, reason=NOT_IN_TELDA_UNIVERSE)

    # Defence in depth: the database CHECK constraint already forbids this
    # combination. If it ever appears anyway, refuse rather than trust it.
    if instrument.get("telda_verified_at") is None:
        return UniverseVerdict(ok=False, reason=TELDA_AVAILABILITY_UNVERIFIED)

    return UniverseVerdict(ok=True, reason=TELDA_UNIVERSE_OK)


def _parse_bool(raw: str | None, *, row: int) -> bool:
    value = (raw or "").strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise UniverseError(
        f"row {row}: telda_available must be true or false, got {raw!r}"
    )


def _parse_verified_on(raw: str | None, *, row: int) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        verified_on = date.fromisoformat(value)
    except ValueError as exc:
        raise UniverseError(
            f"row {row}: telda_verified_on must be an ISO date (YYYY-MM-DD), "
            f"got {raw!r}"
        ) from exc
    return datetime.combine(verified_on, time(0, 0), tzinfo=timezone.utc)


def load_universe_csv(path: str | Path) -> list[UniverseEntry]:
    """Parse the operator-maintained universe file.

    An entry may only claim ``telda_available=true`` if it also carries the
    date the operator verified it in the Telda app. That mirrors the database
    constraint, so a bad file is rejected before it reaches PostgreSQL.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise UniverseError(f"could not read universe file {path}: {exc}") from exc

    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise UniverseError(f"universe file {path} is empty")

    missing = [c for c in CSV_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise UniverseError(
            f"universe file {path} is missing column(s): {', '.join(missing)}"
        )

    entries: list[UniverseEntry] = []
    seen: set[str] = set()

    for offset, raw_row in enumerate(reader, start=2):  # row 1 is the header
        instrument_id = (raw_row.get("instrument_id") or "").strip()
        ticker = (raw_row.get("ticker") or "").strip()
        name = (raw_row.get("name") or "").strip()

        if not instrument_id and not ticker and not name:
            continue  # blank padding line

        if not instrument_id or not ticker or not name:
            raise UniverseError(
                f"row {offset}: instrument_id, ticker, and name are all required"
            )
        if instrument_id in seen:
            raise UniverseError(f"row {offset}: duplicate instrument_id {instrument_id!r}")
        seen.add(instrument_id)

        available = _parse_bool(raw_row.get("telda_available"), row=offset)
        verified_at = _parse_verified_on(raw_row.get("telda_verified_on"), row=offset)

        if available and verified_at is None:
            raise UniverseError(
                f"row {offset}: {ticker} is marked telda_available without a "
                "telda_verified_on date; availability must be verified by a human"
            )

        sector = (raw_row.get("sector") or "").strip()
        asset_type = (raw_row.get("asset_type") or "").strip() or "EQUITY"

        entries.append(
            UniverseEntry(
                instrument_id=instrument_id,
                ticker=ticker,
                name=name,
                asset_type=asset_type,
                sector=sector or None,
                telda_available=available,
                telda_verified_at=verified_at,
            )
        )

    return entries


__all__ = [
    "CSV_COLUMNS",
    "INSTRUMENT_NOT_REGISTERED",
    "NOT_IN_TELDA_UNIVERSE",
    "TELDA_AVAILABILITY_UNVERIFIED",
    "TELDA_UNIVERSE_OK",
    "UniverseEntry",
    "UniverseError",
    "UniverseVerdict",
    "check_universe",
    "load_universe_csv",
]
