"""Shared request building and error mapping for the sync and async clients."""

import math
import re
from typing import Any, List, Optional, Sequence, Tuple

from .exceptions import (
    APIError,
    AuthenticationError,
    InsufficientCreditsError,
    NotFoundError,
    RateLimitError,
    ServerError,
    SubscriptionError,
    ValidationError,
)

Params = List[Tuple[str, str]]

_CREDITS_REMAINING = re.compile(r"you have (\d+) remaining")


def credits_for_odds(market_types: Sequence[str], bookmakers: Sequence[str]) -> int:
    """market_types x ceil(bookmakers / 5), matching the API."""
    return len(market_types) * math.ceil(len(bookmakers) / 5)


def odds_params(
    api_key: str, market_types: Sequence[str], bookmakers: Sequence[str]
) -> Params:
    """Both are repeated singular query params, not comma separated lists."""
    params: Params = [("api_key", api_key)]
    params.extend(("market_type", m) for m in market_types)
    params.extend(("bookmaker", b) for b in bookmakers)
    return params


def results_params(
    api_key: str,
    status: str,
    include: Sequence[str],
    game_id: Optional[str],
    round_number: Optional[int],
    days: Optional[int],
) -> Params:
    params: Params = [("api_key", api_key), ("status", status), ("include", ",".join(include))]
    if game_id is not None:
        # Stored as an int but compared as a string on the way in.
        params.append(("game_id", str(game_id)))
    if round_number is not None:
        params.append(("round", str(round_number)))
    if days is not None:
        params.append(("days", str(days)))
    return params


def _detail(status_code: int, body: Any) -> str:
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)
    return f"HTTP {status_code}"


def error_for_response(status_code: int, body: Any) -> APIError:
    """Map an error response onto an exception class.

    429 covers both rate limiting and running out of credits, so the two are
    told apart by the message the API sends back.
    """
    message = _detail(status_code, body)

    if status_code == 401:
        return AuthenticationError(message, status_code)
    if status_code == 403:
        return SubscriptionError(message, status_code)
    if status_code == 404:
        return NotFoundError(message, status_code)
    if status_code in (400, 422):
        return ValidationError(message, status_code)
    if status_code == 429:
        if "credit" in message.lower():
            match = _CREDITS_REMAINING.search(message)
            remaining = int(match.group(1)) if match else None
            return InsufficientCreditsError(message, status_code, remaining)
        return RateLimitError(message, status_code)
    if status_code >= 500:
        return ServerError(message, status_code)
    return APIError(message, status_code)


def retry_delay(attempt: int) -> float:
    """1s, 2s, 4s, capped at 30s."""
    return min(2.0**attempt, 30.0)
