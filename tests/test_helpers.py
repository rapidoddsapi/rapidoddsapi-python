from datetime import timezone

import pytest

from rapidoddsapi import (
    ValidationError,
    find_arbitrage,
    find_value_bets,
    group_games,
    parse_time,
)


def lined(home, away, commence_time, bookmaker, market, outcomes):
    """One bookmaker's prices on a market whose outcomes carry a line."""
    return {
        "game": {"commence_time": commence_time, "home_team": home, "away_team": away},
        "bookmakers": [
            {
                "name": bookmaker,
                "last_update": commence_time,
                "markets": [{"key": market, "outcomes": outcomes}],
            }
        ],
    }


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

    def test_the_window_comes_from_the_sport(self):
        """MLB gets 1.8 hours because of doubleheaders, everything else 6. The
        same two start times therefore split for MLB and merge for the AFL."""
        games = [
            entry("Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365", {"Red Sox": 2.0}),
            entry("Red Sox", "Blue Jays", "2026-07-04T21:35:00", "TAB", {"Red Sox": 2.4}),
        ]
        assert len(group_games({"sport": "MLB", "games": games})) == 2
        assert len(group_games({"sport": "AFL", "games": games})) == 1

    def test_a_split_doubleheader_stays_apart(self):
        """Three hours apart, which a flat four hour window would have merged."""
        response = {
            "sport": "MLB",
            "games": [
                entry("Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365", {"Red Sox": 2.0}),
                entry("Red Sox", "Blue Jays", "2026-07-04T20:05:00", "Bet365", {"Red Sox": 2.4}),
            ],
        }
        assert len(group_games(response)) == 2

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

    def test_three_way_rejected(self, three_way):
        with pytest.raises(ValidationError, match="three way"):
            find_arbitrage(three_way, market="head_to_head_3_way")

    def test_value_bets_reject_three_way_too(self, three_way):
        with pytest.raises(ValidationError, match="three way"):
            find_value_bets(three_way, devig="Bet365", market="head_to_head_3_way")

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
        assert find_value_bets(ev_response, devig="DraftKings", market="draw_no_bet") == []


class TestTotals:
    @pytest.fixture
    def totals(self):
        """An arb on the 8.5 line, and a 9.5 line carrying no arb.

        Crossing the two lines would look like a 15% arb on Over 9.5 against
        Under 8.5, which is not a bet, so the second line is what proves the
        grouping holds.
        """
        return {
            "sport": "MLB",
            "games": [
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365",
                    "alternate_total_runs",
                    [
                        {"name": "Over", "price": 2.10, "point": 8.5},
                        {"name": "Under", "price": 1.80, "point": 8.5},
                        {"name": "Over", "price": 2.50, "point": 9.5},
                        {"name": "Under", "price": 1.55, "point": 9.5},
                    ],
                ),
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Sportsbet",
                    "alternate_total_runs",
                    [
                        {"name": "Over", "price": 1.75, "point": 8.5},
                        {"name": "Under", "price": 2.15, "point": 8.5},
                        {"name": "Over", "price": 2.45, "point": 9.5},
                        {"name": "Under", "price": 1.57, "point": 9.5},
                    ],
                ),
            ],
        }

    def test_lines_are_not_crossed(self, totals):
        arbs = find_arbitrage(totals, market="alternate_total_runs")

        assert len(arbs) == 1
        assert arbs[0]["profit_percent"] == pytest.approx(6.24, abs=0.01)
        assert {leg["point"] for leg in arbs[0]["legs"]} == {8.5}

    def test_legs_carry_the_line(self, totals):
        legs = find_arbitrage(totals, market="alternate_total_runs")[0]["legs"]

        assert {(leg["team"], leg["point"]) for leg in legs} == {("Over", 8.5), ("Under", 8.5)}

    def test_value_is_priced_per_line(self):
        """Pinnacle is even money on 8.5 and shaded on 9.5. Devigging the two
        together would price both wrong."""
        response = {
            "sport": "MLB",
            "games": [
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Pinnacle",
                    "alternate_total_runs",
                    [
                        {"name": "Over", "price": 1.95, "point": 8.5},
                        {"name": "Under", "price": 1.95, "point": 8.5},
                        {"name": "Over", "price": 2.50, "point": 9.5},
                        {"name": "Under", "price": 1.55, "point": 9.5},
                    ],
                ),
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Sportsbet",
                    "alternate_total_runs",
                    [
                        {"name": "Over", "price": 2.10, "point": 8.5},
                        {"name": "Under", "price": 1.75, "point": 8.5},
                        {"name": "Over", "price": 2.55, "point": 9.5},
                    ],
                ),
            ],
        }
        bets = find_value_bets(response, market="alternate_total_runs")

        assert len(bets) == 1
        assert bets[0]["selection"] == "Over"
        assert bets[0]["point"] == 8.5
        assert bets[0]["edge_percent"] == pytest.approx(5.0, abs=0.01)

    def test_a_book_arbing_itself_is_not_a_fair_price(self):
        """Pinnacle's two prices sum under 1, which is a bad feed rather than a
        thin margin. Normalising it upwards would invent edge everywhere."""
        response = {
            "sport": "MLB",
            "games": [
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Pinnacle",
                    "alternate_total_runs",
                    [
                        {"name": "Over", "price": 2.10, "point": 8.5},
                        {"name": "Under", "price": 2.10, "point": 8.5},
                    ],
                ),
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Sportsbet",
                    "alternate_total_runs",
                    [{"name": "Over", "price": 2.20, "point": 8.5}],
                ),
            ],
        }
        assert find_value_bets(response, market="alternate_total_runs") == []


