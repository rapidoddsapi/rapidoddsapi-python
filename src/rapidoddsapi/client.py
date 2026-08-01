import asyncio
import time
from types import TracebackType
from typing import Any, AsyncIterator, Dict, Iterator, Optional, Sequence, Type, TypeVar

import httpx

from . import websocket as ws_stream
from ._http import (
    credits_for_odds,
    error_for_response,
    odds_params,
    results_params,
    retry_delay,
)
from .constants import (
    BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    ODDS_WS_URL,
    RESULTS_INCLUDES,
    RESULTS_WS_URL,
)
from .exceptions import (
    AuthenticationError,
    NetworkError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from .types import OddsResponse, OddsUpdate, ResultsResponse, ResultsUpdate

T = TypeVar("T")


class RapidOddsAPI:
    """Synchronous client for the odds and results APIs.

    Both APIs take the same `oa_` key.

        client = RapidOddsAPI(api_key="oa_your_api_key_here")
        games = client.get_odds("AFL", ["head_to_head"], ["Sportsbet", "TAB"])
    """

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_url: str = BASE_URL,
    ) -> None:
        if not api_key or not api_key.startswith("oa_"):
            raise AuthenticationError("API keys start with 'oa_'. Find yours in your dashboard.")

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._credits_used = 0
        self._client = httpx.Client(timeout=timeout)

    @property
    def credits_used(self) -> int:
        """Credits this client has spent since it was created.

        Counted locally using the same formula as the API, and only when a call
        returns games, since empty responses are free. It does not know about
        spend from other processes or earlier runs.
        """
        return self._credits_used

    def get_odds(
        self,
        sport: str,
        market_types: Sequence[str],
        bookmakers: Sequence[str],
    ) -> OddsResponse:
        """Odds for one sport.

        Both lists are required by the API. Cost is
        `len(market_types) x ceil(len(bookmakers) / 5)` credits, charged only if
        games come back.
        """
        if not market_types:
            raise ValidationError("market_types cannot be empty.")
        if not bookmakers:
            raise ValidationError("bookmakers cannot be empty.")

        data: OddsResponse = self._request(
            f"/sports/{sport}/markets", odds_params(self.api_key, market_types, bookmakers)
        )
        if data.get("games"):
            self._credits_used += credits_for_odds(market_types, bookmakers)
        return data

    def get_results(
        self,
        sport: str,
        *,
        status: str = "all",
        include: Sequence[str] = RESULTS_INCLUDES,
        game_id: Optional[str] = None,
        round_number: Optional[int] = None,
        days: Optional[int] = None,
    ) -> ResultsResponse:
        """Live scores and player stats for one sport.

        Costs 1 credit, charged only if games come back. An unknown `game_id`
        is not an error, it returns an empty list.
        """
        data: ResultsResponse = self._request(
            f"/results/{sport}",
            results_params(self.api_key, status, include, game_id, round_number, days),
        )
        if data.get("games"):
            self._credits_used += 1
        return data

    def stream_odds(
        self,
        sport: str,
        market_types: Sequence[str],
        bookmakers: Sequence[str],
        **options: Any,
    ) -> Iterator[OddsUpdate]:
        """Odds pushed as each scrape cycle completes. Pro and Elite only.

            for update in client.stream_odds("AFL", ["head_to_head"], ["Sportsbet"]):
                print(update["data"]["games"])

        Reconnects and re-subscribes on its own. Each push costs the same as the
        equivalent REST call.
        """
        subscribe: Dict[str, Any] = {
            "action": "subscribe",
            "sport": sport,
            "bookmakers": list(bookmakers),
            "market_types": list(market_types),
        }
        source: AsyncIterator[OddsUpdate] = ws_stream.stream(  # type: ignore[assignment]
            ODDS_WS_URL, self.api_key, subscribe, "odds_update", **options
        )
        return self._counted(_iter_sync(source))

    def stream_results(
        self,
        sport: str,
        *,
        status: str = "all",
        include: Sequence[str] = RESULTS_INCLUDES,
        days: Optional[int] = None,
        **options: Any,
    ) -> Iterator[ResultsUpdate]:
        """Scores and player stats pushed as each scrape cycle completes.

        Pro and Elite only. 1 credit per push.
        """
        subscribe: Dict[str, Any] = {
            "action": "subscribe",
            "sport": sport,
            "status": status,
            "include": list(include),
        }
        if days is not None:
            subscribe["days"] = days

        source: AsyncIterator[ResultsUpdate] = ws_stream.stream(  # type: ignore[assignment]
            RESULTS_WS_URL, self.api_key, subscribe, "results_update", **options
        )
        return self._counted(_iter_sync(source))

    def _counted(self, updates: Iterator[T]) -> Iterator[T]:
        """Add each push to the running total. The server reports what it
        charged, so unlike the REST estimate this is the real number."""
        for update in updates:
            self._credits_used += update.get("credits_charged", 0)  # type: ignore[attr-defined]
            yield update

    def _request(self, path: str, params: Any) -> Any:
        url = f"{self.base_url}{path}"
        last_error: Exception

        for attempt in range(self.max_retries):
            try:
                response = self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_error = NetworkError(f"Request to {url} failed: {exc}")
            else:
                if response.status_code < 400:
                    return response.json()

                error = error_for_response(response.status_code, _body(response))
                if not isinstance(error, (RateLimitError, ServerError)):
                    raise error
                last_error = error

            if attempt < self.max_retries - 1:
                time.sleep(retry_delay(attempt))

        raise last_error

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RapidOddsAPI":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()


def _body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _iter_sync(source: AsyncIterator[T]) -> Iterator[T]:
    """Drive an async generator from sync code on a private event loop."""
    loop = asyncio.new_event_loop()
    try:
        while True:
            try:
                yield loop.run_until_complete(source.__anext__())
            except StopAsyncIteration:
                return
    finally:
        loop.run_until_complete(source.aclose())  # type: ignore[attr-defined]
        loop.close()
