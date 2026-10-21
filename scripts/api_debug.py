#!/usr/bin/env python3
"""Inspect the Peloton API with the integration's own client.

Logs in once with a password, prints a short summary of the account and the
latest workout, and revokes the refresh token before exiting. Needs Python
3.14 and aiohttp (both come with Home Assistant; scripts/docker-check's venv
has them).

Credentials come from PELOTON_USERNAME and PELOTON_PASSWORD, or are prompted
for. They are never taken from the command line, so they stay out of shell
history.

Examples:
  scripts/api_debug.py                 summary only
  scripts/api_debug.py --raw           also print full JSON; contains personal
                                       data (usernames, emails and token
                                       fields are redacted)
  scripts/api_debug.py --fixtures DIR  write sanitized JSON to DIR, which must
                                       not already contain fixtures
  scripts/api_debug.py --smoke         login, refresh, revoke, check revoke

Each run does exactly one password login. Keep runs few: Peloton and
Cloudflare rate limit logins per IP address.
"""

import argparse
import asyncio
from collections.abc import Callable
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

import aiohttp

# Load the client package directly, without importing the Home Assistant
# integration around it.
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "custom_components" / "peloton")
)

from api import (
    PelotonAuthError,
    PelotonClient,
    PelotonError,
    PelotonTokens,
    async_login,
    async_refresh,
)

HEX_ID = re.compile(r"^[0-9a-f]{32}$")

# Keys whose values are personal, whatever their type.
PERSONAL_KEYS = frozenset(
    {
        "username",
        "first_name",
        "last_name",
        "middle_initial",
        "email",
        "obfuscated_email",
        "location",
        "birthday",
        "gender",
        "height",
        "weight",
        "phone_number",
        "bio",
        "facebook_id",
        "default_max_heart_rate",
        "customized_max_heart_rate",
        "default_heart_rate_zones",
        "customized_heart_rate_zones",
    }
)
# Lists or objects about the account that tests never need; emptied whole.
DROPPED_KEYS = frozenset(
    {
        "social_connections",
        "paired_devices",
        "member_groups",
        "contract_agreements",
        "external_music_auth_list",
        "corporate_wellness_group",
    }
)
# "name" is personal on a user or instructor; elsewhere it labels metrics
# and segments ("resistance", "Warm Up") that tests rely on.
NAME_PARENTS = frozenset({None, "user", "instructor"})
# Keys whose values --raw always hides.
RAW_SECRET_KEYS = frozenset({"username", "email", "obfuscated_email"})

FIXTURE_NAMES = ("me", "settings", "workouts", "workout", "performance_graph")


def credentials() -> tuple[str, str]:
    """Read credentials from the environment or prompt for them."""
    try:
        username = (
            os.environ.get("PELOTON_USERNAME") or input("Peloton username or email: ")
        ).strip()
        password = os.environ.get("PELOTON_PASSWORD") or getpass.getpass(
            "Peloton password: "
        )
    except EOFError, KeyboardInterrupt:
        raise SystemExit(
            "Error: no credentials. Set PELOTON_USERNAME and PELOTON_PASSWORD, "
            "or run with a terminal (docker run -it)."
        ) from None
    if not username or not password:
        raise SystemExit("Error: username and password must not be empty.")
    return username, password


def sanitizer() -> Callable[[Any], Any]:
    """Return a function that strips personal data from API responses.

    32-character hex ids are replaced consistently, so ids that refer to each
    other still match. Check the output before committing it anyway.
    """
    ids: dict[str, str] = {}

    def fake_id(value: str) -> str:
        if value == "0" * 32:
            return value
        if value not in ids:
            ids[value] = hashlib.sha256(f"fixture-{len(ids)}".encode()).hexdigest()[:32]
        return ids[value]

    def redact(value: Any) -> Any:
        if isinstance(value, str):
            return "redacted"
        if isinstance(value, int | float) and not isinstance(value, bool):
            return 0
        if isinstance(value, list):
            return []
        return None

    def clean(value: Any, key: str | None = None, parent: str | None = None) -> Any:
        if key is not None:
            if (
                key in PERSONAL_KEYS
                or "token" in key
                or (key == "name" and parent in NAME_PARENTS)
            ):
                return redact(value)
            if key in DROPPED_KEYS or "location" in key:
                if isinstance(value, bool):
                    return False
                return [] if isinstance(value, list) else None
            if isinstance(value, str):
                if key == "timezone":
                    return "UTC"
                if "country" in key or "locale" in key:
                    return "redacted"
        if isinstance(value, dict):
            return {k: clean(v, k, key) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v, key, parent) for v in value]
        if not isinstance(value, str):
            return value
        if key is not None and key.endswith("_url"):
            return "https://example.invalid/"
        if HEX_ID.match(value):
            return fake_id(value)
        if key is not None and (key == "id" or key.endswith("_id")):
            return "redacted"
        return value

    return clean