class TestSpreads:
    def test_a_team_is_paired_with_the_mirrored_line(self):
        response = {
            "sport": "MLB",
            "games": [
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365",
                    "alternate_lines",
                    [
                        {"name": "Red Sox", "price": 2.20, "point": -1.5},
                        {"name": "Blue Jays", "price": 1.70, "point": 1.5},
                    ],
                ),
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Sportsbet",
                    "alternate_lines",
                    [
                        {"name": "Red Sox", "price": 1.95, "point": -1.5},
                        {"name": "Blue Jays", "price": 1.95, "point": 1.5},
                    ],
                ),
            ],
        }
        arbs = find_arbitrage(response, market="alternate_lines")

        assert len(arbs) == 1
        assert arbs[0]["profit_percent"] == pytest.approx(3.37, abs=0.01)
        assert {(leg["team"], leg["point"]) for leg in arbs[0]["legs"]} == {
            ("Red Sox", -1.5),
            ("Blue Jays", 1.5),
        }

    def test_the_same_side_of_a_line_is_never_paired(self):
        """Books disagree on who is giving start. Red Sox -1.5 and Blue Jays
        -1.5 are both real bets and both win only if that team covers, so
        backing both is not an arb however the prices look."""
        response = {
            "sport": "MLB",
            "games": [
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365",
                    "alternate_lines",
                    [{"name": "Red Sox", "price": 2.20, "point": -1.5}],
                ),
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Sportsbet",
                    "alternate_lines",
                    [{"name": "Blue Jays", "price": 2.45, "point": -1.5}],
                ),
            ],
        }
        assert find_arbitrage(response, market="alternate_lines") == []

    def test_a_zero_handicap_is_ignored(self):
        """Level teams push a zero line, refunding both sides rather than one
        winning, so the pair is not a locked profit. Pinnacle quotes these as
        0.0 against -0.0."""
        response = {
            "sport": "MLB",
            "games": [
                lined(
                    "Baltimore Orioles", "Philadelphia Phillies", "2026-08-03T17:05:00",
                    "Pinnacle", "alternate_lines_1st_5_innings",
                    [{"name": "Baltimore Orioles", "price": 2.23, "point": 0.0}],
                ),
                lined(
                    "Baltimore Orioles", "Philadelphia Phillies", "2026-08-03T17:05:00",
                    "Dabble", "alternate_lines_1st_5_innings",
                    [{"name": "Philadelphia Phillies", "price": 2.10, "point": -0.0}],
                ),
            ],
        }
        assert find_arbitrage(response, market="alternate_lines_1st_5_innings") == []

    def test_value_devigs_the_pair_and_compares_the_exact_line(self):
        response = {
            "sport": "MLB",
            "games": [
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Pinnacle",
                    "alternate_lines",
                    [
                        {"name": "Red Sox", "price": 1.95, "point": -1.5},
                        {"name": "Blue Jays", "price": 1.95, "point": 1.5},
                    ],
                ),
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Sportsbet",
                    "alternate_lines",
                    [
                        {"name": "Red Sox", "price": 2.10, "point": -1.5},
                        {"name": "Blue Jays", "price": 1.75, "point": 1.5},
                    ],
                ),
            ],
        }
        bets = find_value_bets(response, market="alternate_lines")

        assert len(bets) == 1
        assert bets[0]["selection"] == "Red Sox"
        assert bets[0]["point"] == -1.5
        assert bets[0]["edge_percent"] == pytest.approx(5.0, abs=0.01)


