"""The HTTP shim: authentication, routing, and refusing oversized input.

Exercised through a real socket against a real server, so the wiring is tested
rather than mocked. Decision logic itself is covered by test_decide.py.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from egx_engine.server import MAX_BODY_BYTES, build_server
from egx_engine.settings import Settings, SettingsError

TOKEN = "test-token-not-a-real-secret"


@pytest.fixture
def server():
    """A live server on an ephemeral port, torn down after each test."""
    httpd = build_server(Settings(api_token=TOKEN, http_host="127.0.0.1", http_port=0))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def call(url, *, method="POST", token=TOKEN, body=b"{}", headers=None):
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# --- startup --------------------------------------------------------------


def test_server_refuses_to_start_without_a_token():
    """An unauthenticated decision endpoint must never come up."""
    with pytest.raises(SettingsError, match="SENTINEL_API_TOKEN"):
        build_server(Settings(api_token=None))


def test_server_refuses_a_blank_token():
    with pytest.raises(SettingsError):
        build_server(Settings(api_token=""))


# --- health ---------------------------------------------------------------


def test_health_needs_no_token(server):
    status, body = call(f"{server}/health", method="GET", token=None, body=None)
    assert status == 200
    assert body["status"] == "ok"


def test_health_reveals_nothing_sensitive(server):
    _, body = call(f"{server}/health", method="GET", token=None, body=None)
    assert set(body) == {"status", "service"}


# --- authentication -------------------------------------------------------


def test_decide_rejects_a_missing_token(server):
    status, body = call(f"{server}/decide", token=None)
    assert status == 401
    assert body["error"] == "unauthorized"


def test_decide_rejects_a_wrong_token(server):
    status, _ = call(f"{server}/decide", token="wrong-token")
    assert status == 401


def test_decide_rejects_a_malformed_authorization_header(server):
    request = urllib.request.Request(f"{server}/decide", data=b"{}", method="POST")
    request.add_header("Authorization", TOKEN)  # no "Bearer " scheme
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 401


def test_unauthorized_response_does_not_say_why(server):
    """A prober must not learn whether the route or the token was wrong."""
    _, missing = call(f"{server}/decide", token=None)
    _, wrong = call(f"{server}/decide", token="wrong-token")
    assert missing == wrong == {"error": "unauthorized"}


# --- routing --------------------------------------------------------------


def test_unknown_post_route_is_404(server):
    status, _ = call(f"{server}/execute-order")
    assert status == 404


def test_unknown_get_route_is_404(server):
    status, _ = call(f"{server}/admin", method="GET", token=None, body=None)
    assert status == 404


def test_there_is_no_order_endpoint(server):
    """This system recommends. It must expose no way to place a trade."""
    for path in ("/order", "/execute", "/buy", "/trade"):
        status, _ = call(f"{server}{path}")
        assert status == 404, path


# --- request body ---------------------------------------------------------


def test_empty_body_is_refused(server):
    status, body = call(f"{server}/decide", body=b"")
    assert status == 400
    assert "empty" in body["error"]


def test_oversized_body_is_refused_by_declared_length(server):
    """A body declared larger than the cap is refused without being read.

    The server answers 413 and closes rather than reading a megabyte it has
    already decided to reject. A client that declared more than it sent may
    therefore see the connection drop instead of reading the 413 — both are
    refusals, and the property under test is that nothing was decided. Which of
    the two the OS delivers is not something worth pinning down.
    """
    try:
        status, body = call(
            f"{server}/decide",
            body=b"{}",
            headers={"Content-Length": str(MAX_BODY_BYTES + 1)},
        )
    except (ConnectionError, urllib.error.URLError, OSError):
        return  # refused by dropping the connection

    assert status == 413
    assert "too large" in body["error"]


def test_malformed_json_is_a_400_not_a_500(server):
    status, body = call(f"{server}/decide", body=b"{not json")
    assert status == 400
    assert "not valid JSON" in body["error"]


def test_a_bad_request_reports_the_contract_violation(server):
    status, body = call(f"{server}/decide", body=json.dumps({"quotes": []}).encode())
    assert status == 400
    assert "schema_version" in body["error"]


def test_research_boundary_is_enforced_over_http(server):
    """The price-field ban is not a CLI-only guard."""
    payload = {
        "schema_version": "1.0",
        "portfolio_id": 1,
        "quotes": [{}],
        "research": {"analysis": [{"ticker": "COMI", "stop_loss": 79.8}]},
    }
    status, body = call(f"{server}/decide", body=json.dumps(payload).encode())
    assert status == 400
    assert "may not supply trade numbers" in body["error"]


def test_responses_are_json(server):
    request = urllib.request.Request(f"{server}/health", method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.headers["Content-Type"] == "application/json"
