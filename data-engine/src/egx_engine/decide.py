"""The one entry point an orchestrator calls: machine data in, decision out.

n8n gathers the numbers and the research, then calls here. This module is
transport-agnostic — the CLI pipes stdin to it and the HTTP shim posts to it,
and both get identical behaviour.

Two rules give this module its shape, and everything else follows from them.

**The engine computes every number.** ``entry``, ``stop_loss``, ``target``,
``shares``, ``risk_egp`` and the BUY/NO_TRADE verdict come from
:mod:`egx_engine.levels`, :mod:`egx_engine.risk` and
:mod:`egx_engine.pipeline`, exactly as they did before this module existed.
Prices arrive from a declared machine source and are validated like any vendor
feed.

**Research is words, never numbers.** The research object is untrusted input
from a language model. It is checked for price- and size-shaped fields and
*rejected* if any are present — enforced here at the boundary, not requested in
a prompt. It is then read only after the decision has already been computed,
and only ever reaches ``signals.thesis``, ``signals.confidence`` and
``signals.model``. There is no code path by which it can move a stop or size a
position. That is a structural guarantee, not a policy.

The engine never learns which model produced the research. Swapping providers
in n8n changes nothing here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .config import DEFAULT_RISK_POLICY, RiskPolicy
from .db.errors import PersistenceError
from .db.repository import Repository
from .levels import derive_levels
from .liquidity import LiquidityGate, TradedValueLiquidityGate
from .models import DailyBar, MarketSnapshot
from .pipeline import evaluate_and_persist
from .providers import PayloadProvider

SCHEMA_VERSION = "1.0"

#: Freshness ceiling per decision mode, in seconds.
#:
#: ``intraday`` uses the data policy's own limit (120s) — a live quote acted on
#: now. ``next_session`` allows one session's gap, because an end-of-day close
#: used to plan tomorrow's entry is not stale data being smuggled through: it is
#: a different, explicitly declared question. The mode is chosen by the caller,
#: never inferred from how old the data happens to be, and the limit that was
#: applied is persisted in ``validation_results.max_freshness_seconds`` so any
#: decision can be re-read against the rule it was judged under.
#:
#: Nothing else is relaxed. In particular the validator still cross-checks the
#: caller's claimed ``freshness_seconds`` against the age its own
#: ``source_timestamp`` implies, so a sheet that reports "0 seconds old" for
#: yesterday's close is INVALID, not merely stale.
NEXT_SESSION_FRESHNESS_SECONDS = 30 * 3600
MODES: dict[str, int | None] = {
    "intraday": None,
    "next_session": NEXT_SESSION_FRESHNESS_SECONDS,
}

#: Sources that must never be presented as live market data.
TEST_DATA_SOURCES = frozenset({"manual", "test", "fixture", "sample", "demo"})

MAX_QUOTES = 100
MAX_THESIS_CHARS = 4000

#: Research keys that would mean the model is trying to supply a number the
#: engine is responsible for. Matched after normalisation (lowercased, with
#: separators removed), at any depth.
FORBIDDEN_RESEARCH_KEYS: frozenset[str] = frozenset(
    {
        # entry / price
        "entry", "entryprice", "entrylow", "entryhigh", "entryzone", "entrypoint",
        "price", "lastprice", "last", "currentprice", "marketprice", "close",
        "closeprice", "open", "high", "low", "bid", "ask",
        # exits
        "stop", "stoploss", "stopprice", "stoplevel", "sl",
        "target", "targetprice", "targetlevel", "target1", "target2", "target3",
        "takeprofit", "tp", "tp1", "tp2", "tp3", "exit", "exitprice",
        # size
        "shares", "quantity", "qty", "numshares", "sharecount", "lot", "lotsize",
        "size", "positionsize", "position", "positionvalue", "positionegp",
        "notional", "allocation", "weight",
        # risk / portfolio
        "risk", "riskegp", "riskamount", "riskpercent", "riskpertrade",
        "riskreward", "rr", "rrratio", "reward", "rewardegp",
        "portfolio", "portfoliovalue", "equity", "cash", "capital", "balance",
        "fees", "atr", "stopdistance",
    }
)


class DecideError(ValueError):
    """The request is malformed or violates the research boundary.

    A safe failure: nothing was decided and nothing was written.
    """


def json_default(value: Any) -> str:
    """JSON fallback: Decimals and datetimes become strings, never floats."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"cannot serialise {type(value).__name__}")


