"""WebSocket streaming with automatic reconnect.

Both feeds follow the same protocol: connect with the key on the query string,
receive a `connected` event, send one `subscribe` message per sport, then
receive an update event every time a scrape cycle finishes.

A dropped connection starts with no subscriptions, so the subscribe message is
replayed on every reconnect.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Optional
from urllib.parse import quote

import websockets
from websockets.exceptions import ConnectionClosed, InvalidHandshake, WebSocketException

from .exceptions import InsufficientCreditsError, StreamAuthError, StreamError

AUTH_CLOSE_CODE = 4001


def _handshake_status(exc: Exception) -> Optional[int]:
    """websockets renamed this exception between versions."""
    response = getattr(exc, "response", None)
    if response is not None:
        return getattr(response, "status_code", None)
    return getattr(exc, "status_code", None)


def _auth_failure(exc: Exception) -> bool:
    """Rejected at the handshake, or closed with the server's auth code.

    Closing a connection before accepting it turns into an HTTP 403 on the
    handshake rather than a close frame, so both shapes mean the same thing:
    the key is invalid, or the plan does not include WebSocket access.
    """
    if isinstance(exc, ConnectionClosed):
        return exc.code == AUTH_CLOSE_CODE
    return _handshake_status(exc) == 403


def _raise_for_event(message: Dict[str, Any]) -> None:
    if message.get("event") != "error":
        return
    detail = str(message.get("message", "Stream error"))
    if "credit" in detail.lower():
        raise InsufficientCreditsError(detail)
    raise StreamError(detail)


async def stream(
    url: str,
    api_key: str,
    subscribe: Dict[str, Any],
    update_event: str,
    *,
    reconnect: bool = True,
    max_reconnect_attempts: Optional[int] = None,
    initial_backoff: float = 1.0,
    max_backoff: float = 30.0,
) -> AsyncIterator[Dict[str, Any]]:
    """Yield update events, reconnecting until told otherwise.

    `max_reconnect_attempts` counts consecutive failures. A successful
    connection resets it, so a stream that runs for a week and drops nightly
    never exhausts its budget.
    """
    endpoint = f"{url}?api_key={quote(api_key, safe='')}"
    attempts = 0

    while True:
        try:
            async with websockets.connect(endpoint) as ws:
                attempts = 0
                await ws.send(json.dumps(subscribe))

                async for raw in ws:
                    message = json.loads(raw)
                    _raise_for_event(message)
                    if message.get("event") == update_event:
                        yield message

        except (ConnectionClosed, InvalidHandshake, WebSocketException, OSError) as exc:
            if _auth_failure(exc):
                raise StreamAuthError(
                    "WebSocket rejected. Check the key is valid and the plan includes "
                    "WebSocket access, which is Pro and Elite only."
                ) from exc
            if not reconnect:
                raise StreamError(f"Stream closed: {exc}") from exc
            if max_reconnect_attempts is not None and attempts >= max_reconnect_attempts:
                raise StreamError(
                    f"Stream closed after {attempts} reconnect attempts: {exc}"
                ) from exc

            delay = min(initial_backoff * (2**attempts), max_backoff)
            attempts += 1
            await asyncio.sleep(delay)
