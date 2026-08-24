"""The MVP decide contract.

The tests that matter most here are the ones proving the AI cannot reach a
number. Everything else is input validation.
"""

import json
from decimal import Decimal

import pytest

from egx_engine.db.repository import Repository
from egx_engine.decide import (
    NEXT_SESSION_FRESHNESS_SECONDS,
    SCHEMA_VERSION,
    DecideError,
    assert_research_is_qualitative,
    decide,
    parse_request_json,
)

from conftest import NOW, make_bars, make_snapshot

pytestmark = pytest.mark.integration

SOURCE = "google_sheet"

NUMERIC_FIELDS = (
    "entry",
    "stop_loss",
    "target",
    "shares",
    "risk_egp",
    "reward_egp",
    "risk_reward",
    "position_value_egp",
    "atr",
)


def quote(source: str = SOURCE, **overrides) -> dict:
    snapshot = make_snapshot(source=source, **overrides)
    return json.loads(snapshot.model_dump_json())


def bars(count: int = 20, source: str = SOURCE, **overrides) -> list[dict]:
    return [
        json.loads(bar.model_dump_json())
        for bar in make_bars(count, source=source, **overrides)
    ]


def request(portfolio_id: int, *, research=None, **overrides) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": "next_session",
        "portfolio_id": portfolio_id,
        "quotes": [quote()],
        "bars": {"TEST": bars()},
    }
    if research is not None:
        payload["research"] = research
    payload.update(overrides)
    return payload


def research_for(ticker="TEST", **overrides) -> dict:
    entry = {
        "ticker": ticker,
        "action": "BUY_CANDIDATE",
        "confidence": 0.82,
        "thesis": "Loan growth and a widening margin; catalyst is the Q3 print.",
        "catalysts": ["Q3 results"],
        "risks": ["EGP volatility"],
        "sources": ["https://example.com/report"],
    }
    entry.update(overrides)
    return {"model": "openrouter/some-model-v1", "analysis": [entry]}


def run(conn, payload):
    return decide(conn, payload, now=NOW)


# --- the happy path -------------------------------------------------------


def test_decide_produces_a_persisted_buy(conn, portfolio_id):
    result = run(conn, request(portfolio_id, research=research_for()))

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["mode"] == "next_session"
    assert result["freshness_limit_seconds"] == NEXT_SESSION_FRESHNESS_SECONDS
    assert result["summary"] == {
        "evaluated": 1,
        "buy_count": 1,
        "no_trade_count": 0,
        "contains_test_data": False,
    }

    decision = result["decisions"][0]
    assert decision["action"] == "BUY"
    assert decision["is_actionable"] is True
    assert decision["shares"] == 150
    assert decision["entry"] == Decimal("10")
    assert decision["stop_loss"] == Decimal("9.600")
    assert decision["target"] == Decimal("10.951")
    assert decision["snapshot_source"] == SOURCE
    assert decision["data_is_test"] is False
    assert decision["risk_plan_id"] is not None


def test_engine_numbers_are_computed_not_supplied(conn, portfolio_id):
    """Sizing comes from equity and ATR, never from the request."""
    result = run(conn, request(portfolio_id))
    decision = result["decisions"][0]

    # 1.5% of EGP 5,000 equity, fee-aware, is the binding budget.
    assert decision["risk_egp"] <= Decimal("75")
    assert decision["risk_reward"] >= Decimal("2")
    assert decision["risk_percent"] < Decimal("1.5")


# --- the boundary that matters --------------------------------------------


def test_research_cannot_change_any_number(conn, portfolio_id):
    """The whole safety claim, as one assertion.

    Identical market data, once with research and once without. Every numeric
    output must be byte-identical: research is read only after the decision
    exists.
    """
    without = run(conn, request(portfolio_id))["decisions"][0]
    with_research = run(
        conn,
        request(
            portfolio_id,
            research=research_for(
                confidence=0.99,
                thesis="Extremely strong conviction, enormous upside, buy aggressively.",
            ),
        ),
    )["decisions"][0]

    for field in NUMERIC_FIELDS:
        assert without[field] == with_research[field], field
    assert without["action"] == with_research["action"]
    assert without["reason"] == with_research["reason"]


def test_ai_buy_cannot_override_a_sentinel_no_trade(conn, portfolio_id, repo):
    """AI says BUY at 99% confidence; the Telda gate says no. NO_TRADE wins."""
    repo.upsert_instrument(
        instrument_id="TEST", ticker="TEST", name="Test Instrument",
        source="fixture", source_updated_at=NOW, telda_available=False,
    )
    conn.commit()

    result = run(
        conn,
        request(
            portfolio_id,
            research=research_for(action="BUY_CANDIDATE", confidence=1.0),
        ),
    )

    decision = result["decisions"][0]
    assert decision["action"] == "NO_TRADE"
    assert decision["reason"] == "NOT_IN_TELDA_UNIVERSE"
    assert decision["is_actionable"] is False
    assert decision["shares"] == 0
    assert result["summary"]["buy_count"] == 0


