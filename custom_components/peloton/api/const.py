"""Constants for the Peloton API client."""

import aiohttp

AUTH_BASE = "https://auth.onepeloton.com"
TOKEN_URL = f"{AUTH_BASE}/oauth/token"
REVOKE_URL = f"{AUTH_BASE}/oauth/revoke"
API_BASE = "https://api.onepeloton.com"

# Client id of Peloton's own web and iOS apps. Peloton offers no public OAuth
# client registration, so this is the only client that accepts the password
# grant used here.
CLIENT_ID = "mgsmWCD0A8Qn6uz6mmqI6qeBNHH9IPwS"
SCOPE = "openid offline_access"

# Claim in the access token that carries the Peloton user id.
USER_ID_CLAIM = "http://onepeloton.com/user_id"

# Refresh the access token this many seconds before it expires.
REFRESH_MARGIN = 300

# After a proactive refresh fails for a transient reason, wait this many seconds
# before trying again (the current token stays in use meanwhile).
REFRESH_RETRY_DELAY = 60

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)

# Ride id Peloton uses for workouts without a class (for example Just Ride).
NO_CLASS_RIDE_ID = "0" * 32