class TestTeamTotals:
    def test_teams_are_not_crossed(self):
        """Red Sox Over against Blue Jays Under would price as a 7% arb. It is
        not a bet: both can land."""
        response = {
            "sport": "MLB",
            "games": [
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365",
                    "alternate_team_total_runs",
                    [
                        {"name": "Over", "price": 2.10, "point": 4.5, "team_name": "Red Sox"},
                        {"name": "Over", "price": 1.90, "point": 4.5, "team_name": "Blue Jays"},
                    ],
                ),
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Sportsbet",
                    "alternate_team_total_runs",
                    [
                        {"name": "Under", "price": 1.80, "point": 4.5, "team_name": "Red Sox"},
                        {"name": "Under", "price": 2.20, "point": 4.5, "team_name": "Blue Jays"},
                    ],
                ),
            ],
        }
        arbs = find_arbitrage(response, market="alternate_team_total_runs")

        assert len(arbs) == 1
        assert arbs[0]["profit_percent"] == pytest.approx(1.95, abs=0.01)
        assert {leg["team_name"] for leg in arbs[0]["legs"]} == {"Blue Jays"}


class TestPlayerProps:
    @pytest.fixture
    def props(self):
        """An arb on Judge. Devers is priced so that crossing the two players
        would beat it, putting a bet that does not exist at the top."""
        return {
            "sport": "MLB",
            "games": [
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365",
                    "batter_total_bases",
                    [
                        {"name": "Over", "price": 2.10, "point": 1.5,
                         "player_name": "Aaron Judge"},
                        {"name": "Under", "price": 1.80, "point": 1.5,
                         "player_name": "Aaron Judge"},
                        {"name": "Over", "price": 1.60, "point": 1.5,
                         "player_name": "Rafael Devers"},
                        {"name": "Under", "price": 2.30, "point": 1.5,
                         "player_name": "Rafael Devers"},
                    ],
                ),
                lined(
                    "Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Sportsbet",
                    "batter_total_bases",
                    [
                        {"name": "Over", "price": 1.75, "point": 1.5,
                         "player_name": "Aaron Judge"},
                        {"name": "Under", "price": 2.15, "point": 1.5,
                         "player_name": "Aaron Judge"},
                        {"name": "Over", "price": 1.62, "point": 1.5,
                         "player_name": "Rafael Devers"},
                        {"name": "Under", "price": 2.28, "point": 1.5,
                         "player_name": "Rafael Devers"},
                    ],
                ),
            ],
        }

    def test_players_are_not_crossed(self, props):
        arbs = find_arbitrage(props, market="batter_total_bases")

        assert len(arbs) == 1
        assert arbs[0]["profit_percent"] == pytest.approx(6.24, abs=0.01)
        assert {leg["player_name"] for leg in arbs[0]["legs"]} == {"Aaron Judge"}

    def test_value_names_the_player(self, props):
        bets = find_value_bets(props, devig="Bet365", market="batter_total_bases")

        assert bets
        assert all(bet["player_name"] in ("Aaron Judge", "Rafael Devers") for bet in bets)
        assert all(bet["point"] == 1.5 for bet in bets)