@pytest.mark.parametrize(
    "field",
    ["entry", "last_price", "stop_loss", "target", "shares", "risk",
     "position_size", "portfolio_value", "atr", "take_profit", "quantity"],
)
def test_price_and_size_fields_are_refused(conn, portfolio_id, field):
    payload = request(portfolio_id, research=research_for(**{field: 12.34}))
    with pytest.raises(DecideError, match="may not supply trade numbers"):
        run(conn, payload)


def test_forbidden_field_is_caught_at_any_depth():
    with pytest.raises(DecideError, match="may not supply trade numbers"):
        assert_research_is_qualitative(
            {"analysis": [{"ticker": "COMI", "detail": {"levels": {"stop_loss": 79.8}}}]}
        )


def test_key_matching_ignores_case_and_separators():
    for variant in ("Stop_Loss", "STOPLOSS", "stop-loss", "Position Size"):
        with pytest.raises(DecideError):
            assert_research_is_qualitative({variant: 1})


def test_legitimate_research_fields_are_allowed():
    """'risks' must not be confused with the forbidden 'risk'."""
    assert_research_is_qualitative(
        {
            "model": "x",
            "analysis": [
                {"ticker": "COMI", "action": "BUY_CANDIDATE", "confidence": 0.8,
                 "thesis": "entry looks attractive near 82", "catalysts": [],
                 "risks": ["FX"], "sources": ["https://example.com"]}
            ],
        }
    )


def test_a_price_mentioned_in_prose_is_harmless(conn, portfolio_id):
    """Text may say anything; it never becomes a number."""
    result = run(
        conn,
        request(
            portfolio_id,
            research=research_for(thesis="I would enter at 999 with a stop at 1."),
        ),
    )
    decision = result["decisions"][0]
    assert decision["entry"] == Decimal("10")
    assert decision["stop_loss"] == Decimal("9.600")


# --- signal persistence ---------------------------------------------------


def test_research_is_linked_to_the_risk_plan(conn, portfolio_id):
    result = run(conn, request(portfolio_id, research=research_for()))
    decision = result["decisions"][0]

    assert decision["signal_id"] is not None
    signal = Repository(conn).get_signal(decision["signal_id"])

    assert signal["risk_plan_id"] == decision["risk_plan_id"]
    assert signal["model"] == "openrouter/some-model-v1"
    assert signal["confidence"] == Decimal("82.00")  # stored as percent
    assert signal["thesis"].startswith("Loan growth")
    assert signal["action"] == "BUY"  # the engine's verdict, not the model's
    assert signal["status"] == "ACTIONABLE"
    assert signal["data_snapshot_id"] is not None


def test_a_rejected_decision_still_records_its_research(conn, portfolio_id, repo):
    repo.upsert_instrument(
        instrument_id="TEST", ticker="TEST", name="Test Instrument",
        source="fixture", source_updated_at=NOW, telda_available=False,
    )
    conn.commit()

    decision = run(conn, request(portfolio_id, research=research_for()))["decisions"][0]
    signal = Repository(conn).get_signal(decision["signal_id"])

    assert signal["action"] == "NO_TRADE"
    assert signal["status"] == "REJECTED"


def test_no_research_means_no_signal(conn, portfolio_id):
    decision = run(conn, request(portfolio_id))["decisions"][0]
    assert decision["signal_id"] is None
    assert decision["research"] is None


# --- test-data labelling --------------------------------------------------


def test_manual_data_is_flagged(conn, portfolio_id):
    payload = request(
        portfolio_id,
        quotes=[quote(source="manual")],
        bars={"TEST": bars(source="manual")},
    )
    result = run(conn, payload)

    assert result["decisions"][0]["data_is_test"] is True
    assert result["summary"]["contains_test_data"] is True


def test_google_sheet_data_is_not_flagged_as_test(conn, portfolio_id):
    assert run(conn, request(portfolio_id))["decisions"][0]["data_is_test"] is False


# --- freshness ------------------------------------------------------------


def test_intraday_mode_rejects_an_end_of_day_close(conn, portfolio_id):
    """The stale-data rule is not relaxed; the caller picks which rule applies."""
    stale = quote(freshness_seconds=20 * 3600)
    payload = request(portfolio_id, mode="intraday", quotes=[stale])

    decision = run(conn, payload)["decisions"][0]
    assert decision["action"] == "NO_TRADE"
    assert decision["reason"] == "DATA_NOT_VERIFIED_NO_TRADE"


