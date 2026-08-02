"""Official Python SDK for RapidOddsAPI.

    from rapidoddsapi import RapidOddsAPI

    client = RapidOddsAPI(api_key="oa_your_api_key_here")
    odds = client.get_odds("AFL", ["head_to_head"], ["Sportsbet", "TAB"])

Docs: https://rapidoddsapi.com/docs
"""

from .async_client import AsyncRapidOddsAPI
from .client import RapidOddsAPI
from .constants import (
    AU_BOOKMAKERS,
    BOOKMAKERS,
    EU_BOOKMAKERS,
    RESULTS_SPORTS,
    SPORTS,
    UPCOMING_SPORTS,
    US_BOOKMAKERS,
)
from .exceptions import (
    APIError,
    AuthenticationError,
    InsufficientCreditsError,
    NetworkError,
    NotFoundError,
    QuotaError,
    RapidOddsAPIError,
    RateLimitError,
    ServerError,
    StreamAuthError,
    StreamError,
    SubscriptionError,
    ValidationError,
)
from .helpers import find_arbitrage, find_value_bets, group_games, parse_time

__version__ = "0.2.0"

__all__ = [
    "RapidOddsAPI",
    "AsyncRapidOddsAPI",
    "SPORTS",
    "UPCOMING_SPORTS",
    "RESULTS_SPORTS",
    "BOOKMAKERS",
    "AU_BOOKMAKERS",
    "US_BOOKMAKERS",
    "EU_BOOKMAKERS",
    "find_arbitrage",
    "find_value_bets",
    "group_games",
    "parse_time",
    "RapidOddsAPIError",
    "APIError",
    "AuthenticationError",
    "SubscriptionError",
    "NotFoundError",
    "ValidationError",
    "QuotaError",
    "RateLimitError",
    "InsufficientCreditsError",
    "ServerError",
    "NetworkError",
    "StreamError",
    "StreamAuthError",
    "__version__",
]
