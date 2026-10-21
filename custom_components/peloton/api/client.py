"""Authenticated Peloton API client."""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import replace
import logging
import time
from typing import Any

import aiohttp

from ._http import describe_error, raise_for_transient, read_body
from .auth import PelotonTokens, async_login, async_refresh, async_revoke
from .const import API_BASE, REFRESH_RETRY_DELAY, REQUEST_TIMEOUT
from .exceptions import (
    PelotonAuthError,
    PelotonConnectionError,
    PelotonError,
    PelotonRateLimitError,
)
from .models import PelotonUser, PerformanceGraph, UserSettings, Workout

_LOGGER = logging.getLogger(__name__)

# Joins that embed the class and instructor in a workout, so the instructor
# endpoint (which fails for workouts without a class) is never needed.
_WORKOUT_JOINS = "ride,ride.instructor"


async def async_login_and_identify(
    session: aiohttp.ClientSession, username: str, password: str
) -> PelotonTokens:
    """Log in and return tokens that carry the Peloton user id.

    The id normally comes from the access token; if it is missing there, it is
    read from /api/me. Raises PelotonError when neither has it.
    """
    tokens = await async_login(session, username, password)
    if tokens.user_id is not None:
        return tokens
    client = PelotonClient(session, tokens)
    await client.async_get_me()
    if client.user_id is None:
        raise PelotonError("Peloton did not return a user id")
    return replace(tokens, user_id=client.user_id)


