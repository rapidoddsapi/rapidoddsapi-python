from datetime import timezone

import pytest

from rapidoddsapi import (
    ValidationError,
    find_arbitrage,
    find_value_bets,
    group_games,
    parse_time,
)


def entry(home, away, commence_time, bookmaker, prices, market="head_to_head"):
    return {
        "game": {"commence_time": commence_time, "home_team": home, "away_team": away},
        "bookmakers": [
            {
                "name": bookmaker,
                "last_update": commence_time,
                "markets": [
                    {
                        "key": market,
                        "outcomes": [
                            {"name": name, "price": price} for name, price in prices.items()
                        ],
                    }
                ],
            }
        ],
    }


class TestParseTime:
    def test_naive_timestamps_are_utc(self):
        parsed = parse_time("2026-07-23T09:30:00")
        assert parsed.tzinfo is timezone.utc
        assert parsed.hour == 9

    def test_offset_is_converted_to_utc(self):
        assert parse_time("2026-07-23T19:30:00+10:00").hour == 9

    def test_trailing_z(self):
        assert parse_time("2026-07-23T09:30:00Z").tzinfo is timezone.utc


class TestGroupGames:
    def test_books_listing_the_same_game_merge(self):
        response = {
            "sport": "MLB",
            "games": [
                entry("Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365", {"Red Sox": 2.0}),
                entry("Red Sox", "Blue Jays", "2026-07-04T17:11:00", "Sportsbet", {"Red Sox": 2.1}),
            ],
        }
        grouped = group_games(response)
        assert len(grouped) == 1
        assert len(grouped[0]["bookmakers"]) == 2

    def test_doubleheader_stays_separate(self):
        response = {
            "sport": "MLB",
            "games": [
                entry("Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365", {"Red Sox": 2.0}),
                entry("Red Sox", "Blue Jays", "2026-07-04T21:35:00", "Bet365", {"Red Sox": 2.4}),
            ],
        }
        assert len(group_games(response)) == 2

    def test_window_is_configurable(self):
        response = {
            "sport": "MLB",
            "games": [
                entry("Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365", {"Red Sox": 2.0}),
                entry("Red Sox", "Blue Jays", "2026-07-04T21:35:00", "TAB", {"Red Sox": 2.4}),
            ],
        }
        assert len(group_games(response, window_hours=6.0)) == 1

    def test_empty_response(self):
        assert group_games({"sport": "AFL", "games": []}) == []


class TestFindArbitrage:
    @pytest.fixture
    def arb_response(self):
        return {
            "sport": "MLB",
            "games": [
                entry(
                    "Red Sox",
                    "Blue Jays",
                    "2026-07-04T17:05:00",
                    "Bet365",
                    {"Blue Jays": 2.18, "Red Sox": 1.80},
                ),
                entry(
                    "Red Sox",
                    "Blue Jays",
                    "2026-07-04T17:05:00",
                    "Sportsbet",
                    {"Blue Jays": 1.75, "Red Sox": 2.02},
                ),
            ],
        }

    def test_finds_the_cross_book_arb(self, arb_response):
        arbs = find_arbitrage(arb_response)
        assert len(arbs) == 1

        arb = arbs[0]
        assert arb["profit_percent"] == pytest.approx(4.85, abs=0.01)
        assert {leg["bookmaker"] for leg in arb["legs"]} == {"Bet365", "Sportsbet"}

    def test_stakes_split_to_an_equal_return(self, arb_response):
        legs = find_arbitrage(arb_response, stake=100.0)[0]["legs"]
        returns = [leg["stake"] * leg["price"] for leg in legs]
        assert returns[0] == pytest.approx(returns[1], abs=0.05)
        assert sum(leg["stake"] for leg in legs) == pytest.approx(100.0, abs=0.02)

    def test_min_profit_filters(self, arb_response):
        assert find_arbitrage(arb_response, min_profit=10.0) == []

    def test_no_arb_within_one_book(self):
        response = {
            "sport": "MLB",
            "games": [
                entry(
                    "Red Sox",
                    "Blue Jays",
                    "2026-07-04T17:05:00",
                    "Bet365",
                    {"Blue Jays": 2.18, "Red Sox": 2.02},
                )
            ],
        }
        assert find_arbitrage(response) == []


