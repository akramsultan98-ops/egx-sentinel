"""Provider selection, and the interim operator-supplied provider.

No licensed market-data feed has been authorised yet (see
``docs/data-source-policy.md``), so the only concrete provider here reads files
the operator maintains by hand. It is given **no** privileges for that: what it
returns is validated, universe-gated, and liquidity-gated exactly like a vendor
feed would be, and it stamps ``source="manual"`` so no row's provenance is ever
ambiguous. A manual price that is stale or self-contradictory is refused by
:mod:`egx_engine.validator` just the same.

When a licensed feed is authorised it becomes another entry in
:data:`PROVIDERS` and nothing downstream changes.

Expected layout of ``MARKET_DATA_DIR``::

    <dir>/snapshots.json      JSON array of MarketSnapshot objects
    <dir>/instruments.json    JSON array of instrument dicts (optional)
    <dir>/bars/<TICKER>.csv   session_date,open,high,low,close,volume

Numbers in JSON are parsed straight to :class:`~decimal.Decimal`. Going via
``float`` would introduce binary rounding error into prices before validation
ever saw them.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Sequence

from .models import DailyBar, MarketSnapshot
from .provider import MarketDataError, MarketDataProvider, UnconfiguredProvider
from .settings import Settings, SettingsError

SNAPSHOT_FILE = "snapshots.json"
INSTRUMENT_FILE = "instruments.json"
BAR_DIRECTORY = "bars"
BAR_COLUMNS = ("session_date", "open", "high", "low", "close", "volume")


def _normalise(symbol: str) -> str:
    return symbol.strip().upper()


class ManualFileProvider(MarketDataProvider):
    """Reads operator-supplied market data from a local directory.

    Deliberately dumb: it parses, it does not interpret. Every judgement about
    whether the data is usable is made downstream by the validator and the risk
    engine.
    """

    name = "manual"

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    # -- helpers ----------------------------------------------------------

    def _read_json(self, filename: str) -> Any:
        path = self.data_dir / filename
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MarketDataError(f"could not read {path}: {exc}") from exc
        try:
            # parse_float=Decimal keeps prices exact; a float round-trip would
            # corrupt them before anything had a chance to validate them.
            return json.loads(text, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            raise MarketDataError(f"{path} is not valid JSON: {exc}") from exc

    # -- provider contract ------------------------------------------------

    def health(self) -> bool:
        """Healthy when the data directory and a snapshot file both exist."""
        return self.data_dir.is_dir() and (self.data_dir / SNAPSHOT_FILE).is_file()

    def instruments(self) -> Sequence[dict]:
        path = self.data_dir / INSTRUMENT_FILE
        if not path.is_file():
            return []
        payload = self._read_json(INSTRUMENT_FILE)
        if not isinstance(payload, list):
            raise MarketDataError(f"{path} must contain a JSON array")
        return payload

    def snapshot(self, symbols: Sequence[str]) -> list[MarketSnapshot]:
        """Return snapshots for the requested tickers.

        Tickers with no entry are simply absent from the result rather than
        raising: during a multi-ticker scan one missing quote must not suppress
        every other candidate. The caller is responsible for noticing the gap,
        and no decision can be produced without a snapshot anyway.
        """
        payload = self._read_json(SNAPSHOT_FILE)
        if not isinstance(payload, list):
            raise MarketDataError(
                f"{self.data_dir / SNAPSHOT_FILE} must contain a JSON array"
            )

        wanted = {_normalise(s) for s in symbols}
        snapshots: list[MarketSnapshot] = []

        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                raise MarketDataError(
                    f"{SNAPSHOT_FILE} entry {index} is not an object"
                )
            if _normalise(str(item.get("ticker", ""))) not in wanted:
                continue
            try:
                snapshots.append(MarketSnapshot(**item))
            except Exception as exc:  # pydantic ValidationError and friends
                raise MarketDataError(
                    f"{SNAPSHOT_FILE} entry {index} is not a usable snapshot: {exc}"
                ) from exc

        return snapshots

    def daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        ticker = _normalise(symbol)
        path = self.data_dir / BAR_DIRECTORY / f"{ticker}.csv"
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise MarketDataError(f"no bar history for {ticker}: {exc}") from exc

        reader = csv.DictReader(text.splitlines())
        if reader.fieldnames is None:
            raise MarketDataError(f"{path} is empty")
        missing = [c for c in BAR_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise MarketDataError(f"{path} is missing column(s): {', '.join(missing)}")

        bars: list[DailyBar] = []
        for offset, row in enumerate(reader, start=2):
            raw_date = (row.get("session_date") or "").strip()
            if not raw_date:
                continue
            try:
                session_date = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise MarketDataError(
                    f"{path} row {offset}: session_date must be ISO (YYYY-MM-DD)"
                ) from exc

            if session_date < start or session_date > end:
                continue

            try:
                bars.append(
                    DailyBar(
                        ticker=ticker,
                        session_date=session_date,
                        open=Decimal(row["open"].strip()),
                        high=Decimal(row["high"].strip()),
                        low=Decimal(row["low"].strip()),
                        close=Decimal(row["close"].strip()),
                        volume=int(row["volume"].strip() or 0),
                        source=self.name,
                    )
                )
            except (InvalidOperation, ValueError, TypeError, AttributeError) as exc:
                raise MarketDataError(f"{path} row {offset} is unusable: {exc}") from exc

        bars.sort(key=lambda bar: bar.session_date)
        return bars


class PayloadProvider(MarketDataProvider):
    """Serves market data supplied in the request itself.

    The orchestrator (n8n) already holds the numbers when it calls us, so there
    is nothing to fetch. This makes that path a first-class provider rather than
    a side door: payload data reaches the engine through the same contract as a
    vendor feed and is validated identically.

    ``name`` is ``payload`` — the *transport*. Each quote keeps its own
    ``source`` field (``google_sheet``, ``manual``, a vendor name), because that
    is the provenance that matters and it is what gets persisted. A spreadsheet
    is never allowed to look like a live feed.

    The provider asserts nothing about freshness or correctness. It parses.
    """

    name = "payload"

    def __init__(
        self,
        quotes: Sequence[MarketSnapshot],
        bars: dict[str, Sequence[DailyBar]] | None = None,
    ):
        self._quotes = {_normalise(q.ticker): q for q in quotes}
        self._bars = {_normalise(k): list(v) for k, v in (bars or {}).items()}

    def health(self) -> bool:
        """Healthy when at least one quote was supplied."""
        return bool(self._quotes)

    def instruments(self) -> Sequence[dict]:
        return []

    def snapshot(self, symbols: Sequence[str]) -> list[MarketSnapshot]:
        wanted = [_normalise(s) for s in symbols]
        return [self._quotes[s] for s in wanted if s in self._quotes]

    def daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        ticker = _normalise(symbol)
        if ticker not in self._bars:
            raise MarketDataError(f"no bar history supplied for {ticker}")
        bars = [b for b in self._bars[ticker] if start <= b.session_date <= end]
        bars.sort(key=lambda bar: bar.session_date)
        return bars


PROVIDERS = ("unconfigured", "manual")


def get_provider(settings: Settings) -> MarketDataProvider:
    """Build the provider named by the environment.

    An unrecognised name raises rather than quietly falling back. A typo must
    be visible, not silently reinterpreted.
    """
    name = settings.provider_name

    if name == "unconfigured":
        return UnconfiguredProvider()
    if name == "manual":
        return ManualFileProvider(settings.require_provider_data_dir())

    raise SettingsError(
        f"unknown market-data provider {name!r}; known providers: "
        f"{', '.join(PROVIDERS)}"
    )


__all__ = [
    "BAR_COLUMNS",
    "BAR_DIRECTORY",
    "INSTRUMENT_FILE",
    "PROVIDERS",
    "SNAPSHOT_FILE",
    "ManualFileProvider",
    "PayloadProvider",
    "get_provider",
]
