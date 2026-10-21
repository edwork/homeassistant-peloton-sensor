"""Exceptions raised by the Peloton API client."""


class PelotonError(Exception):
    """Base error, also raised for unexpected responses (for example a 404)."""


class PelotonAuthError(PelotonError):
    """Credentials or refresh token were rejected; the user has to log in again."""


class PelotonMfaRequiredError(PelotonAuthError):
    """Login needs multi-factor authentication, which this client does not support."""


class PelotonConnectionError(PelotonError):
    """Peloton could not be reached or returned a server error; try again later."""


class PelotonRateLimitError(PelotonConnectionError):
    """Peloton or Cloudflare rate limited the request."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        """Store the server's Retry-After value in seconds, when it sent one."""
        super().__init__(message)
        self.retry_after = retry_after
