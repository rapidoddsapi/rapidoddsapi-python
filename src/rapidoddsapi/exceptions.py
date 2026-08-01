from typing import Optional


class RapidOddsAPIError(Exception):
    """Base class for every error raised by this library."""


class APIError(RapidOddsAPIError):
    """The API returned an error response."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthenticationError(APIError):
    """401. The key is missing, malformed, or not recognised."""


class SubscriptionError(APIError):
    """403. The key is valid but the subscription is not active."""


class NotFoundError(APIError):
    """404. Unknown sport."""


class ValidationError(APIError):
    """400 or 422. A parameter was missing or invalid."""


class QuotaError(APIError):
    """429. Catch this to handle both rate limiting and credit exhaustion."""


class RateLimitError(QuotaError):
    """429. More than 30 requests per second on this key. Retryable."""


class InsufficientCreditsError(QuotaError):
    """429. Not enough credits for this request. Retrying will not help."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        credits_remaining: Optional[int] = None,
    ) -> None:
        super().__init__(message, status_code)
        self.credits_remaining = credits_remaining


class ServerError(APIError):
    """5xx."""


class NetworkError(RapidOddsAPIError):
    """The request never got a response: timeout, DNS failure, connection reset."""


class StreamError(RapidOddsAPIError):
    """The WebSocket stream failed."""


class StreamAuthError(StreamError):
    """The stream was rejected at the handshake.

    Either the key is invalid or the plan does not include WebSocket access,
    which is Pro and Elite only. Reconnecting will not help.
    """