class TestConsensusDevig:
    """Three books agree the true price is 2.00. Unibet is out of line at 2.20,
    which is the bet. Worked through by hand the consensus is 2.0568, so Unibet
    is +6.96% and the other three are negative.
    """

    @pytest.fixture
    def four_books(self):
        prices = {
            "Pinnacle": {"Red Sox": 2.00, "Blue Jays": 2.00},
            "Bet365": {"Red Sox": 1.95, "Blue Jays": 1.95},
            "TAB": {"Red Sox": 1.90, "Blue Jays": 1.90},
            "Unibet": {"Red Sox": 2.20, "Blue Jays": 1.80},
        }
        return {
            "sport": "MLB",
            "games": [
                entry("Red Sox", "Blue Jays", "2026-07-04T17:05:00", book, quotes)
                for book, quotes in prices.items()
            ],
        }

    def test_all_books(self, four_books):
        bets = find_value_bets(four_books, devig="all")

        assert bets[0]["bookmaker"] == "Unibet"
        assert bets[0]["selection"] == "Red Sox"
        assert bets[0]["fair_price"] == pytest.approx(2.0568, abs=0.001)
        assert bets[0]["edge_percent"] == pytest.approx(6.96, abs=0.01)

    def test_one_book_out_of_line_moves_both_sides(self, four_books):
        """Unibet shading the Blue Jays to 1.80 pulls their consensus under
        2.00, which leaves Pinnacle's 2.00 on that side worth backing. A single
        sharp book cannot show this, since it is the one being measured."""
        bets = find_value_bets(four_books, devig="all")

        assert len(bets) == 2
        assert bets[1]["bookmaker"] == "Pinnacle"
        assert bets[1]["selection"] == "Blue Jays"
        assert bets[1]["edge_percent"] == pytest.approx(2.38, abs=0.01)

    def test_a_book_is_judged_against_a_consensus_it_is_part_of(self, four_books):
        """Unlike a single sharp book, no book is excluded from the results,
        so the one setting the price can still be the one beating it."""
        bets = find_value_bets(four_books, devig="all", min_edge=-100.0)

        assert {bet["bookmaker"] for bet in bets} == {"Pinnacle", "Bet365", "TAB", "Unibet"}

    def test_too_few_books_is_no_consensus(self, four_books):
        four_books["games"] = four_books["games"][:3]
        assert find_value_bets(four_books, devig="all") == []

    def test_min_books_is_configurable(self, four_books):
        four_books["games"] = four_books["games"][1:]
        assert find_value_bets(four_books, devig="all") == []
        assert find_value_bets(four_books, devig="all", min_books=3) != []

    def test_weights_are_used_as_given(self, four_books):
        """Weighting Unibet to nothing leaves the three books that agree, so
        the fair price is exactly their 2.00 and Unibet's edge is 10%."""
        bets = find_value_bets(
            four_books,
            devig={"Pinnacle": 1.0, "Bet365": 1.0, "TAB": 1.0, "Unibet": 0.0},
        )

        assert len(bets) == 1
        assert bets[0]["bookmaker"] == "Unibet"
        assert bets[0]["fair_price"] == pytest.approx(2.00, abs=0.001)
        assert bets[0]["edge_percent"] == pytest.approx(10.0, abs=0.01)

    def test_naming_books_lowers_the_floor(self, four_books):
        """Naming two books means a consensus of two was asked for, so the
        default floor of four does not veto it."""
        bets = find_value_bets(four_books, devig={"Pinnacle": 1.0, "Bet365": 1.0})

        assert [bet["bookmaker"] for bet in bets] == ["Unibet"]

    def test_unnamed_books_are_left_out_of_the_average(self, four_books):
        """Pinnacle alone by weights matches Pinnacle alone by name."""
        by_weights = find_value_bets(four_books, devig={"Pinnacle": 1.0})
        by_name = find_value_bets(four_books, devig="Pinnacle")

        assert [bet["edge_percent"] for bet in by_weights] == [
            pytest.approx(bet["edge_percent"]) for bet in by_name
        ]


