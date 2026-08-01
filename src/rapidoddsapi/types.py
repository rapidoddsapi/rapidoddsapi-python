"""Response shapes.

These are TypedDicts, so responses are ordinary dicts at runtime. Your editor
gets autocomplete and mypy checks key names, but an unexpected field from the
API is carried through rather than raising.

Timestamps are strings throughout: naive UTC, no offset, "2026-07-23T09:30:00".
Use `parse_time` from `rapidoddsapi.helpers` to get an aware datetime.
"""

from typing import Any, Dict, List, Optional, TypedDict


class _OutcomeBase(TypedDict):
    name: str
    price: float


class Outcome(_OutcomeBase, total=False):
    """A single price.

    `point` is the line on spreads, totals and player props. `player_name` is
    set on player prop markets, `team_name` on team markets and handicaps.

    correct_score and correct_score_sets also carry one key per competitor
    holding that side's scoreline, named after the competitor.
    """

    point: float
    player_name: str
    team_name: str


class Market(TypedDict):
    key: str
    outcomes: List[Outcome]


class Bookmaker(TypedDict):
    name: str
    last_update: str
    markets: List[Market]


class Game(TypedDict, total=False):
    commence_time: str
    home_team: str
    away_team: str
    game_url: Optional[str]


class GameOdds(TypedDict):
    game: Game
    bookmakers: List[Bookmaker]


class OddsResponse(TypedDict):
    sport: str
    games: List[GameOdds]


class OddsUpdate(TypedDict):
    """One push from the odds stream."""

    event: str
    sport: str
    timestamp: str
    credits_charged: int
    data: OddsResponse


class ResultsGame(TypedDict):
    game_id: int
    commence_time: str
    last_update: Optional[str]
    concluded_at: Optional[str]
    home_team: str
    away_team: str
    status: str
    round_number: Optional[int]


class PeriodState(TypedDict, total=False):
    """Which clock fields are present depends on the sport.

    Only the period in progress carries a clock, except in AFL where finished
    quarters keep `period_seconds_elapsed`. Baseball has no clock and carries
    `half` instead.
    """

    period: int
    completed: bool
    period_seconds_elapsed: int
    period_seconds_remaining: int
    match_seconds_elapsed: int
    display_clock: str
    half: str


class Totals(TypedDict, total=False):
    """Combined score for both teams.

    A named total is None until the period it describes has finished, so
    `full_time` stays None until the game is CONCLUDED. Sum `by_period` for a
    live running total. `half_time` covers the first half however many periods
    that is for the sport; MLB carries `first_5_innings` instead.
    """

    full_time: Optional[Dict[str, Any]]
    half_time: Optional[Dict[str, Any]]
    first_5_innings: Optional[Dict[str, Any]]
    by_period: List[Dict[str, Any]]


class Score(TypedDict, total=False):
    """Scoring field names vary by sport: points for AFL, runs for MLB.

    `home` and `away` hold the team name plus that sport's scoring fields.
    """

    home: Dict[str, Any]
    away: Dict[str, Any]
    home_by_period: List[Dict[str, Any]]
    away_by_period: List[Dict[str, Any]]
    period_state: List[PeriodState]
    totals: Totals
    scoring_events: List[Dict[str, Any]]


# Player entries carry one field per player prop market covered for that sport,
# named to match the market key. The set differs per sport, so this stays a
# plain dict: players[0]["player_disposals"], players[0]["batter_total_bases"].
Player = Dict[str, Any]


class GameResult(TypedDict, total=False):
    """`score` and `players` are absent on games that have not started, and on
    requests that did not ask for them via `include`."""

    game: ResultsGame
    score: Score
    players: List[Player]


class ResultsResponse(TypedDict):
    sport: str
    games: List[GameResult]


class ResultsUpdate(TypedDict):
    """One push from the results stream."""

    event: str
    sport: str
    timestamp: str
    credits_charged: int
    data: ResultsResponse


class ArbLeg(TypedDict):
    team: str
    price: float
    bookmaker: str
    stake: float


class Arbitrage(TypedDict):
    home_team: str
    away_team: str
    commence_time: str
    margin: float
    profit_percent: float
    legs: List[ArbLeg]


class ValueBet(TypedDict):
    home_team: str
    away_team: str
    commence_time: str
    selection: str
    price: float
    bookmaker: str
    fair_price: float
    fair_probability: float
    edge_percent: float