class TestUnsupportedMarkets:
    """An empty list would read as 'no opportunities', so these raise instead."""

    @pytest.fixture
    def three_way(self):
        return {
            "sport": "EPL",
            "games": [
                entry(
                    "Arsenal",
                    "Chelsea",
                    "2026-07-04T17:05:00",
                    "Bet365",
                    {"Arsenal": 2.5, "Draw": 3.4, "Chelsea": 3.0},
                    market="head_to_head_3_way",
                )
            ],
        }

    @pytest.fixture
    def totals(self):
        return {
            "sport": "MLB",
            "games": [
                {
                    "game": {
                        "commence_time": "2026-07-04T17:05:00",
                        "home_team": "Red Sox",
                        "away_team": "Blue Jays",
                    },
                    "bookmakers": [
                        {
                            "name": "Bet365",
                            "last_update": "2026-07-04T16:00:00",
                            "markets": [
                                {
                                    "key": "alternate_total_runs",
                                    "outcomes": [
                                        {"name": "Over", "price": 1.9, "point": 8.5},
                                        {"name": "Under", "price": 1.9, "point": 8.5},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }

    def test_three_way_rejected(self, three_way):
        with pytest.raises(ValidationError, match="three way"):
            find_arbitrage(three_way, market="head_to_head_3_way")

    def test_line_market_rejected(self, totals):
        with pytest.raises(ValidationError, match="carries a line"):
            find_arbitrage(totals, market="alternate_total_runs")

    def test_value_bets_rejects_too(self, totals):
        with pytest.raises(ValidationError, match="carries a line"):
            find_value_bets(totals, sharp="Bet365", market="alternate_total_runs")

    def test_absent_market_is_not_an_error(self):
        """A book not offering the market is a legitimate empty result."""
        response = {
            "sport": "MLB",
            "games": [
                entry("Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365",
                      {"Red Sox": 2.0, "Blue Jays": 2.0})
            ],
        }
        assert find_arbitrage(response, market="draw_no_bet") == []


class TestFindValueBets:
    @pytest.fixture
    def ev_response(self):
        return {
            "sport": "WORLD_CUP",
            "games": [
                entry(
                    "New Zealand",
                    "Egypt",
                    "2026-07-04T17:05:00",
                    "Pinnacle",
                    {"New Zealand": 4.17, "Egypt": 1.253},
                    market="draw_no_bet",
                ),
                entry(
                    "New Zealand",
                    "Egypt",
                    "2026-07-04T17:05:00",
                    "Sportsbet",
                    {"New Zealand": 4.45, "Egypt": 1.20},
                    market="draw_no_bet",
                ),
            ],
        }

    def test_finds_the_price_beating_fair_value(self, ev_response):
        bets = find_value_bets(ev_response, market="draw_no_bet")
        assert len(bets) == 1

        bet = bets[0]
        assert bet["selection"] == "New Zealand"
        assert bet["bookmaker"] == "Sportsbet"
        assert bet["edge_percent"] == pytest.approx(2.8, abs=0.1)
        assert bet["fair_price"] == pytest.approx(4.33, abs=0.01)

    def test_sharp_book_is_not_compared_to_itself(self, ev_response):
        assert all(bet["bookmaker"] != "Pinnacle" for bet in find_value_bets(ev_response,
                                                                             market="draw_no_bet"))

    def test_min_edge_filters(self, ev_response):
        assert find_value_bets(ev_response, market="draw_no_bet", min_edge=5.0) == []

    def test_no_sharp_book_means_no_baseline(self, ev_response):
        assert find_value_bets(ev_response, sharp="DraftKings", market="draw_no_bet") == []
