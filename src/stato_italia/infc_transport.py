from __future__ import annotations

import os
import re
from collections.abc import Callable
from time import sleep
from typing import Any
from urllib.parse import urlparse

import requests

INFC_HOST = "www.inventarioforestale.org"
INFC_PROXY_ENV = "INFC_HTTPS_PROXIES"
_RETRYABLE_ROUTE_STATUSES = {403, 407, 408, 429, 500, 502, 503, 504}
_TRANSPORT_ERRORS = (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError)


class InfcTransportError(requests.ConnectionError):
    """All TLS-verified routes to the official INFC host failed."""


def is_infc_url(url: str) -> bool:
    return urlparse(url).hostname == INFC_HOST


def is_retryable_infc_status(url: str, status_code: int) -> bool:
    return is_infc_url(url) and status_code in _RETRYABLE_ROUTE_STATUSES


def _normalise_proxy(value: str, *, position: int) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"Empty INFC proxy at position {position}")
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    try:
        parsed = urlparse(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid INFC proxy at position {position}") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or port is None:
        raise ValueError(f"Invalid INFC proxy at position {position}")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError(f"Invalid INFC proxy at position {position}")
    return candidate.rstrip("/")


def configured_infc_proxies(raw: str | None = None) -> tuple[str, ...]:
    """Parse operator-prioritised proxies from a multiline or comma-separated secret."""
    raw = os.getenv(INFC_PROXY_ENV, "") if raw is None else raw
    values = [value for value in re.split(r"[\r\n,]+", raw) if value.strip()]
    proxies: list[str] = []
    for position, value in enumerate(values, start=1):
        proxy = _normalise_proxy(value, position=position)
        if proxy not in proxies:
            proxies.append(proxy)
    return tuple(proxies)


def infc_proxy_candidates(url: str) -> tuple[str, ...]:
    """Return operator-configured proxies only inside GitHub Actions."""
    if not is_infc_url(url) or os.getenv("GITHUB_ACTIONS") != "true":
        return ()
    return configured_infc_proxies()


def get_with_infc_fallback(
    request_get: Callable[..., Any],
    url: str,
    *,
    direct_attempts: int = 1,
    retry_sleep: Callable[[float], None] = sleep,
    **kwargs: Any,
) -> tuple[Any, str]:
    """GET directly, then try configured proxies only for INFC in Actions."""
    if direct_attempts < 1:
        raise ValueError("direct_attempts must be positive")
    request_kwargs = {**kwargs, "verify": True}
    direct_error: requests.RequestException | None = None
    for attempt in range(direct_attempts):
        try:
            response = request_get(url, **request_kwargs)
            if not is_retryable_infc_status(url, response.status_code):
                return response, "direct"
            response.close()
            direct_error = requests.HTTPError(f"INFC direct route returned HTTP {response.status_code}")
        except _TRANSPORT_ERRORS as exc:
            direct_error = exc
        if attempt + 1 < direct_attempts:
            retry_sleep(2 ** attempt)
    if not is_infc_url(url):
        assert direct_error is not None
        raise direct_error
    proxies = infc_proxy_candidates(url)
    for proxy in proxies:
        try:
            response = request_get(url, **request_kwargs, proxies={"https": proxy})
            if is_retryable_infc_status(url, response.status_code):
                response.close()
                continue
            return response, "proxy"
        except _TRANSPORT_ERRORS:
            continue
    direct_reason = type(direct_error).__name__ if direct_error else "unknown"
    error = InfcTransportError(
        f"INFC direct route and {len(proxies)} TLS-verified proxy routes failed; direct={direct_reason}"
    )
    if direct_error is not None:
        raise error from direct_error
    raise error
