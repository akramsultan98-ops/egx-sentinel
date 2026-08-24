"""Operator command line for the deterministic engine.

Three verbs, deliberately small:

``load-universe``
    Upsert the operator-verified Telda universe from CSV.
``ingest``
    Pull daily bars from the configured provider and store them.
``scan``
    Run the full decision flow for every tradeable instrument and print the
    result as JSON.

This is the surface an orchestrator will eventually call. It is a CLI rather
than a service because nothing yet needs to call it over a network, and a
process that can only be run deliberately is a smaller blast radius than one
that is always listening.

Every command prints JSON to stdout and returns a process exit code. Decimals
are printed as strings: rendering a price through a JSON float would reintroduce
exactly the rounding error the engine works to avoid.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Sequence

from .config import DEFAULT_RISK_POLICY, RiskPolicy
from .db.connection import connect
from .db.errors import PersistenceError
from .db.repository import Repository
from .decide import DecideError, decide, json_default, parse_request_json
from .levels import ATR_PERIOD, derive_levels
from .liquidity import LiquidityGate, TradedValueLiquidityGate
from .pipeline import evaluate_and_persist
from .provider import MarketDataError, MarketDataProvider
from .providers import get_provider
from .settings import SettingsError, load_settings
from .universe import UniverseError, load_universe_csv

# The seed universe ships as package data for the same reason the migrations do:
# a path relative to the repository root is not something an installed package
# can resolve. Operators override it with `--file`.
UNIVERSE_DIR_NAME = "data"
UNIVERSE_FILENAME = "telda-universe.csv"

# How much history to request by default. Comfortably more than ATR needs, so
# holidays and suspended sessions cannot silently starve the calculation.
DEFAULT_HISTORY_DAYS = 400

NO_MARKET_DATA = "NO_MARKET_DATA"
PROVIDER_UNHEALTHY = "PROVIDER_UNHEALTHY"


def default_universe_file() -> Path:
    """Locate the seed universe shipped with this package.

    Depends on nothing above the package, so it resolves identically however
    ``egx_engine`` was installed.
    """
    try:
        package_root = Path(str(resources.files("egx_engine")))
    except (ModuleNotFoundError, TypeError) as exc:  # pragma: no cover - defensive
        raise UniverseError(f"could not locate the egx_engine package: {exc}") from exc

    path = package_root / UNIVERSE_DIR_NAME / UNIVERSE_FILENAME
    if not path.is_file():
        raise UniverseError(
            f"the seed universe is missing from the installed package: expected "
            f"{path}. The distribution was built without its package data "
            f"(see [tool.setuptools.package-data] in pyproject.toml)."
        )
    return path


# Decimals and datetimes become strings, never floats — shared with the HTTP
# shim so both transports render a price identically.
_encode = json_default


def _emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=_encode, sort_keys=True))


# --- commands ------------------------------------------------------------


def load_universe_command(conn, path: str | Path, *, source: str = "operator") -> dict:
    """Load the operator's verified universe file into ``instruments``."""
    entries = load_universe_csv(path)
    repo = Repository(conn)
    loaded = repo.load_universe(entries, source=source)
    conn.commit()

    available = [e.ticker for e in entries if e.telda_available]
    return {
        "command": "load-universe",
        "file": str(path),
        "loaded": loaded,
        "telda_available": len(available),
        "telda_available_tickers": sorted(available),
    }