def redact_secrets(value: Any, key: str | None = None) -> Any:
    """Hide usernames, emails and token fields in --raw output."""
    if key is not None and (key in RAW_SECRET_KEYS or "token" in key):
        return "redacted" if value is not None else None
    if isinstance(value, dict):
        return {k: redact_secrets(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(v, key) for v in value]
    return value


def check_fixture_dir(directory: Path) -> str | None:
    """Return an error message if fixtures cannot be written safely to directory."""
    existing = [n for n in FIXTURE_NAMES if (directory / f"{n}.json").exists()]
    if existing:
        files = ", ".join(f"{n}.json" for n in existing)
        return f"{directory} already has {files}; pick an empty directory"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".api_debug_write_test"
        probe.touch()
        probe.unlink()
    except OSError as err:
        return f"cannot write to {directory}: {err}"
    return None


def show(title: str, data: Any) -> None:
    """Print a JSON document under a heading."""
    print(f"\n== {title}")
    print(json.dumps(data, indent=2))


async def revoke(client: PelotonClient) -> bool:
    """Revoke the login's refresh token; warn instead of failing."""
    try:
        await client.async_revoke()
    except PelotonError as err:
        print(
            "WARNING: could not revoke the refresh token from this login "
            f"({type(err).__name__}: {err}). It stays valid until Peloton "
            "expires it.",
            file=sys.stderr,
        )
        return False
    print("Refresh token revoked.")
    return True


async def run(args: argparse.Namespace) -> int:
    """Log in, inspect the account, and always revoke the refresh token."""
    if args.fixtures and (message := check_fixture_dir(args.fixtures)):
        print(f"Error: {message}", file=sys.stderr)
        return 1
    if args.raw:
        print(
            "Note: --raw output contains personal data; do not paste it into "
            "issues or commit it.",
            file=sys.stderr,
        )
    username, password = credentials()
    async with aiohttp.ClientSession() as session:
        tokens = await async_login(session, username, password)
        del password
        lifetime = round((tokens.expires_at - time.time()) / 3600, 1)
        print(
            f"Logged in. Access token valid for {lifetime} h; refresh token: "
            f"{'yes' if tokens.refresh_token else 'no'}; user id in token: "
            f"{'yes' if tokens.user_id else 'no'}."
        )
        refreshes: list[PelotonTokens] = []
        client = PelotonClient(session, tokens, refreshes.append)
        if args.smoke:
            return await smoke(session, client)
        try:
            await inspect(client, args)
        finally:
            revoked = await revoke(client)
    return 0 if revoked else 1


async def inspect(client: PelotonClient, args: argparse.Namespace) -> None:
    """Print a summary, and optionally raw JSON or sanitized fixtures."""
    me = await client.async_get_me()
    settings = await client.async_get_settings()
    workout = await client.async_get_latest_workout()
    print(
        f"Total workouts: {me.total_workouts}; distance unit: {settings.distance_unit}"
    )
    print(f"Workout counts: {me.workout_counts}")
    if workout is None or workout.id is None:
        print("No workouts on this account.")
    else:
        workout = await client.async_get_workout(workout.id)
        graph = await client.async_get_performance_graph(workout.id)
        print(
            f"Latest workout: {workout.status}, {workout.fitness_discipline}, "
            f"device {workout.device_type}, class: "
            f"{workout.ride.is_class if workout.ride else None}"
        )
        print(
            f"Summaries: {sorted(graph.summaries)}; "
            f"averages: {sorted(graph.average_summaries)}; "
            f"metrics: {sorted(graph.metrics)}"
        )

    if not (args.raw or args.fixtures):
        return
    user_id = me.id
    raw: dict[str, Any] = {
        "me": await client.async_get_raw("/api/me"),
        "settings": await client.async_get_raw(f"/api/user/{user_id}/settings"),
        "workouts": await client.async_get_raw(
            f"/api/user/{user_id}/workouts",
            {
                "sort_by": "-created",
                "page": 0,
                "limit": 1,
                "joins": "ride,ride.instructor",
            },
        ),
    }
    if workout is not None and workout.id is not None:
        raw["workout"] = await client.async_get_raw(
            f"/api/workout/{workout.id}", {"joins": "ride,ride.instructor"}
        )
        raw["performance_graph"] = await client.async_get_raw(
            f"/api/workout/{workout.id}/performance_graph", {"every_n": 5}
        )
    if args.raw:
        for name, data in raw.items():
            show(name, redact_secrets(data))
    if args.fixtures:
        clean = sanitizer()
        for name, data in raw.items():
            path = args.fixtures / f"{name}.json"
            with path.open("x") as file:
                file.write(json.dumps(clean(data), indent=2) + "\n")
            print(f"Wrote {path}")


async def smoke(session: aiohttp.ClientSession, client: PelotonClient) -> int:
    """Check refresh and revoke against the live API. Returns an exit code."""
    before = client.tokens
    if before.refresh_token is None:
        print("FAIL: login returned no refresh token")
        return 1
    try:
        await client.async_get_me()
        print("API call with the login token: ok")
        refreshed = await async_refresh(session, before.refresh_token)
        print(
            "Refresh: ok (new access token: "
            f"{refreshed.access_token != before.access_token}; refresh token "
            f"rotated: {refreshed.refresh_token != before.refresh_token})"
        )
    finally:
        # Revoke even if a step above failed, so no refresh token is left behind.
        revoked = await revoke(client)
    if not revoked:
        return 1
    try:
        await async_refresh(session, before.refresh_token)
    except PelotonAuthError:
        print("Refresh after revoke: rejected as expected")
        return 0
    print("FAIL: refresh still works after revoke")
    return 1


def main() -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="print full JSON responses (personal data; usernames, emails and "
        "token fields are redacted)",
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        help="write sanitized JSON to this directory (must not hold fixtures)",
    )
    parser.add_argument("--smoke", action="store_true", help="test refresh and revoke")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except PelotonError as err:
        print(f"Error: {type(err).__name__}: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