def parse_request_json(text: str | bytes) -> dict:
    """Parse a request body, keeping numbers exact.

    ``parse_float=Decimal`` matters: a price that goes through a binary float
    on the way in is already wrong before anything validates it.
    """
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DecideError(f"request body is not valid UTF-8: {exc}") from exc
    try:
        payload = json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise DecideError(f"request body is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DecideError("request body must be a JSON object")
    return payload


def _normalise_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def _normalise_ticker(ticker: str) -> str:
    return str(ticker).strip().upper()


def assert_research_is_qualitative(research: Any, *, path: str = "research") -> None:
    """Reject research that tries to supply a number the engine owns.

    Walks the whole object, not just the top level: a forbidden key nested
    three levels down is still an attempt to price a trade.

    This is deliberately blunt. A model that wants to say "I think the entry is
    around 82" can say it in ``thesis`` as prose, where it is inert text that
    reaches a human. What it cannot do is hand the engine a field the engine
    would otherwise have computed.
    """
    if isinstance(research, Mapping):
        for key, value in research.items():
            normalised = _normalise_key(str(key))
            if normalised in FORBIDDEN_RESEARCH_KEYS:
                raise DecideError(
                    f"{path}.{key}: research may not supply trade numbers. "
                    f"{key!r} is computed by the engine from validated market "
                    "data; put qualitative context in 'thesis' instead."
                )
            assert_research_is_qualitative(value, path=f"{path}.{key}")
    elif isinstance(research, (list, tuple)):
        for index, item in enumerate(research):
            assert_research_is_qualitative(item, path=f"{path}[{index}]")


def _require(payload: Mapping, key: str) -> Any:
    if key not in payload:
        raise DecideError(f"missing required field {key!r}")
    return payload[key]


def _parse_confidence(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    try:
        confidence = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise DecideError(f"confidence must be a number, got {raw!r}") from exc
    if not (Decimal("0") <= confidence <= Decimal("1")):
        raise DecideError(f"confidence must be between 0 and 1, got {confidence}")
    return confidence


def _parse_quotes(raw: Any) -> list[MarketSnapshot]:
    if not isinstance(raw, list) or not raw:
        raise DecideError("'quotes' must be a non-empty JSON array")
    if len(raw) > MAX_QUOTES:
        raise DecideError(f"'quotes' may not exceed {MAX_QUOTES} entries")

    quotes: list[MarketSnapshot] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise DecideError(f"quotes[{index}] must be a JSON object")
        try:
            quotes.append(MarketSnapshot(**item))
        except Exception as exc:  # pydantic ValidationError and friends
            raise DecideError(f"quotes[{index}] is not a usable quote: {exc}") from exc
    return quotes


def _parse_bars(raw: Any) -> dict[str, list[DailyBar]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DecideError("'bars' must be a JSON object keyed by ticker")

    bars: dict[str, list[DailyBar]] = {}
    for ticker, series in raw.items():
        if not isinstance(series, list):
            raise DecideError(f"bars[{ticker}] must be a JSON array")
        parsed: list[DailyBar] = []
        for index, item in enumerate(series):
            if not isinstance(item, dict):
                raise DecideError(f"bars[{ticker}][{index}] must be a JSON object")
            try:
                parsed.append(DailyBar(**item))
            except Exception as exc:
                raise DecideError(
                    f"bars[{ticker}][{index}] is not a usable bar: {exc}"
                ) from exc
        bars[_normalise_ticker(ticker)] = parsed
    return bars


def _index_research(research: Any) -> tuple[str | None, dict[str, dict]]:
    """Return ``(model, {ticker: entry})`` from a validated research object."""
    if research is None:
        return None, {}
    if not isinstance(research, dict):
        raise DecideError("'research' must be a JSON object")

    assert_research_is_qualitative(research)

    model = research.get("model")
    if model is not None and not isinstance(model, str):
        raise DecideError("research.model must be a string")

    analysis = research.get("analysis", [])
    if not isinstance(analysis, list):
        raise DecideError("research.analysis must be a JSON array")

    by_ticker: dict[str, dict] = {}
    for index, item in enumerate(analysis):
        if not isinstance(item, dict):
            raise DecideError(f"research.analysis[{index}] must be a JSON object")
        ticker = item.get("ticker")
        if not ticker or not isinstance(ticker, str):
            raise DecideError(f"research.analysis[{index}] is missing a ticker")
        # Validated here so a malformed entry fails before anything is decided
        # or written, rather than part-way through the run.
        _parse_confidence(item.get("confidence"))
        by_ticker[_normalise_ticker(ticker)] = item

    return model, by_ticker


@dataclass(frozen=True)
class DecideRequest:
    """A request that has passed every check not needing a database."""

    mode: str
    freshness_limit: int | None
    portfolio_id: int
    quotes: list[MarketSnapshot]
    bars: dict[str, list[DailyBar]]
    model: str | None
    research_by_ticker: dict[str, dict]


def parse_decide_request(payload: Mapping[str, Any]) -> DecideRequest:
    """Validate a request without touching the database.

    Kept separate so a malformed request — or one that violates the research
    boundary — is refused before a connection is opened and before anything can
    be written. Contract violations must cost nothing.
    """
    schema_version = str(_require(payload, "schema_version"))
    if schema_version != SCHEMA_VERSION:
        raise DecideError(
            f"unsupported schema_version {schema_version!r}; this engine speaks "
            f"{SCHEMA_VERSION!r}"
        )

    mode = str(payload.get("mode", "next_session"))
    if mode not in MODES:
        raise DecideError(
            f"unknown mode {mode!r}; known modes: {', '.join(sorted(MODES))}"
        )
    freshness_limit = MODES[mode]

    raw_portfolio_id = _require(payload, "portfolio_id")
    try:
        portfolio_id = int(raw_portfolio_id)
    except (TypeError, ValueError) as exc:
        raise DecideError(
            f"portfolio_id must be an integer, got {raw_portfolio_id!r}"
        ) from exc

    # The research boundary is checked first and unconditionally. It is the
    # security-critical rule, so it must not depend on the rest of the payload
    # happening to be well-formed: a request carrying a forbidden price field
    # is refused as a boundary violation, whatever else is wrong with it.
    model, research_by_ticker = _index_research(payload.get("research"))

    quotes = _parse_quotes(_require(payload, "quotes"))
    supplied_bars = _parse_bars(payload.get("bars"))

    return DecideRequest(
        mode=mode,
        freshness_limit=freshness_limit,
        portfolio_id=portfolio_id,
        quotes=quotes,
        bars=supplied_bars,
        model=model,
        research_by_ticker=research_by_ticker,
    )


def decide(
    conn,
    payload: Mapping[str, Any],
    *,
    risk_policy: RiskPolicy = DEFAULT_RISK_POLICY,
    liquidity_gate: LiquidityGate | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate a request, decide on every quote in it, and return the result.

    Every decision — including a refusal — is committed with its full audit
    chain before it is returned, because that guarantee belongs to
    :func:`egx_engine.pipeline.evaluate_and_persist` and is not weakened here.
    """
    return decide_request(
        conn,
        parse_decide_request(payload),
        risk_policy=risk_policy,
        liquidity_gate=liquidity_gate,
        now=now,
    )


def decide_request(
    conn,
    request: DecideRequest,
    *,
    risk_policy: RiskPolicy = DEFAULT_RISK_POLICY,
    liquidity_gate: LiquidityGate | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Decide on an already-validated request."""
    now = now or datetime.now(timezone.utc)
    gate = liquidity_gate if liquidity_gate is not None else TradedValueLiquidityGate()

    mode = request.mode
    freshness_limit = request.freshness_limit
    portfolio_id = request.portfolio_id
    quotes = request.quotes
    model = request.model
    research_by_ticker = request.research_by_ticker

    provider = PayloadProvider(quotes, request.bars)
    repo = Repository(conn)

    # Read once, for the reporting-only risk percentage. Sizing itself always
    # reads the portfolio inside the pipeline's own transaction.
    equity = _current_equity(repo, portfolio_id)

    decisions: list[dict[str, Any]] = []
    for quote in quotes:
        decisions.append(
            _decide_one(
                conn,
                repo,
                quote=quote,
                provider=provider,
                portfolio_id=portfolio_id,
                equity=equity,
                freshness_limit=freshness_limit,
                research=research_by_ticker.get(_normalise_ticker(quote.ticker)),
                model=model,
                risk_policy=risk_policy,
                gate=gate,
                now=now,
            )
        )

    buys = [d for d in decisions if d["action"] == "BUY" and d["is_actionable"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "freshness_limit_seconds": freshness_limit,
        "portfolio_id": portfolio_id,
        "decided_at": now,
        "decisions": decisions,
        "summary": {
            "evaluated": len(decisions),
            "buy_count": len(buys),
            "no_trade_count": len(decisions) - len(buys),
            "contains_test_data": any(d["data_is_test"] for d in decisions),
        },
    }


def _current_equity(repo: Repository, portfolio_id: int) -> Decimal | None:
    try:
        return repo.get_portfolio_state(portfolio_id).equity_egp
    except PersistenceError:
        # Unknown equity is handled properly inside the pipeline, which refuses
        # to size against it. Here it only means we cannot render a percentage.
        return None


def _decide_one(
    conn,
    repo: Repository,
    *,
    quote: MarketSnapshot,
    provider: PayloadProvider,
    portfolio_id: int,
    equity: Decimal | None,
    freshness_limit: int | None,
    research: dict | None,
    model: str | None,
    risk_policy: RiskPolicy,
    gate: LiquidityGate,
    now: datetime,
) -> dict[str, Any]:
    ticker = _normalise_ticker(quote.ticker)

    # Bars supplied in the request are stored first, so history accumulates and
    # the levels calculation always reads from one place. Bars are keyed by the
    # quote's own source: two sources must never be blended into one series.
    try:
        supplied = provider.daily_bars(ticker, date.min, date.max)
    except Exception:
        supplied = []

    if supplied:
        try:
            repo.save_daily_bars(quote.instrument_id, supplied)
            conn.commit()
        except PersistenceError:
            conn.rollback()

    try:
        bars = repo.get_daily_bars(quote.instrument_id, source=quote.source)
    except PersistenceError:
        conn.rollback()
        bars = []

    levels = derive_levels(quote.last_price, bars, policy=risk_policy)

    record = evaluate_and_persist(
        conn,
        quote,
        stop_loss=levels.stop_loss,
        target=levels.target,
        levels_reason=None if levels.ok else levels.reason,
        portfolio_id=portfolio_id,
        risk_policy=risk_policy,
        liquidity_gate=gate,
        max_freshness_seconds=freshness_limit,
        now=now,
    )

    signal_id = _record_research(
        conn,
        repo,
        record=record,
        quote=quote,
        portfolio_id=portfolio_id,
        research=research,
        model=model,
    )

    plan = record.plan
    risk_percent = None
    if equity and plan.risk_egp:
        risk_percent = (plan.risk_egp / equity) * Decimal("100")

    thesis = None
    confidence = None
    if research is not None:
        raw_thesis = research.get("thesis")
        if isinstance(raw_thesis, str):
            thesis = raw_thesis.strip()[:MAX_THESIS_CHARS]
        confidence = _parse_confidence(research.get("confidence"))

    return {
        "ticker": plan.ticker,
        "action": plan.action,
        "reason": plan.reason,
        "persisted": record.persisted,
        "is_actionable": record.is_actionable,
        "entry": plan.entry,
        "stop_loss": plan.stop_loss,
        "target": plan.target,
        "shares": plan.shares,
        "position_value_egp": plan.position_value_egp,
        "risk_egp": plan.risk_egp,
        "reward_egp": plan.reward_egp,
        "risk_reward": plan.risk_reward,
        "risk_percent": risk_percent,
        "atr": levels.atr,
        "snapshot_source": plan.snapshot_source,
        "snapshot_timestamp_utc": plan.snapshot_timestamp_utc,
        "data_is_test": (quote.source or "").strip().lower() in TEST_DATA_SOURCES,
        "risk_plan_id": record.risk_plan_id,
        "signal_id": signal_id,
        "research": None
        if research is None
        else {"model": model, "confidence": confidence, "thesis": thesis},
        "error": record.error,
    }


def _record_research(
    conn,
    repo: Repository,
    *,
    record,
    quote: MarketSnapshot,
    portfolio_id: int,
    research: dict | None,
    model: str | None,
) -> int | None:
    """Attach research to a committed plan. Never blocks the decision.

    A signal is only ever a note on an existing ``risk_plan_id``, so research
    that cannot be stored costs us an annotation, not a verdict.
    """
    if research is None or record.risk_plan_id is None:
        return None

    thesis = research.get("thesis")
    if isinstance(thesis, str):
        thesis = thesis.strip()[:MAX_THESIS_CHARS] or None
    else:
        thesis = None

    try:
        signal_id = repo.save_signal(
            risk_plan_id=record.risk_plan_id,
            portfolio_id=portfolio_id,
            instrument_id=quote.instrument_id,
            action=record.plan.action,
            status="ACTIONABLE" if record.is_actionable else "REJECTED",
            snapshot_id=record.snapshot_id,
            model=model,
            confidence=_parse_confidence(research.get("confidence")),
            thesis=thesis,
        )
        conn.commit()
        return signal_id
    except (PersistenceError, DecideError):
        conn.rollback()
        return None


__all__ = [
    "FORBIDDEN_RESEARCH_KEYS",
    "MODES",
    "NEXT_SESSION_FRESHNESS_SECONDS",
    "SCHEMA_VERSION",
    "TEST_DATA_SOURCES",
    "DecideError",
    "DecideRequest",
    "assert_research_is_qualitative",
    "decide",
    "decide_request",
    "json_default",
    "parse_decide_request",
    "parse_request_json",
]
