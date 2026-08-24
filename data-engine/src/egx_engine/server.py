"""A deliberately small HTTP shim over :func:`egx_engine.decide.decide`.

Two routes, no framework, no third-party dependency:

* ``GET  /health``  — liveness for the container healthcheck. No auth, no data.
* ``POST /decide``  — bearer-authenticated; body in, decision out.

It is a transport and nothing more. Every rule about what may be decided lives
in the engine; this file only moves bytes and refuses callers it does not
recognise.

Deployment shape: the service listens inside a private Docker network and its
port is never published to the host, so the only thing that can reach it is
another container on that network. PostgreSQL is reached the same way and is
likewise unpublished. Binding to ``0.0.0.0`` inside the container is therefore
not exposure — the absence of a compose ``ports:`` mapping is what keeps it
private, and that is where the guarantee is enforced.

Single-threaded on purpose. One decision a day does not need concurrency, and
a serial server cannot interleave two transactions on one connection. Each
request opens its own connection and closes it.
"""

from __future__ import annotations

import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .db.connection import connect
from .decide import (
    DecideError,
    decide_request,
    json_default,
    parse_decide_request,
    parse_request_json,
)
from .settings import Settings, SettingsError, load_settings

LOGGER = logging.getLogger("egx_engine.server")

#: Requests larger than this are refused unread.
MAX_BODY_BYTES = 1_000_000


class SentinelHandler(BaseHTTPRequestHandler):
    """Request handler. ``settings`` is injected by :func:`build_server`."""

    settings: Settings
    server_version = "EGXSentinel"
    sys_version = ""

    # -- plumbing ---------------------------------------------------------

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Close rather than keep alive. An error path may answer before reading
        # the request body, which leaves a reused connection out of sync with
        # the client; one connection per request costs nothing at this volume.
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send(status, {"error": message})

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        LOGGER.info("%s - %s", self.address_string(), fmt % args)

    def _authorised(self) -> bool:
        """Constant-time bearer check.

        ``compare_digest`` rather than ``==`` so a wrong token cannot be
        recovered one character at a time from response timing.
        """
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return False
        return hmac.compare_digest(token.strip(), self.settings.api_token or "")

    # -- routes -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self.path.split("?")[0] == "/health":
            self._send(200, {"status": "ok", "service": "egx-sentinel"})
            return
        self._error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error(400, "invalid Content-Length")
            return

        if length > MAX_BODY_BYTES:
            # Refused unread: we will not pull a megabyte off the wire only to
            # discard it. The connection closes, which a client that declared
            # more than it sent may see as a reset rather than a 413.
            self._error(413, "request body too large")
            return

        # Consume the body before answering anything else. Responding while an
        # unread body is still in flight desynchronises the connection, so
        # routing and authentication both happen after this read.
        raw = self.rfile.read(length) if length > 0 else b""

        if self.path.split("?")[0] != "/decide":
            self._error(404, "not found")
            return

        if not self._authorised():
            # Deliberately uninformative: a caller without a valid token learns
            # nothing about whether the route or the token was the problem.
            self._error(401, "unauthorized")
            return

        if not raw:
            self._error(400, "empty request body")
            return

        try:
            # Validate fully before opening a connection: a malformed request,
            # or one that violates the research boundary, must never reach the
            # database or cost a transaction.
            request = parse_decide_request(parse_request_json(raw))
        except DecideError as exc:
            self._error(400, str(exc))
            return

        try:
            with connect() as conn:
                result = decide_request(conn, request)
        except DecideError as exc:
            self._error(400, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - never leak internals
            # The detail goes to the log, not to the caller.
            LOGGER.exception("decide failed")
            self._error(500, f"internal error: {type(exc).__name__}")
            return

        self._send(200, result)


def build_server(settings: Settings | None = None) -> HTTPServer:
    """Construct the server, refusing to start without a token."""
    settings = settings or load_settings()

    if not settings.api_token:
        raise SettingsError(
            "SENTINEL_API_TOKEN is not set; refusing to start an unauthenticated "
            "decision endpoint"
        )

    handler = type("BoundSentinelHandler", (SentinelHandler,), {"settings": settings})
    return HTTPServer((settings.http_host, settings.http_port), handler)


def serve(settings: Settings | None = None) -> int:  # pragma: no cover - blocking
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    httpd = build_server(settings)
    host, port = httpd.server_address[0], httpd.server_address[1]
    LOGGER.info("EGX Sentinel listening on %s:%s (analysis only, no execution)", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("shutting down")
    finally:
        httpd.server_close()
    return 0


__all__ = ["MAX_BODY_BYTES", "SentinelHandler", "build_server", "serve"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(serve())
