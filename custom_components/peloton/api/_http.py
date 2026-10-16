"""Response handling shared by the auth and API requests."""

from collections.abc import Mapping
import json
import math
from typing import Any

import aiohttp

from .exceptions import PelotonConnectionError, PelotonRateLimitError


async def read_body(resp: aiohttp.ClientResponse) -> tuple[Any, str]:
    """Return (parsed JSON or None, raw text) for a response.

    The body is only parsed when the server says it is JSON. Cloudflare answers
    some errors with plain text ("error code: 1015") and unknown API paths
    return HTML.
    """
    # Replace undecodable bytes: proxies and gateways sometimes send error pages
    # that are not valid UTF-8, and those must still classify as HTTP errors.
    text = await resp.text(errors="replace")
    if "json" not in (resp.content_type or ""):
        return None, text
    try:
        return json.loads(text), text
    except ValueError:
        return None, text


def retry_after(headers: Mapping[str, str]) -> float | None:
    """Return the Retry-After header in seconds, if it is a positive number."""
    try:
        value = float(headers["Retry-After"])
    except KeyError, ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def raise_for_transient(
    status: int, text: str, headers: Mapping[str, str], what: str
) -> None:
    """Raise for responses that are worth retrying later: rate limits and 5xx."""
    if status == 429 or "error code: 1015" in text:
        raise PelotonRateLimitError(
            f"{what}: rate limited (HTTP {status})", retry_after(headers)
        )
    if status >= 500:
        raise PelotonConnectionError(f"{what}: server error (HTTP {status})")