class PelotonClient:
    """Peloton API client that keeps its access token fresh.

    The client never logs in with a password. It refreshes the access token
    shortly before it expires, or once after a 401, and hands new tokens to
    ``on_tokens_updated`` so the caller can store them. A rejected refresh
    token raises PelotonAuthError.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: PelotonTokens,
        on_tokens_updated: Callable[[PelotonTokens], None] | None = None,
    ) -> None:
        """Initialize the client with tokens from a login or from storage."""
        self._session = session
        self._tokens = tokens
        self._on_tokens_updated = on_tokens_updated
        self._lock = asyncio.Lock()
        self._user_id = tokens.user_id
        # Counts finished refresh attempts, so requests that waited for the lock
        # can tell that a refresh ran (and failed) meanwhile.
        self._refresh_attempt = 0
        self._refresh_error: PelotonError | None = None
        # No proactive refresh before this time (after a transient failure).
        self._refresh_not_before = 0.0

    @property
    def tokens(self) -> PelotonTokens:
        """Return the current tokens."""
        return self._tokens

    @property
    def user_id(self) -> str | None:
        """Return the user id, once known from the token or /api/me."""
        return self._user_id

    async def async_get_me(self) -> PelotonUser:
        """Return the logged-in user."""
        user = PelotonUser.from_api(await self._async_get("/api/me"))
        if self._user_id is None:
            self._user_id = user.id
        return user

    async def async_get_settings(self) -> UserSettings:
        """Return the user's settings (distance unit)."""
        user_id = await self._async_user_id()
        return UserSettings.from_api(
            await self._async_get(f"/api/user/{user_id}/settings")
        )

    async def async_get_latest_workout(self) -> Workout | None:
        """Return the most recently created workout, or None if there are none.

        One request. The row has the status, times and class, but not the
        leaderboard, output, FTP or pause fields; use async_get_workout for those.
        """
        user_id = await self._async_user_id()
        data = await self._async_get(
            f"/api/user/{user_id}/workouts",
            {"sort_by": "-created", "page": 0, "limit": 1, "joins": _WORKOUT_JOINS},
        )
        rows = data.get("data") if isinstance(data, Mapping) else None
        if not isinstance(rows, list) or not rows:
            return None
        return Workout.from_api(rows[0])

    async def async_get_workout(self, workout_id: str) -> Workout:
        """Return one workout with all fields."""
        return Workout.from_api(
            await self._async_get(
                f"/api/workout/{workout_id}", {"joins": _WORKOUT_JOINS}
            )
        )

    async def async_get_performance_graph(
        self, workout_id: str, every_n: int = 5
    ) -> PerformanceGraph:
        """Return totals and metrics, sampled every ``every_n`` seconds.

        The last sample is always included, so a large every_n still gives
        the current value.
        """
        return PerformanceGraph.from_api(
            await self._async_get(
                f"/api/workout/{workout_id}/performance_graph", {"every_n": every_n}
            )
        )

    async def async_get_raw(
        self, path: str, params: Mapping[str, str | int] | None = None
    ) -> Any:
        """Return the parsed JSON for any API path (for debugging and fixtures)."""
        return await self._async_get(path, params)

    async def async_revoke(self) -> None:
        """Revoke the refresh token, for example when the entry is removed."""
        if self._tokens.refresh_token is not None:
            await async_revoke(self._session, self._tokens.refresh_token)

    async def _async_user_id(self) -> str:
        """Return the user id from the token, or from /api/me if it had none."""
        if self._user_id is None:
            await self.async_get_me()
        if self._user_id is None:
            raise PelotonError("Peloton did not return a user id")
        return self._user_id

    async def _async_access_token(self, rejected: str | None = None) -> str:
        """Return a usable access token, refreshing it when needed.

        ``rejected`` is a token the API just answered with 401. It is only
        refreshed if it is still the current token, so several requests that
        fail together cause a single refresh.

        A refresh that fails while other requests wait for the lock is not
        repeated by each of them; they get the same outcome. When a proactive
        refresh fails for a transient reason (network, server error, rate
        limit) and the current token has not expired yet, the current token is
        used and proactive refreshes pause for REFRESH_RETRY_DELAY seconds (or
        the server's Retry-After).
        """
        attempt_seen = self._refresh_attempt
        async with self._lock:
            current = self._tokens
            if rejected is not None and rejected != current.access_token:
                return current.access_token
            if rejected is None and (
                not current.needs_refresh()
                or time.time() < min(self._refresh_not_before, current.expires_at)
            ):
                return current.access_token
            if self._refresh_attempt != attempt_seen and self._refresh_error:
                # A refresh failed while this request waited; do not repeat it.
                return self._token_after_failed_refresh(
                    self._refresh_error, current, rejected
                )
            if current.refresh_token is None:
                raise PelotonAuthError("No refresh token stored; log in again")
            try:
                tokens = await async_refresh(self._session, current.refresh_token)
            except PelotonError as err:
                _LOGGER.debug("Refresh failed: %s", err)
                self._refresh_error = err
                return self._token_after_failed_refresh(err, current, rejected)
            finally:
                # Counted when finished, so requests that started waiting while
                # this refresh ran see the change.
                self._refresh_attempt += 1
            self._refresh_error = None
            self._refresh_not_before = 0.0
            self._tokens = tokens
            if tokens.user_id is not None:
                self._user_id = tokens.user_id
            if self._on_tokens_updated is not None:
                self._on_tokens_updated(tokens)
            return tokens.access_token

    def _token_after_failed_refresh(
        self, err: PelotonError, current: PelotonTokens, rejected: str | None
    ) -> str:
        """Keep using a still-valid token after a transient refresh failure."""
        now = time.time()
        if (
            isinstance(err, PelotonConnectionError)
            and rejected is None
            and now < current.expires_at
        ):
            delay = REFRESH_RETRY_DELAY
            if isinstance(err, PelotonRateLimitError) and err.retry_after:
                delay = max(delay, err.retry_after)
            self._refresh_not_before = now + delay
            return current.access_token
        raise err

    async def _async_get(
        self, path: str, params: Mapping[str, str | int] | None = None
    ) -> Any:
        """GET an API path and return the parsed JSON body."""
        rejected: str | None = None
        for attempt in range(2):
            token = await self._async_access_token(rejected)
            try:
                async with self._session.get(
                    f"{API_BASE}{path}",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        # Required by some endpoints (user overview); harmless elsewhere.
                        "Peloton-Platform": "web",
                    },
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    status = resp.status
                    data, text = await read_body(resp)
                    headers = resp.headers
            except (aiohttp.ClientError, TimeoutError) as err:
                raise PelotonConnectionError(
                    f"{path}: cannot reach Peloton: {describe_error(err)}"
                ) from err

            if status == 401:
                if attempt == 0:
                    rejected = token
                    continue
                raise PelotonAuthError(f"{path}: access token rejected after refresh")
            raise_for_transient(status, text, headers, path)
            if status != 200:
                raise PelotonError(f"{path}: unexpected HTTP {status}")
            if data is None:
                raise PelotonError(f"{path}: response is not JSON")
            return data
        raise AssertionError("unreachable")  # pragma: no cover