def ingest_command(
    conn,
    provider: MarketDataProvider,
    *,
    tickers: Sequence[str] | None = None,
    days: int = DEFAULT_HISTORY_DAYS,
    today: date | None = None,
) -> dict:
    """Fetch and store daily bars.

    Defaults to every registered instrument, not just the tradeable ones:
    history is a market fact, and storing it does not imply the instrument may
    be bought.
    """
    repo = Repository(conn)
    end = today or datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)

    targets = _resolve_targets(repo, tickers, telda_available=None)

    results: list[dict] = []
    for instrument in targets:
        try:
            bars = provider.daily_bars(instrument["ticker"], start, end)
            stored = repo.save_daily_bars(instrument["instrument_id"], bars)
            conn.commit()
            results.append(
                {"ticker": instrument["ticker"], "bars": stored, "error": None}
            )
        except (MarketDataError, PersistenceError) as exc:
            conn.rollback()
            results.append(
                {
                    "ticker": instrument["ticker"],
                    "bars": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    return {
        "command": "ingest",
        "provider": provider.name,
        "start": start,
        "end": end,
        "results": results,
    }


def scan_command(
    conn,
    provider: MarketDataProvider,
    *,
    portfolio_id: int,
    tickers: Sequence[str] | None = None,
    risk_policy: RiskPolicy = DEFAULT_RISK_POLICY,
    liquidity_gate: LiquidityGate | None = None,
    now: datetime | None = None,
) -> dict:
    """Run the decision flow across the tradeable universe."""
    repo = Repository(conn)
    gate = liquidity_gate if liquidity_gate is not None else TradedValueLiquidityGate()

    if not provider.health():
        return {
            "command": "scan",
            "provider": provider.name,
            "portfolio_id": portfolio_id,
            "reason": PROVIDER_UNHEALTHY,
            "decisions": [],
        }

    targets = _resolve_targets(repo, tickers, telda_available=True)

    quotes: dict[str, Any] = {}
    if targets:
        for quote in provider.snapshot([t["ticker"] for t in targets]):
            quotes[quote.ticker.strip().upper()] = quote

    decisions: list[dict] = []
    for instrument in targets:
        ticker = instrument["ticker"]
        snapshot = quotes.get(ticker.strip().upper())

        if snapshot is None:
            # Nothing to validate and nothing to record: without a snapshot
            # there is no decision, only an absence.
            decisions.append(
                {
                    "ticker": ticker,
                    "action": "NO_TRADE",
                    "reason": NO_MARKET_DATA,
                    "persisted": False,
                    "is_actionable": False,
                }
            )
            continue

        bars = repo.get_daily_bars(
            instrument["instrument_id"],
            source=provider.name,
            limit=ATR_PERIOD + 1,
        )
        levels = derive_levels(snapshot.last_price, bars, policy=risk_policy)

        record = evaluate_and_persist(
            conn,
            snapshot,
            stop_loss=levels.stop_loss,
            target=levels.target,
            levels_reason=None if levels.ok else levels.reason,
            portfolio_id=portfolio_id,
            risk_policy=risk_policy,
            liquidity_gate=gate,
            now=now,
        )

        decisions.append(_describe(record, levels))

    return {
        "command": "scan",
        "provider": provider.name,
        "portfolio_id": portfolio_id,
        "liquidity_gate": getattr(gate, "name", type(gate).__name__),
        "decisions": decisions,
    }


def decide_command(conn, request_text: str) -> dict:
    """Decide from a JSON request. The transport-independent MVP entry point.

    The HTTP shim calls :func:`egx_engine.decide.decide` with the same parsed
    payload, so piping a file through the CLI and posting it over HTTP produce
    byte-identical decisions.
    """
    return decide(conn, parse_request_json(request_text))


def _resolve_targets(
    repo: Repository,
    tickers: Sequence[str] | None,
    *,
    telda_available: bool | None,
) -> list[dict]:
    """Pick the instruments a command should act on.

    An explicit ``--ticker`` still has to be registered; the CLI will not
    conjure an instrument that the universe file never verified.
    """
    universe = repo.get_universe(telda_available=telda_available)
    if tickers is None:
        return universe

    wanted = [t.strip().upper() for t in tickers]
    by_ticker = {row["ticker"].strip().upper(): row for row in repo.get_universe()}

    missing = [t for t in wanted if t not in by_ticker]
    if missing:
        raise UniverseError(
            f"not registered in the instrument universe: {', '.join(missing)}"
        )
    return [by_ticker[t] for t in wanted]


def _describe(record, levels) -> dict:
    plan = record.plan
    return {
        "ticker": plan.ticker,
        "action": plan.action,
        "reason": plan.reason,
        "persisted": record.persisted,
        "is_actionable": record.is_actionable,
        "shares": plan.shares,
        "entry": plan.entry,
        "stop_loss": plan.stop_loss,
        "target": plan.target,
        "position_value_egp": plan.position_value_egp,
        "risk_egp": plan.risk_egp,
        "reward_egp": plan.reward_egp,
        "risk_reward": plan.risk_reward,
        "atr": levels.atr,
        "snapshot_source": plan.snapshot_source,
        "snapshot_timestamp_utc": plan.snapshot_timestamp_utc,
        "risk_plan_id": record.risk_plan_id,
        "error": record.error,
    }


# --- argument parsing ----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="egx",
        description="EGX Sentinel deterministic engine (analysis only, no execution).",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    universe = subcommands.add_parser(
        "load-universe", help="load the operator-verified Telda universe CSV"
    )
    universe.add_argument(
        "--file", default=None, help="path to the universe CSV (default: repo copy)"
    )

    ingest = subcommands.add_parser("ingest", help="fetch and store daily bars")
    ingest.add_argument("--ticker", action="append", dest="tickers", default=None)
    ingest.add_argument("--days", type=int, default=DEFAULT_HISTORY_DAYS)

    scan = subcommands.add_parser("scan", help="run the decision flow")
    scan.add_argument("--ticker", action="append", dest="tickers", default=None)
    scan.add_argument(
        "--portfolio-id",
        type=int,
        default=None,
        help="overrides EGX_PORTFOLIO_ID",
    )

    decide_parser = subcommands.add_parser(
        "decide",
        help="decide from a JSON request on stdin (quotes + optional research)",
    )
    decide_parser.add_argument(
        "--file",
        default=None,
        help="read the request from a file instead of stdin",
    )

    subcommands.add_parser(
        "serve", help="run the internal HTTP endpoint (requires SENTINEL_API_TOKEN)"
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = load_settings()

        if args.command == "load-universe":
            path = Path(args.file) if args.file else default_universe_file()
            with connect() as conn:
                _emit(load_universe_command(conn, path))
            return 0

        if args.command == "decide":
            text = (
                Path(args.file).read_text(encoding="utf-8")
                if args.file
                else sys.stdin.read()
            )
            with connect() as conn:
                _emit(decide_command(conn, text))
            return 0

        if args.command == "serve":
            from .server import serve

            return serve(settings)

        provider = get_provider(settings)

        if args.command == "ingest":
            with connect() as conn:
                _emit(ingest_command(conn, provider, tickers=args.tickers, days=args.days))
            return 0

        if args.command == "scan":
            portfolio_id = (
                args.portfolio_id
                if args.portfolio_id is not None
                else settings.require_portfolio_id()
            )
            with connect() as conn:
                _emit(
                    scan_command(
                        conn, provider, portfolio_id=portfolio_id, tickers=args.tickers
                    )
                )
            return 0

    except (
        SettingsError,
        UniverseError,
        PersistenceError,
        MarketDataError,
        DecideError,
    ) as exc:
        # Every one of these is a safe failure: nothing was decided.
        _emit({"error": f"{type(exc).__name__}: {exc}"})
        return 1

    return 1  # pragma: no cover - argparse rejects unknown commands first


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
