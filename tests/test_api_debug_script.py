"""Tests for scripts/api_debug.py helpers (no network)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "api_debug.py"

# Hard-coded on purpose: removing a key from the script must fail a test.
EXPECTED_PERSONAL_KEYS = {
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


def load_script() -> ModuleType:
    """Load scripts/api_debug.py as a module."""
    spec = importlib.util.spec_from_file_location("api_debug", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def api_debug() -> ModuleType:
    """Load the script once per module."""
    return load_script()


def test_personal_key_list(api_debug: ModuleType) -> None:
    """The script redacts at least the expected personal keys."""
    assert EXPECTED_PERSONAL_KEYS <= api_debug.PERSONAL_KEYS


@pytest.mark.parametrize("key", sorted(EXPECTED_PERSONAL_KEYS))
def test_personal_key_redacted(api_debug: ModuleType, key: str) -> None:
    """Personal values are redacted whatever their type and depth."""
    clean = api_debug.sanitizer()

    assert clean({key: "secret"})[key] == "redacted"
    assert clean({key: 42})[key] == 0
    assert clean({key: [1, 2]})[key] == []
    assert clean({"items": [{key: "secret"}]})["items"][0][key] == "redacted"


def test_sanitizer(api_debug: ModuleType) -> None:
    """Ids, URLs, locations and account lists are cleaned; workout data stays."""
    user_id = "ab" * 16
    clean = api_debug.sanitizer()

    result = clean(
        {
            "id": user_id,
            "name": "Real Name",
            "facebook_access_token": "secret",
            "image_url": "https://example.com/me.jpg",
            "created_country": "US",
            "locale": "en-US",
            "strava_id": "12345",
            "external_music_auth_list": [{"email": "me@example.com"}],
            "workouts": [
                {
                    "user_id": user_id,
                    "name": "Cycling Workout",
                    "timezone": "America/New_York",
                    "ride": {"id": "0" * 32, "instructor": {"name": "Coach"}},
                    "total_work": 360000.0,
                    "is_paused": False,
                }
            ],
            "location_data": [{"coordinates": [{"lat": 40.7, "lng": -74.0}]}],
            "is_location_data_accurate": True,
            "segment_list": [{"name": "Warm Up"}],
            "time_in_metric": [{"name": "resistance"}],
        }
    )

    workout = result["workouts"][0]
    assert result["id"] != user_id
    assert workout["user_id"] == result["id"]
    assert workout["ride"]["id"] == "0" * 32
    assert result["name"] == "redacted"
    assert workout["ride"]["instructor"]["name"] == "redacted"
    assert workout["name"] == "Cycling Workout"
    assert result["segment_list"][0]["name"] == "Warm Up"
    assert result["time_in_metric"][0]["name"] == "resistance"
    assert result["facebook_access_token"] == "redacted"
    assert result["image_url"] == "https://example.invalid/"
    assert result["created_country"] == result["locale"] == "redacted"
    assert result["strava_id"] == "redacted"
    assert result["external_music_auth_list"] == []
    assert result["location_data"] == []
    assert result["is_location_data_accurate"] is False
    assert workout["timezone"] == "UTC"
    assert workout["total_work"] == 360000.0
    assert workout["is_paused"] is False


def test_redact_secrets(api_debug: ModuleType) -> None:
    """--raw output hides usernames, emails and token fields."""
    result = api_debug.redact_secrets(
        {
            "username": "me",
            "email": "me@example.com",
            "ride": {"join_tokens": {"x": 1}},
            "total_workouts": 3,
        }
    )

    assert result == {
        "username": "redacted",
        "email": "redacted",
        "ride": {"join_tokens": "redacted"},
        "total_workouts": 3,
    }


def test_check_fixture_dir(api_debug: ModuleType, tmp_path: Path) -> None:
    """Fixtures are never written over existing ones."""
    assert api_debug.check_fixture_dir(tmp_path / "new") is None
    (tmp_path / "me.json").write_text("{}")
    assert "me.json" in api_debug.check_fixture_dir(tmp_path)


@pytest.mark.parametrize(
    ("username", "password"), [("", "pw"), ("   ", "pw"), ("user", "")]
)
def test_credentials_must_not_be_empty(
    api_debug: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    username: str,
    password: str,
) -> None:
    """Empty credentials stop before any login is attempted."""
    monkeypatch.setenv("PELOTON_USERNAME", username)
    monkeypatch.setenv("PELOTON_PASSWORD", password)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr(api_debug.getpass, "getpass", lambda _prompt: "")

    with pytest.raises(SystemExit):
        api_debug.credentials()


def test_credentials_without_terminal(
    api_debug: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without env vars or a terminal the script exits with a clear message."""
    monkeypatch.delenv("PELOTON_USERNAME", raising=False)
    monkeypatch.delenv("PELOTON_PASSWORD", raising=False)

    def no_input(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", no_input)

    with pytest.raises(SystemExit, match="PELOTON_USERNAME"):
        api_debug.credentials()
