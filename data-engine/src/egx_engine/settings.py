"""Environment-derived configuration.

:mod:`egx_engine.config` is deliberately pure: it reads nothing and every value
in it is deterministic, which is what makes it safe to use inside calculations.
Anything that depends on the environment lives here instead, so that separation
survives Phase 2.

Fail closed: an unreadable or nonsensical value raises :class:`SettingsError`
rather than falling back to a guess. The one safe default is the provider name,
which defaults to ``unconfigured`` — the provider that refuses to serve data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

PROVIDER_ENV_VAR = "MARKET_DATA_PROVIDER"
PROVIDER_DATA_DIR_ENV_VAR = "MARKET_DATA_DIR"
API_KEY_ENV_VAR = "MARKET_DATA_API_KEY"
PORTFOLIO_ID_ENV_VAR = "EGX_PORTFOLIO_ID"
API_TOKEN_ENV_VAR = "SENTINEL_API_TOKEN"
HTTP_HOST_ENV_VAR = "SENTINEL_HTTP_HOST"
HTTP_PORT_ENV_VAR = "SENTINEL_HTTP_PORT"

DEFAULT_PROVIDER = "unconfigured"

# Inside a container this is the only way a sibling container can reach us.
# Privacy comes from not publishing the port, not from the bind address.
DEFAULT_HTTP_HOST = "0.0.0.0"  # noqa: S104
DEFAULT_HTTP_PORT = 8080


class SettingsError(RuntimeError):
    """Environment configuration is missing or unusable.

    Like the persistence errors, this is a *safe* failure: callers must turn it
    into a refusal to act, never into a decision.
    """


@dataclass(frozen=True)
class Settings:
    """Resolved environment settings.

    ``portfolio_id`` is optional at load time because not every command needs
    one (``load-universe`` does not). Commands that do need it call
    :meth:`require_portfolio_id`, which fails loudly rather than defaulting to
    portfolio 1.
    """

    provider_name: str = DEFAULT_PROVIDER
    provider_data_dir: Path | None = None
    api_key: str | None = None
    portfolio_id: int | None = None
    # Bearer token the HTTP shim requires. No default: an unset token means the
    # server refuses to start rather than listening without authentication.
    api_token: str | None = None
    http_host: str = DEFAULT_HTTP_HOST
    http_port: int = DEFAULT_HTTP_PORT

    def require_portfolio_id(self) -> int:
        if self.portfolio_id is None:
            raise SettingsError(
                f"{PORTFOLIO_ID_ENV_VAR} is not set; refusing to guess which "
                "portfolio a decision belongs to"
            )
        return self.portfolio_id

    def require_provider_data_dir(self) -> Path:
        if self.provider_data_dir is None:
            raise SettingsError(
                f"{PROVIDER_DATA_DIR_ENV_VAR} is not set; the {self.provider_name!r} "
                "provider has no data directory to read"
            )
        return self.provider_data_dir


def _clean(value: str | None) -> str | None:
    """Treat whitespace-only environment values as absent."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _portfolio_id(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        identifier = int(raw)
    except ValueError as exc:
        raise SettingsError(
            f"{PORTFOLIO_ID_ENV_VAR} must be an integer, got {raw!r}"
        ) from exc
    if identifier <= 0:
        raise SettingsError(
            f"{PORTFOLIO_ID_ENV_VAR} must be a positive integer, got {identifier}"
        )
    return identifier


def _http_port(raw: str | None) -> int:
    if raw is None:
        return DEFAULT_HTTP_PORT
    try:
        port = int(raw)
    except ValueError as exc:
        raise SettingsError(
            f"{HTTP_PORT_ENV_VAR} must be an integer, got {raw!r}"
        ) from exc
    if not (1 <= port <= 65535):
        raise SettingsError(f"{HTTP_PORT_ENV_VAR} must be a valid port, got {port}")
    return port


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read settings from ``env`` (defaults to the process environment)."""
    source = os.environ if env is None else env

    data_dir = _clean(source.get(PROVIDER_DATA_DIR_ENV_VAR))

    return Settings(
        provider_name=(_clean(source.get(PROVIDER_ENV_VAR)) or DEFAULT_PROVIDER).lower(),
        provider_data_dir=Path(data_dir) if data_dir else None,
        api_key=_clean(source.get(API_KEY_ENV_VAR)),
        portfolio_id=_portfolio_id(_clean(source.get(PORTFOLIO_ID_ENV_VAR))),
        api_token=_clean(source.get(API_TOKEN_ENV_VAR)),
        http_host=_clean(source.get(HTTP_HOST_ENV_VAR)) or DEFAULT_HTTP_HOST,
        http_port=_http_port(_clean(source.get(HTTP_PORT_ENV_VAR))),
    )


__all__ = [
    "API_KEY_ENV_VAR",
    "API_TOKEN_ENV_VAR",
    "DEFAULT_HTTP_HOST",
    "DEFAULT_HTTP_PORT",
    "DEFAULT_PROVIDER",
    "HTTP_HOST_ENV_VAR",
    "HTTP_PORT_ENV_VAR",
    "PORTFOLIO_ID_ENV_VAR",
    "PROVIDER_DATA_DIR_ENV_VAR",
    "PROVIDER_ENV_VAR",
    "Settings",
    "SettingsError",
    "load_settings",
]