class TestDirtyTeamNames:
    """Books do not agree on team names. Bovada and Fanatics quote the Oakland
    Athletics as "Athletics", which reads as a third side of a two sided bet.
    """

    def test_an_unknown_name_is_dropped_from_a_handicap(self):
        """Which side a handicap is depends on which team it names, so a name
        matching neither is unusable. The books that do name a team still
        pair."""
        response = {
            "sport": "MLB",
            "games": [
                lined(
                    "Oakland Athletics", "Detroit Tigers", "2026-08-02T21:05:00",
                    "BetRight", "alternate_lines_1st_5_innings",
                    [
                        {"name": "Oakland Athletics", "price": 2.02, "point": -0.5},
                        {"name": "Detroit Tigers", "price": 1.70, "point": 0.5},
                    ],
                ),
                lined(
                    "Oakland Athletics", "Detroit Tigers", "2026-08-02T21:05:00",
                    "Bovada", "alternate_lines_1st_5_innings",
                    [
                        {"name": "Detroit Tigers", "price": 2.10, "point": 0.5},
                        {"name": "Athletics", "price": 1.59, "point": 0.5},
                    ],
                ),
            ],
        }
        arbs = find_arbitrage(response, market="alternate_lines_1st_5_innings")

        assert len(arbs) == 1
        assert arbs[0]["profit_percent"] == pytest.approx(2.96, abs=0.01)
        assert {leg["team"] for leg in arbs[0]["legs"]} == {
            "Oakland Athletics",
            "Detroit Tigers",
        }

    def test_an_extra_name_skips_the_bet_not_the_market(self):
        """Head to head cannot drop unmatched names, since a three way market's
        third outcome is a real one. The spoiled game is skipped and the rest
        of the response is still reported."""
        response = {
            "sport": "MLB",
            "games": [
                entry("Oakland Athletics", "Detroit Tigers", "2026-08-02T21:05:00",
                      "BetRight", {"Oakland Athletics": 1.80, "Detroit Tigers": 1.95}),
                entry("Oakland Athletics", "Detroit Tigers", "2026-08-02T21:05:00",
                      "Bovada", {"Athletics": 1.80, "Detroit Tigers": 2.30}),
                entry("Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365",
                      {"Blue Jays": 2.18, "Red Sox": 1.80}),
                entry("Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Sportsbet",
                      {"Blue Jays": 1.75, "Red Sox": 2.02}),
            ],
        }
        arbs = find_arbitrage(response)

        assert len(arbs) == 1
        assert arbs[0]["home_team"] == "Red Sox"

    def test_a_tie_still_raises(self):
        """A draw is a real third outcome, not a naming slip, whatever it is
        called."""
        response = {
            "sport": "MLB",
            "games": [
                entry("Oakland Athletics", "Detroit Tigers", "2026-08-02T21:05:00",
                      "BetRight", {"Oakland Athletics": 2.4, "Tie": 9.0,
                                   "Detroit Tigers": 2.6},
                      market="head_to_head_1st_5_innings"),
            ],
        }
        with pytest.raises(ValidationError, match="draw"):
            find_arbitrage(response, market="head_to_head_1st_5_innings")


class TestNearArbs:
    @pytest.fixture
    def no_arb(self):
        return {
            "sport": "MLB",
            "games": [
                entry("Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Bet365",
                      {"Red Sox": 1.90, "Blue Jays": 1.90}),
                entry("Red Sox", "Blue Jays", "2026-07-04T17:05:00", "Sportsbet",
                      {"Red Sox": 1.92, "Blue Jays": 1.88}),
            ],
        }

    def test_nothing_by_default(self, no_arb):
        assert find_arbitrage(no_arb) == []

    def test_a_negative_min_profit_shows_the_near_miss(self, no_arb):
        near = find_arbitrage(no_arb, min_profit=-5.0)

        assert len(near) == 1
        assert near[0]["profit_percent"] == pytest.approx(-4.50, abs=0.01)