def test_dishonest_freshness_is_refused_even_in_next_session_mode(conn, portfolio_id):
    """Claiming '0 seconds old' for yesterday's close is INVALID, not stale."""
    from datetime import timedelta

    liar = quote(freshness_seconds=0, source_timestamp=(NOW - timedelta(hours=20)))
    decision = run(conn, request(portfolio_id, quotes=[liar]))["decisions"][0]

    assert decision["action"] == "NO_TRADE"
    assert decision["reason"] == "DATA_NOT_VERIFIED_NO_TRADE"

    trail = Repository(conn).get_decision_audit_trail(decision["risk_plan_id"])
    assert "FRESHNESS_MISREPORTED" in trail["validation"]["reasons"]


def test_the_applied_freshness_limit_is_audited(conn, portfolio_id):
    decision = run(conn, request(portfolio_id))["decisions"][0]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT v.max_freshness_seconds FROM risk_plans r "
            "JOIN validation_results v USING (validation_result_id) "
            "WHERE r.risk_plan_id = %s",
            (decision["risk_plan_id"],),
        )
        assert cur.fetchone()[0] == NEXT_SESSION_FRESHNESS_SECONDS


# --- malformed input ------------------------------------------------------


def test_wrong_schema_version_is_refused(conn, portfolio_id):
    with pytest.raises(DecideError, match="unsupported schema_version"):
        run(conn, request(portfolio_id, schema_version="9.9"))


def test_unknown_mode_is_refused(conn, portfolio_id):
    with pytest.raises(DecideError, match="unknown mode"):
        run(conn, request(portfolio_id, mode="realtime"))


def test_missing_quotes_are_refused(conn, portfolio_id):
    payload = request(portfolio_id)
    del payload["quotes"]
    with pytest.raises(DecideError, match="missing required field 'quotes'"):
        run(conn, payload)


def test_empty_quotes_are_refused(conn, portfolio_id):
    with pytest.raises(DecideError, match="non-empty"):
        run(conn, request(portfolio_id, quotes=[]))


def test_a_malformed_quote_is_refused(conn, portfolio_id):
    bad = quote()
    bad["last_price"] = "-5"
    with pytest.raises(DecideError, match="not a usable quote"):
        run(conn, request(portfolio_id, quotes=[bad]))


def test_non_integer_portfolio_id_is_refused(conn):
    with pytest.raises(DecideError, match="portfolio_id must be an integer"):
        run(conn, request("not-a-number"))


@pytest.mark.parametrize("bad", ["a string", 42, ["a list"]])
def test_research_must_be_an_object(conn, portfolio_id, bad):
    with pytest.raises(DecideError, match="'research' must be a JSON object"):
        run(conn, request(portfolio_id, research=bad))


def test_analysis_must_be_a_list(conn, portfolio_id):
    with pytest.raises(DecideError, match="analysis must be a JSON array"):
        run(conn, request(portfolio_id, research={"model": "x", "analysis": {}}))


def test_analysis_entry_needs_a_ticker(conn, portfolio_id):
    with pytest.raises(DecideError, match="missing a ticker"):
        run(conn, request(portfolio_id, research={"analysis": [{"thesis": "x"}]}))


@pytest.mark.parametrize("value", [1.5, -0.1, "high"])
def test_bad_confidence_is_refused(conn, portfolio_id, value):
    with pytest.raises(DecideError):
        run(conn, request(portfolio_id, research=research_for(confidence=value)))


def test_malformed_json_is_refused():
    with pytest.raises(DecideError, match="not valid JSON"):
        parse_request_json("{not json")


def test_a_json_array_body_is_refused():
    with pytest.raises(DecideError, match="must be a JSON object"):
        parse_request_json("[1, 2, 3]")


def test_prices_survive_json_parsing_exactly():
    payload = parse_request_json('{"p": 82.55}')
    assert payload["p"] == Decimal("82.55")


# --- multiple candidates --------------------------------------------------


def test_each_quote_is_decided_independently(conn, portfolio_id, repo):
    repo.upsert_instrument(
        instrument_id="OTHER", ticker="OTHER", name="Other",
        source="fixture", source_updated_at=NOW,
        telda_available=True, telda_verified_at=NOW,
    )
    conn.commit()

    payload = request(
        portfolio_id,
        quotes=[quote(), quote(instrument_id="OTHER", ticker="OTHER")],
        bars={"TEST": bars()},  # OTHER has no history
    )
    result = run(conn, payload)

    by_ticker = {d["ticker"]: d for d in result["decisions"]}
    assert by_ticker["TEST"]["action"] == "BUY"
    assert by_ticker["OTHER"]["reason"] == "INSUFFICIENT_HISTORY"
    assert result["summary"] == {
        "evaluated": 2,
        "buy_count": 1,
        "no_trade_count": 1,
        "contains_test_data": False,
    }
