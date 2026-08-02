import httpx
import pytest
import respx

from rapidoddsapi import (
    AsyncRapidOddsAPI,
    AuthenticationError,
    InsufficientCreditsError,
    NotFoundError,
    QuotaError,
    RapidOddsAPI,
    RateLimitError,
    ServerError,
    SubscriptionError,
    ValidationError,
)

KEY = "oa_your_api_key_here"
ODDS_URL = "https://api.rapidoddsapi.com/sports/AFL/markets"
RESULTS_URL = "https://api.rapidoddsapi.com/results/AFL"
SPORTS_URL = "https://api.rapidoddsapi.com/sports"
RESULTS_SPORTS_URL = "https://api.rapidoddsapi.com/results/sports"
USAGE_URL = "https://api.rapidoddsapi.com/usage"

SPORTS_LIGHT = [{"id": "AFL", "name": "AFL"}, {"id": "MLB", "name": "MLB"}]

ONE_SPORT = {
    "id": "AFL",
    "name": "AFL",
    "markets": {
        "game": ["head_to_head", "alternate_lines"],
        "team": ["alternate_team_total_points"],
        "player_props": ["player_disposals"],
    },
}

USAGE = {
    "tier": "free",
    "status": "active",
    "credits_used": 37,
    "credits_limit": 250,
    "credits_remaining": 213,
    "resets": False,
}

ONE_GAME = {
    "sport": "AFL",
    "games": [
        {
            "game": {
                "commence_time": "2026-07-23T09:30:00",
                "home_team": "Adelaide Crows",
                "away_team": "Collingwood",
            },
            "bookmakers": [
                {
                    "name": "Sportsbet",
                    "last_update": "2026-07-23T09:00:00",
                    "markets": [
                        {
                            "key": "head_to_head",
                            "outcomes": [
                                {"name": "Adelaide Crows", "price": 2.4},
                                {"name": "Collingwood", "price": 1.6},
                            ],
                        }
                    ],
                }
            ],
        }
    ],
}

EMPTY = {"sport": "AFL", "games": []}


@pytest.fixture
def client():
    with RapidOddsAPI(KEY, max_retries=1) as c:
        yield c


class TestKeyValidation:
    @pytest.mark.parametrize("key", ["", "sk_wrong_prefix", "your_api_key"])
    def test_rejected_before_any_request(self, key):
        with pytest.raises(AuthenticationError):
            RapidOddsAPI(key)

    def test_async_client_too(self):
        with pytest.raises(AuthenticationError):
            AsyncRapidOddsAPI("nope")


class TestGetOdds:
    @respx.mock
    def test_sends_repeated_singular_params(self, client):
        route = respx.get(ODDS_URL).mock(return_value=httpx.Response(200, json=ONE_GAME))

        client.get_odds("AFL", ["head_to_head", "alternate_lines"], ["Sportsbet", "TAB"])

        params = route.calls.last.request.url.params
        assert params.get_list("market_type") == ["head_to_head", "alternate_lines"]
        assert params.get_list("bookmaker") == ["Sportsbet", "TAB"]
        assert params["api_key"] == KEY

    @respx.mock
    def test_returns_the_payload(self, client):
        respx.get(ODDS_URL).mock(return_value=httpx.Response(200, json=ONE_GAME))
        assert client.get_odds("AFL", ["head_to_head"], ["Sportsbet"]) == ONE_GAME

    @pytest.mark.parametrize(
        "market_types,bookmakers",
        [([], ["Sportsbet"]), (["head_to_head"], [])],
    )
    def test_empty_lists_rejected_locally(self, client, market_types, bookmakers):
        with pytest.raises(ValidationError):
            client.get_odds("AFL", market_types, bookmakers)


class TestCreditTracking:
    @respx.mock
    def test_counts_the_api_formula(self, client):
        respx.get(ODDS_URL).mock(return_value=httpx.Response(200, json=ONE_GAME))

        client.get_odds("AFL", ["head_to_head", "alternate_lines"], ["a", "b", "c", "d", "e", "f"])

        # 2 market types x ceil(6 / 5) = 4
        assert client.credits_used == 4

    @respx.mock
    def test_empty_responses_are_free(self, client):
        respx.get(ODDS_URL).mock(return_value=httpx.Response(200, json=EMPTY))

        client.get_odds("AFL", ["head_to_head"], ["Sportsbet"])
        assert client.credits_used == 0

    @respx.mock
    def test_results_cost_one(self, client):
        respx.get(RESULTS_URL).mock(
            return_value=httpx.Response(200, json={"sport": "AFL", "games": [{"game": {}}]})
        )

        client.get_results("AFL")
        assert client.credits_used == 1


