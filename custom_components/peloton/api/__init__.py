"""Async client for the Peloton API.

This package depends only on aiohttp and the standard library, so it can be
used outside Home Assistant (see scripts/api_debug.py).
"""

from .auth import PelotonTokens, async_login, async_refresh, async_revoke
from .client import PelotonClient
from .exceptions import (
    PelotonAuthError,
    PelotonConnectionError,
    PelotonError,
    PelotonMfaRequiredError,
    PelotonRateLimitError,
)
from .models import (
    Metric,
    PelotonUser,
    PerformanceGraph,
    Ride,
    Summary,
    UserSettings,
    Workout,
)

__all__ = [
    "Metric",
    "PelotonAuthError",
    "PelotonClient",
    "PelotonConnectionError",
    "PelotonError",
    "PelotonMfaRequiredError",
    "PelotonRateLimitError",
    "PelotonTokens",
    "PelotonUser",
    "PerformanceGraph",
    "Ride",
    "Summary",
    "UserSettings",
    "Workout",
    "async_login",
    "async_refresh",
    "async_revoke",
]
