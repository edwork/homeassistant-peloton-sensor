"""Peloton API client with Auth0 OAuth PKCE authentication."""

import base64
import hashlib
import logging
import secrets
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

# Auth0 OAuth settings
OAUTH_AUTHORIZE_URL = "https://auth.onepeloton.com/authorize"
OAUTH_LOGIN_URL = "https://auth.onepeloton.com/usernamepassword/login"
OAUTH_TOKEN_URL = "https://auth.onepeloton.com/oauth/token"
OAUTH_CALLBACK_URL = "https://auth.onepeloton.com/login/callback"
OAUTH_CLIENT_ID = "WVoJxVDdPoFx4RNewvvg6ch2mZ7bwnsM"
OAUTH_AUDIENCE = "https://api.onepeloton.com/"
OAUTH_SCOPE = "offline_access openid peloton-api.members:default"
OAUTH_REDIRECT_URI = "https://members.onepeloton.com/callback"
OAUTH_AUTH0_CLIENT = "eyJuYW1lIjoiYXV0aDAuanMtdWxwIiwidmVyc2lvbiI6IjkuMTQuMyJ9"

BASE_URL = "https://api.onepeloton.com"


class PelotonLoginException(Exception):
    """Raised when Peloton authentication fails."""


def _generate_pkce():
    """Generate PKCE code verifier and challenge."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def oauth_login(email, password):
    """Authenticate via Auth0 PKCE flow. Returns (access_token, refresh_token)."""
    sess = requests.Session()
    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    # Step 1: /authorize
    auth_resp = sess.get(
        OAUTH_AUTHORIZE_URL,
        params={
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": OAUTH_SCOPE,
            "audience": OAUTH_AUDIENCE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "nonce": nonce,
        },
        allow_redirects=True,
        timeout=30,
    )
    auth_resp.raise_for_status()

    # Extract state from redirect URL
    login_url = auth_resp.url
    if "state=" in login_url:
        url_qs = parse_qs(urlparse(login_url).query)
        if "state" in url_qs:
            state = url_qs["state"][0]

    # Extract CSRF from cookies
    csrf_token = ""
    for cookie in sess.cookies:
        if cookie.name == "_csrf" and "/usernamepassword" in (cookie.path or ""):
            csrf_token = cookie.value
            break
    if not csrf_token:
        for cookie in sess.cookies:
            if cookie.name == "_csrf":
                csrf_token = cookie.value
                break

    # Step 2: POST credentials
    login_resp = sess.post(
        OAUTH_LOGIN_URL,
        json={
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "tenant": "peloton-prod",
            "response_type": "code",
            "scope": OAUTH_SCOPE,
            "audience": OAUTH_AUDIENCE,
            "state": state,
            "nonce": nonce,
            "connection": "pelo-user-password",
            "username": email,
            "password": password,
            "_csrf": csrf_token,
            "_intstate": "deprecated",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        },
        headers={
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Auth0-Client": OAUTH_AUTH0_CLIENT,
            "Origin": "https://auth.onepeloton.com",
            "Referer": login_url,
        },
        allow_redirects=False,
        timeout=30,
    )
    login_resp.raise_for_status()

    # Step 3: Follow callback form or redirect to get auth code
    auth_code = None
    location = login_resp.headers.get("Location", "")
    if location and "code=" in location:
        auth_code = parse_qs(urlparse(location).query).get("code", [None])[0]
    else:
        soup = BeautifulSoup(login_resp.text, "html.parser")
        form = soup.find("form")
        if not form:
            raise PelotonLoginException("No callback form in login response")

        form_action = form.get("action", OAUTH_CALLBACK_URL)
        if not form_action.startswith("http"):
            form_action = f"https://auth.onepeloton.com{form_action}"

        form_data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                form_data[name] = value

        callback_resp = sess.post(
            form_action,
            data=form_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            allow_redirects=False,
            timeout=30,
        )

        max_redirects = 10
        loc = ""
        while max_redirects > 0:
            loc = callback_resp.headers.get("Location", "")
            if not loc:
                break
            if "code=" in loc:
                auth_code = parse_qs(urlparse(loc).query).get("code", [None])[0]
                break
            if not loc.startswith("http"):
                loc = f"https://auth.onepeloton.com{loc}"
            callback_resp = sess.get(loc, allow_redirects=False, timeout=30)
            max_redirects -= 1

        if not auth_code and loc and "code=" in loc:
            auth_code = parse_qs(urlparse(loc).query).get("code", [None])[0]

    if not auth_code:
        raise PelotonLoginException("Could not obtain authorization code")

    # Step 4: Exchange code for tokens
    token_resp = sess.post(
        OAUTH_TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "client_id": OAUTH_CLIENT_ID,
            "code_verifier": code_verifier,
            "code": auth_code,
            "redirect_uri": OAUTH_REDIRECT_URI,
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )
    token_resp.raise_for_status()
    data = token_resp.json()

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    if not access_token:
        raise PelotonLoginException("No access_token in token response")

    return access_token, refresh_token


def oauth_refresh(refresh_token):
    """Use refresh token to get a new access token. Returns (access_token, refresh_token)."""
    resp = requests.post(
        OAUTH_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": OAUTH_CLIENT_ID,
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    new_access = data.get("access_token")
    new_refresh = data.get("refresh_token", refresh_token)
    if not new_access:
        raise PelotonLoginException("Refresh failed: no access_token")
    return new_access, new_refresh


class PelotonApi:
    """Drop-in replacement for PylotonCycle with Auth0 OAuth authentication."""

    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.access_token = None
        self.refresh_token = None
        self.userid = None
        self.username = None
        self.session = requests.Session()

        # Perform initial login
        self._login()

    def _login(self):
        """Authenticate and set up session."""
        try:
            self.access_token, self.refresh_token = oauth_login(self.email, self.password)
        except (requests.RequestException, PelotonLoginException) as e:
            raise PelotonLoginException(f"Login failed: {e}") from e

        self._update_session_headers()

        # Fetch user info to populate userid/username
        me = self._get(f"{BASE_URL}/api/me")
        self.userid = me.get("id")
        self.username = me.get("username")

    def _update_session_headers(self):
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
            "Peloton-Platform": "web",
        })

    def _refresh_auth(self):
        """Refresh the access token."""
        if not self.refresh_token:
            raise PelotonLoginException("No refresh token available")
        self.access_token, self.refresh_token = oauth_refresh(self.refresh_token)
        self._update_session_headers()
        _LOGGER.debug("Peloton access token refreshed")

    def _get(self, url, params=None):
        """GET with auto-retry on 401."""
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code == 401:
            self._refresh_auth()
            resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def GetMe(self):
        """Get user profile. Matches PylotonCycle.GetMe()."""
        resp = self._get(f"{BASE_URL}/api/me")
        self.username = resp.get("username")
        self.userid = resp.get("id")
        return resp

    def GetSettings(self):
        """Get user settings. Matches PylotonCycle.GetSettings()."""
        return self._get(f"{BASE_URL}/api/user/{self.userid}/settings")

    def GetRecentWorkouts(self, num_workouts=1):
        """Get recent workouts with metrics and instructor info.

        Matches PylotonCycle.GetRecentWorkouts() — returns a list of
        workout dicts with 'performance_graph' and 'instructor_name' merged in.
        """
        # Fetch workout list
        workouts = self._get(
            f"{BASE_URL}/api/user/{self.userid}/workouts",
            params={"limit": num_workouts, "sort_by": "-created"},
        )
        workout_list = workouts.get("data", [])

        result = []
        for workout_summary in workout_list:
            workout_id = workout_summary["id"]

            # Fetch full workout details
            workout_detail = self._get(f"{BASE_URL}/api/workout/{workout_id}")

            # Fetch performance graph
            perf_graph = self.GetWorkoutMetricsById(workout_id)
            workout_detail["performance_graph"] = perf_graph

            # Fetch instructor name
            ride = workout_detail.get("ride", {})
            instructor_id = ride.get("instructor_id")
            if instructor_id:
                try:
                    instructor = self._get(f"{BASE_URL}/api/instructor/{instructor_id}")
                    workout_detail["instructor_name"] = instructor.get("name")
                except Exception:
                    workout_detail["instructor_name"] = None
            elif "instructor" in ride and ride["instructor"]:
                workout_detail["instructor_name"] = ride["instructor"].get("name")
            else:
                workout_detail["instructor_name"] = None

            result.append(workout_detail)

        return result

    def GetWorkoutMetricsById(self, workout_id, frequency=50):
        """Get workout performance metrics. Matches PylotonCycle.GetWorkoutMetricsById()."""
        params = f"?every_n={frequency}" if frequency > 0 else ""
        return self._get(f"{BASE_URL}/api/workout/{workout_id}/performance_graph{params}")
