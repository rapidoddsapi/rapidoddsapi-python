import asyncio
from types import TracebackType
from typing import Any, AsyncIterator, Dict, Optional, Sequence, Type, TypeVar, cast

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


class AsyncRapidOddsAPI:
    """Asynchronous client. Same methods and arguments as `RapidOddsAPI`.

        async with AsyncRapidOddsAPI(api_key="oa_your_api_key_here") as client:
            games = await client.get_odds("AFL", ["head_to_head"], ["Sportsbet"])
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
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def credits_used(self) -> int:
        """Credits this client has spent since it was created. See `RapidOddsAPI`."""
        return self._credits_used

    async def get_odds(
        self,
        sport: str,
        market_types: Sequence[str],
        bookmakers: Sequence[str],
    ) -> OddsResponse:
        if not market_types:
            raise ValidationError("market_types cannot be empty.")
        if not bookmakers:
            raise ValidationError("bookmakers cannot be empty.")

        data: OddsResponse = await self._request(
            f"/sports/{sport}/markets", odds_params(self.api_key, market_types, bookmakers)
        )
        if data.get("games"):
            self._credits_used += credits_for_odds(market_types, bookmakers)
        return data

    async def get_results(
        self,
        sport: str,
        *,
        status: str = "all",
        include: Sequence[str] = RESULTS_INCLUDES,
        game_id: Optional[str] = None,
        round_number: Optional[int] = None,
        days: Optional[int] = None,
    ) -> ResultsResponse:
        data: ResultsResponse = await self._request(
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
    ) -> AsyncIterator[OddsUpdate]:
        """Odds pushed as each scrape cycle completes. Pro and Elite only.

            async for update in client.stream_odds("AFL", ["head_to_head"], ["Sportsbet"]):
                print(update["data"]["games"])
        """
        subscribe: Dict[str, Any] = {
            "action": "subscribe",
            "sport": sport,
            "bookmakers": list(bookmakers),
            "market_types": list(market_types),
        }
        return self._counted(
            cast(
                AsyncIterator[OddsUpdate],
                ws_stream.stream(ODDS_WS_URL, self.api_key, subscribe, "odds_update", **options),
            )
        )

    def stream_results(
        self,
        sport: str,
        *,
        status: str = "all",
        include: Sequence[str] = RESULTS_INCLUDES,
        days: Optional[int] = None,
        **options: Any,
    ) -> AsyncIterator[ResultsUpdate]:
        """Scores and player stats pushed as each scrape cycle completes."""
        subscribe: Dict[str, Any] = {
            "action": "subscribe",
            "sport": sport,
            "status": status,
            "include": list(include),
        }
        if days is not None:
            subscribe["days"] = days

        return self._counted(
            cast(
                AsyncIterator[ResultsUpdate],
                ws_stream.stream(
                    RESULTS_WS_URL, self.api_key, subscribe, "results_update", **options
                ),
            )
        )

    async def _counted(self, updates: AsyncIterator[T]) -> AsyncIterator[T]:
        """Add each push to the running total. The server reports what it
        charged, so unlike the REST estimate this is the real number."""
        async for update in updates:
            self._credits_used += update.get("credits_charged", 0)  # type: ignore[attr-defined]
            yield update

    async def _request(self, path: str, params: Any) -> Any:
        url = f"{self.base_url}{path}"
        last_error: Exception

        for attempt in range(self.max_retries):
            try:
                response = await self._client.get(url, params=params)
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
                await asyncio.sleep(retry_delay(attempt))

        raise last_error

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncRapidOddsAPI":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()


def _body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