class TestResultsParams:
    @respx.mock
    def test_defaults(self, client):
        route = respx.get(RESULTS_URL).mock(return_value=httpx.Response(200, json=EMPTY))

        client.get_results("AFL")

        params = route.calls.last.request.url.params
        assert params["status"] == "all"
        assert params["include"] == "scores,players"

    @respx.mock
    def test_optional_filters(self, client):
        route = respx.get(RESULTS_URL).mock(return_value=httpx.Response(200, json=EMPTY))

        client.get_results("AFL", status="live", include=["scores"], game_id="8216",
                           round_number=20, days=2)

        params = route.calls.last.request.url.params
        assert params["status"] == "live"
        assert params["include"] == "scores"
        assert params["game_id"] == "8216"
        assert params["round"] == "20"
        assert params["days"] == "2"

    @respx.mock
    def test_int_game_id_is_stringified(self, client):
        route = respx.get(RESULTS_URL).mock(return_value=httpx.Response(200, json=EMPTY))

        client.get_results("AFL", game_id=8216)

        assert route.calls.last.request.url.params["game_id"] == "8216"


class TestMetadata:
    """The sport directory and credit balance. None of these cost anything."""

    @respx.mock
    def test_list_sports_asks_for_the_light_list(self, client):
        route = respx.get(SPORTS_URL).mock(return_value=httpx.Response(200, json=SPORTS_LIGHT))

        assert client.list_sports() == SPORTS_LIGHT

        params = route.calls.last.request.url.params
        assert "markets" not in params
        assert "sport" not in params

    @respx.mock
    def test_list_sports_can_include_markets(self, client):
        route = respx.get(SPORTS_URL).mock(return_value=httpx.Response(200, json=SPORTS_LIGHT))

        client.list_sports(markets=True)

        assert route.calls.last.request.url.params["markets"] == "true"

    @respx.mock
    def test_get_sport_includes_markets_by_default(self, client):
        route = respx.get(SPORTS_URL).mock(return_value=httpx.Response(200, json=ONE_SPORT))

        assert client.get_sport("AFL") == ONE_SPORT

        params = route.calls.last.request.url.params
        assert params["sport"] == "AFL"
        assert params["markets"] == "true"

    @respx.mock
    def test_unknown_sport_raises(self, client):
        respx.get(SPORTS_URL).mock(
            return_value=httpx.Response(404, json={"detail": "Sport 'XYZ' not found."})
        )

        with pytest.raises(NotFoundError):
            client.get_sport("XYZ")

    @respx.mock
    def test_list_results_sports(self, client):
        respx.get(RESULTS_SPORTS_URL).mock(
            return_value=httpx.Response(200, json=SPORTS_LIGHT)
        )

        assert client.list_results_sports() == SPORTS_LIGHT

    @respx.mock
    def test_get_usage(self, client):
        respx.get(USAGE_URL).mock(return_value=httpx.Response(200, json=USAGE))

        assert client.get_usage() == USAGE

    @respx.mock
    def test_none_of_it_costs_credits(self, client):
        respx.get(SPORTS_URL).mock(return_value=httpx.Response(200, json=SPORTS_LIGHT))
        respx.get(RESULTS_SPORTS_URL).mock(return_value=httpx.Response(200, json=SPORTS_LIGHT))
        respx.get(USAGE_URL).mock(return_value=httpx.Response(200, json=USAGE))

        client.list_sports(markets=True)
        client.get_sport("AFL")
        client.list_results_sports()
        client.get_usage()

        assert client.credits_used == 0


class TestErrorMapping:
    @pytest.mark.parametrize(
        "status,detail,expected",
        [
            (401, "Invalid API key.", AuthenticationError),
            (403, "Subscription is not active.", SubscriptionError),
            (404, "Sport 'XYZ' not found.", NotFoundError),
            (400, "Invalid include value(s): score.", ValidationError),
            (422, "field required", ValidationError),
        ],
    )
    @respx.mock
    def test_status_codes(self, client, status, detail, expected):
        respx.get(ODDS_URL).mock(return_value=httpx.Response(status, json={"detail": detail}))

        with pytest.raises(expected):
            client.get_odds("AFL", ["head_to_head"], ["Sportsbet"])

    @respx.mock
    def test_429_out_of_credits(self, client):
        respx.get(ODDS_URL).mock(
            return_value=httpx.Response(
                429,
                json={
                    "detail": "Insufficient credits. This request costs 4 credits, "
                              "you have 2 remaining."
                },
            )
        )

        with pytest.raises(InsufficientCreditsError) as caught:
            client.get_odds("AFL", ["head_to_head"], ["Sportsbet"])

        assert caught.value.credits_remaining == 2
        assert caught.value.status_code == 429

    @respx.mock
    def test_429_rate_limited(self, client):
        respx.get(ODDS_URL).mock(
            return_value=httpx.Response(
                429, json={"detail": "Rate limit exceeded. Maximum 30 requests per second."}
            )
        )

        with pytest.raises(RateLimitError):
            client.get_odds("AFL", ["head_to_head"], ["Sportsbet"])

    @respx.mock
    def test_both_429s_share_a_parent(self, client):
        respx.get(ODDS_URL).mock(
            return_value=httpx.Response(429, json={"detail": "Insufficient credits, 0 remaining."})
        )

        with pytest.raises(QuotaError):
            client.get_odds("AFL", ["head_to_head"], ["Sportsbet"])


class TestRetries:
    @respx.mock
    def test_server_errors_are_retried(self):
        route = respx.get(ODDS_URL).mock(
            side_effect=[
                httpx.Response(500, json={"detail": "Error fetching market data."}),
                httpx.Response(200, json=ONE_GAME),
            ]
        )

        with RapidOddsAPI(KEY, max_retries=2) as client:
            assert client.get_odds("AFL", ["head_to_head"], ["Sportsbet"]) == ONE_GAME
        assert route.call_count == 2

    @respx.mock
    def test_gives_up_after_max_retries(self):
        respx.get(ODDS_URL).mock(return_value=httpx.Response(500, json={"detail": "boom"}))

        with RapidOddsAPI(KEY, max_retries=2) as client, pytest.raises(ServerError):
            client.get_odds("AFL", ["head_to_head"], ["Sportsbet"])

    @respx.mock
    def test_insufficient_credits_is_not_retried(self):
        route = respx.get(ODDS_URL).mock(
            return_value=httpx.Response(429, json={"detail": "Insufficient credits, 0 remaining."})
        )

        with RapidOddsAPI(KEY, max_retries=3) as client, pytest.raises(InsufficientCreditsError):
            client.get_odds("AFL", ["head_to_head"], ["Sportsbet"])
        assert route.call_count == 1

    @respx.mock
    def test_client_errors_are_not_retried(self):
        route = respx.get(ODDS_URL).mock(
            return_value=httpx.Response(404, json={"detail": "Sport not found."})
        )

        with RapidOddsAPI(KEY, max_retries=3) as client, pytest.raises(NotFoundError):
            client.get_odds("AFL", ["head_to_head"], ["Sportsbet"])
        assert route.call_count == 1


class TestStreamCredits:
    """Pushes are charged too, and the server reports the exact amount."""

    @staticmethod
    def fake_stream(*pushes):
        async def stream(*args, **kwargs):
            for push in pushes:
                yield push

        return stream

    def test_sync_stream_counts_each_push(self, monkeypatch, client):
        monkeypatch.setattr(
            "rapidoddsapi.client.ws_stream.stream",
            self.fake_stream(
                {"event": "odds_update", "credits_charged": 2, "data": EMPTY},
                {"event": "odds_update", "credits_charged": 2, "data": EMPTY},
            ),
        )

        pushes = list(client.stream_odds("AFL", ["head_to_head"], ["Sportsbet"]))

        assert len(pushes) == 2
        assert client.credits_used == 4

    async def test_async_stream_counts_each_push(self, monkeypatch):
        monkeypatch.setattr(
            "rapidoddsapi.async_client.ws_stream.stream",
            self.fake_stream({"event": "results_update", "credits_charged": 1, "data": EMPTY}),
        )

        async with AsyncRapidOddsAPI(KEY) as c:
            async for _ in c.stream_results("AFL", status="live"):
                pass
            assert c.credits_used == 1


class TestAsyncClient:
    @respx.mock
    async def test_get_odds(self):
        respx.get(ODDS_URL).mock(return_value=httpx.Response(200, json=ONE_GAME))

        async with AsyncRapidOddsAPI(KEY, max_retries=1) as client:
            assert await client.get_odds("AFL", ["head_to_head"], ["Sportsbet"]) == ONE_GAME
            assert client.credits_used == 1

    @respx.mock
    async def test_errors_map_the_same_way(self):
        respx.get(ODDS_URL).mock(
            return_value=httpx.Response(401, json={"detail": "Invalid API key."})
        )

        async with AsyncRapidOddsAPI(KEY, max_retries=1) as client:
            with pytest.raises(AuthenticationError):
                await client.get_odds("AFL", ["head_to_head"], ["Sportsbet"])

    @respx.mock
    async def test_get_results(self):
        respx.get(RESULTS_URL).mock(return_value=httpx.Response(200, json=EMPTY))

        async with AsyncRapidOddsAPI(KEY, max_retries=1) as client:
            assert await client.get_results("AFL", status="live") == EMPTY

    @respx.mock
    async def test_metadata(self):
        respx.get(SPORTS_URL).mock(return_value=httpx.Response(200, json=SPORTS_LIGHT))
        respx.get(USAGE_URL).mock(return_value=httpx.Response(200, json=USAGE))

        async with AsyncRapidOddsAPI(KEY, max_retries=1) as client:
            assert await client.list_sports() == SPORTS_LIGHT
            assert await client.get_usage() == USAGE
            assert client.credits_used == 0
