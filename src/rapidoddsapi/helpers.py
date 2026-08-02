"""Tools that work on an odds response.

Each of these takes the dict returned by `get_odds` (or the `data` field of a
stream update) and needs no further API calls.
"""

from datetime import datetime, timezone
from typing import (
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from .constants import DEFAULT_MATCH_WINDOW_HOURS, MATCH_WINDOW_HOURS
from .exceptions import ValidationError
from .types import Arbitrage, ArbLeg, GameOdds, OddsResponse, Outcome, ValueBet

_OVER_UNDER = ("Over", "Under")

# A draw makes a market three way. Books name it either of these.
_DRAW_NAMES = ("draw", "tie")

# Bounds a consensus has to clear before it is believed. One book quoting a
# stale or mistyped price drags an average in a way it cannot drag a single
# book's de-vig, so a fair price outside the range books actually quote, or an
# edge nobody really offers, is treated as bad data rather than opportunity.
_MIN_FAIR_ODDS = 1.1
_MAX_FAIR_ODDS = 50.0
_MAX_EDGE_PERCENT = 50.0


def parse_time(timestamp: str) -> datetime:
    """Turn an API timestamp into a timezone aware datetime.

    Timestamps come back as naive UTC with no offset, so anything that assumes
    a missing offset means local time reads them wrong. This attaches UTC.
    """
    cleaned = timestamp.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def match_window(response: OddsResponse) -> float:
    """How far apart two start times can be and still be the same game.

    Six hours for a sport that plays once a day, which absorbs books listing
    different start times. MLB gets 1.8, because a split doubleheader can start
    three hours after the first game and the two must not merge.
    """
    return MATCH_WINDOW_HOURS.get(response.get("sport", ""), DEFAULT_MATCH_WINDOW_HOURS)


def group_games(response: OddsResponse) -> List[GameOdds]:
    """Merge the per bookmaker entries that belong to the same game.

    Matching on team names alone breaks two ways: the same two teams can play
    twice in a day, and books disagree on the listed start time by a few
    minutes. So games match on teams plus a time window, wide enough to absorb
    the disagreement and narrow enough to keep a doubleheader apart.

    The window comes from the sport, so there is nothing to pass. Edit
    `MATCH_WINDOW_HOURS` if a sport needs a different one.
    """
    window_hours = match_window(response)
    seen: Dict[Tuple[str, str], List[float]] = {}
    merged: Dict[Tuple[str, str, int], GameOdds] = {}

    for entry in response.get("games", []):
        game = entry["game"]
        teams = (game.get("home_team", ""), game.get("away_team", ""))
        instance = _instance_for(seen, teams, game.get("commence_time"), window_hours)
        key = (teams[0], teams[1], instance)

        if key not in merged:
            merged[key] = {"game": game, "bookmakers": []}
        merged[key]["bookmakers"].extend(entry.get("bookmakers", []))

    return list(merged.values())


def find_arbitrage(
    response: OddsResponse,
    *,
    market: str = "head_to_head",
    stake: float = 100.0,
    min_profit: float = 0.0,
) -> List[Arbitrage]:
    """Find markets where backing both sides at different books profits.

    An arb exists when the implied probabilities of the two sides sum to under
    1. Every pair of books is checked rather than just the best price on each
    side, because one book topping both sides would otherwise hide an arb.

    `min_profit` is a percentage. A small buffer is worth setting: prices move
    while you are placing the second leg, so an edge under about 1 percent
    often will not survive. Set it negative to see near misses.

    Markets carrying a line are grouped by that line first, since Over 8.5 and
    Over 9.5 are different bets. Handicaps additionally pair a team against its
    opponent on the mirrored line, so -1.5 is matched with +1.5 and never with
    another -1.5. Player props group by player and team totals by team, so two
    players' props at the same number are never crossed.

    Two kinds of outcome are ignored on handicaps: a line of 0, which pushes
    when the teams finish level rather than one side winning, and a name
    matching neither team, which gives no way to tell which side of the bet it
    is. Books disagree on team names often enough for the second to matter.

    A three way market raises rather than returning nothing, since an empty
    list would read as "no opportunities". It is recognised by a draw or tie
    among the outcomes. A bet left with more than two sides for any other
    reason is dirty data rather than a third way to bet, so it is skipped and
    the rest of the response is still reported.

    One result is returned per line, so a totals market with ten lines can
    yield ten. Results are sorted by profit, best first.
    """
    games = group_games(response)

    found: List[Arbitrage] = []

    for game in games:
        for prices in _groups_by_selection(game, market).values():
            if not _pairable(prices, market):
                continue

            best = _best_pair(prices)
            if best is None:
                continue

            margin, legs = best
            profit = (1 / margin - 1) * 100
            if profit < min_profit:
                continue

            found.append(
                {
                    "home_team": game["game"].get("home_team", ""),
                    "away_team": game["game"].get("away_team", ""),
                    "commence_time": game["game"].get("commence_time", ""),
                    "margin": margin,
                    "profit_percent": profit,
                    "legs": [
                        _leg(selection, price, book, round(stake * (1 / price) / margin, 2))
                        for selection, price, book in legs
                    ],
                }
            )

    found.sort(key=lambda a: a["profit_percent"], reverse=True)
    return found


def find_value_bets(
    response: OddsResponse,
    *,
    devig: Union[str, Mapping[str, float]] = "Pinnacle",
    market: str = "head_to_head",
    min_edge: float = 1.0,
    min_books: int = 4,
) -> List[ValueBet]:
    """Find prices that beat a fair value worked out from the odds themselves.

    Bookmakers price in a margin, so their odds sum to more than certainty.
    Removing it leaves a fair probability for each side, and any book paying
    more than that fair price is +EV. Edge is `fair_probability x price - 1`,
    as a percentage, and `min_edge` filters out the small ones, which are
    usually inside the error of the fair price.

    `devig` says where the fair price comes from:

        "Pinnacle"                     one book, the sharpest you have
        "all"                          every book in the response
        {"Pinnacle": 0.8, "TAB": 0.2}  the books you name, at your weights

    One book is the sharpest read if you have a book worth trusting, since a
    sharp runs thin margins and moves fast. Its own prices are then excluded
    from the results, as it cannot beat itself. Consensus is the better read
    when no single book stands out: each book is de-vigged on its own, and the
    fair odds are averaged, so one wide book cannot drag the answer far.

    Averaging is weighted. Give weights and they are used as passed, relative
    to each other. Otherwise a book's weight is `1 / (1 + margin) ** 2`, which
    counts a tight book for more than a wide one. `min_books` is how many books
    have to price a bet before a consensus is trusted, and is capped at the
    number you name when you name them. Under consensus every book is judged,
    including its own contribution to the average.

    The book being de-vigged has to price both sides of a bet, since a margin
    cannot be stripped from one price alone. On a handicap that means both
    halves of the same line: the fair price for -1.5 comes from that book's
    -1.5 and +1.5 together, and is then compared against -1.5 elsewhere.

    Markets are grouped by line, player and team exactly as in
    `find_arbitrage`, which also covers what is ignored on handicaps, and three
    way markets raise for the same reason.

    Results are sorted by edge, best first.
    """
    weights: Optional[Mapping[str, float]] = None
    single: Optional[str] = None
    if isinstance(devig, str):
        single = None if devig == "all" else devig
    else:
        weights = devig
        # Naming books is asking for a consensus of that size, so the floor
        # cannot exceed it. A book weighted to nothing is not one of them.
        min_books = min(min_books, sum(1 for weight in weights.values() if weight > 0))

    games = group_games(response)

    found: List[ValueBet] = []

    for game in games:
        for by_book in _groups_by_bookmaker(game, market).values():
            sides = {selection for prices in by_book.values() for selection in prices}
            if not _pairable(sides, market):
                continue

            if single is None:
                fair = _consensus_probabilities(by_book, weights, min_books)
            else:
                base = by_book.get(single)
                fair = _fair_probabilities(base) if base and len(base) >= 2 else None
            if fair is None:
                continue

            for book, prices in by_book.items():
                if book == single:
                    continue
                for selection, price in prices.items():
                    probability = fair.get(selection)
                    if probability is None:
                        continue

                    edge = (probability * price - 1) * 100
                    if edge < min_edge or (single is None and edge > _MAX_EDGE_PERCENT):
                        continue

                    bet: ValueBet = {
                        "home_team": game["game"].get("home_team", ""),
                        "away_team": game["game"].get("away_team", ""),
                        "commence_time": game["game"].get("commence_time", ""),
                        "selection": selection.name,
                        "price": price,
                        "bookmaker": book,
                        "fair_price": 1 / probability,
                        "fair_probability": probability,
                        "edge_percent": edge,
                    }
                    if selection.point is not None:
                        bet["point"] = selection.point
                    if selection.player_name:
                        bet["player_name"] = selection.player_name
                    if selection.team_name:
                        bet["team_name"] = selection.team_name

                    found.append(bet)

    found.sort(key=lambda v: v["edge_percent"], reverse=True)
    return found


class _Selection(NamedTuple):
    """One side of a bet, holding everything that tells it from another.

    Two outcomes both named "Over" are the same bet only if they share a line,
    and on player props and team totals also a subject. Carrying those in the
    identity is what keeps Over 8.5 apart from Over 9.5, and one player's props
    apart from another's.
    """

    name: str
    point: Optional[float] = None
    player_name: Optional[str] = None
    team_name: Optional[str] = None


# Which bet an outcome belongs to. Every part is a string so that lines compare
# as text; see _line_key.
_GroupKey = Tuple[str, ...]


def _line_key(point: float) -> str:
    """A line as text, so equal lines always land in the same group.

    Comparing the floats directly leaves 8.5 and 8.500000000000002 as different
    bets. Real lines are quoted in quarters at finest, so one decimal place
    separates every line that actually exists.
    """
    return f"{point:.1f}"


def _classify(
    outcome: Outcome, home_team: str, away_team: str
) -> Optional[Tuple[_GroupKey, _Selection]]:
    """Which bet an outcome belongs to, and which side of it this is.

    The market key is not consulted. What an outcome is is visible in the
    outcome itself: a player prop names a player, a team total names a team and
    quotes Over or Under, a handicap names a team and carries a line. Reading
    the shape rather than a list of market keys means a market the API adds
    later works without a release.
    """
    name = outcome.get("name")
    if not name:
        return None

    point = outcome.get("point")
    if point is None:
        return (), _Selection(name)

    player_name = outcome.get("player_name")
    if player_name:
        return ("player", player_name, _line_key(point)), _Selection(
            name, point, player_name=player_name
        )

    if name in _OVER_UNDER:
        team_name = outcome.get("team_name")
        if team_name:
            return ("team", team_name, _line_key(point)), _Selection(
                name, point, team_name=team_name
            )
        return ("total", _line_key(point)), _Selection(name, point)

    # A handicap. Working out which side of the bet this is means knowing
    # which team it names, so a name matching neither is dropped. Books do not
    # agree on team names, and "Athletics" for "Oakland Athletics" would
    # otherwise read as a third side and make the bet unpairable.
    if name not in (home_team, away_team):
        return None

    # A handicap of zero is dropped. It pushes when the teams finish level, so
    # both sides are refunded rather than one winning, and pricing it as a pair
    # would report a profit that only arrives if there is no tie.
    if point == 0:
        return None

    # The two sides of one bet are a team and its opponent on the mirrored
    # line, so the group is named after whichever team is giving start. Books
    # disagree on who that is, and both readings of the same number are real
    # bets, so -1.5 and +1.5 have to stay in separate groups rather than
    # collapsing onto the number alone.
    favourite = name if point < 0 else (away_team if name == home_team else home_team)

    return ("spread", favourite, _line_key(abs(point))), _Selection(name, point)


def _iter_prices(game: GameOdds, market: str) -> Iterator[Tuple[_GroupKey, _Selection, float, str]]:
    home_team = game["game"].get("home_team", "")
    away_team = game["game"].get("away_team", "")

    for book in game.get("bookmakers", []):
        book_name = book.get("name", "")
        for entry in book.get("markets", []):
            if entry.get("key") != market:
                continue
            for outcome in entry.get("outcomes", []):
                price = outcome.get("price")
                if not price:
                    continue
                classified = _classify(outcome, home_team, away_team)
                if classified is None:
                    continue
                group, selection = classified
                yield group, selection, price, book_name


def _pairable(selections: Iterable[_Selection], market: str) -> bool:
    """Whether a bet's sides can be paired, raising if the market is three way.

    Both helpers back one selection against the other, which needs exactly two
    sides. A draw is a real third outcome that no pair can cover, and returning
    an empty list for it would look identical to finding nothing, so it raises.

    More than two sides without a draw is dirty data rather than a third way to
    bet, usually one book naming a team differently from the rest. That is one
    bet spoiled, not a market that cannot be priced, so it is skipped and the
    remaining lines are still reported.

    A market simply absent from the response is not an error, nor is one side,
    which is a book quoting only an Over.
    """
    names = [selection.name for selection in selections]
    if len(names) <= 2:
        return True

    if any(name.strip().lower() in _DRAW_NAMES for name in names):
        raise ValidationError(
            f"'{market}' has a draw alongside {len(names) - 1} other outcomes. "
            f"Only two sided bets can be priced this way, so three way markets "
            f"like head_to_head_3_way are not supported."
        )
    return False


def _groups_by_selection(
    game: GameOdds, market: str
) -> Dict[_GroupKey, Dict[_Selection, List[Tuple[float, str]]]]:
    """Every price for each side of each bet, for pairing across books."""
    groups: Dict[_GroupKey, Dict[_Selection, List[Tuple[float, str]]]] = {}
    for group, selection, price, book in _iter_prices(game, market):
        groups.setdefault(group, {}).setdefault(selection, []).append((price, book))
    return groups


def _groups_by_bookmaker(
    game: GameOdds, market: str
) -> Dict[_GroupKey, Dict[str, Dict[_Selection, float]]]:
    """The same prices keyed by book, so one book's margin can be stripped."""
    groups: Dict[_GroupKey, Dict[str, Dict[_Selection, float]]] = {}
    for group, selection, price, book in _iter_prices(game, market):
        groups.setdefault(group, {}).setdefault(book, {})[selection] = price
    return groups


def _leg(selection: _Selection, price: float, bookmaker: str, stake: float) -> ArbLeg:
    leg: ArbLeg = {
        "team": selection.name,
        "price": price,
        "bookmaker": bookmaker,
        "stake": stake,
    }
    if selection.point is not None:
        leg["point"] = selection.point
    if selection.player_name:
        leg["player_name"] = selection.player_name
    if selection.team_name:
        leg["team_name"] = selection.team_name
    return leg


def _instance_for(
    seen: Dict[Tuple[str, str], List[float]],
    teams: Tuple[str, str],
    commence_time: Optional[str],
    window_hours: float,
) -> int:
    """Which meeting of these two teams a start time belongs to.

    Start times reduce to hours since the epoch so the comparison is one
    subtraction, with no timezone or midnight edge cases.
    """
    if not commence_time:
        return 0

    hours = parse_time(commence_time).timestamp() / 3600
    registered = seen.setdefault(teams, [])

    closest, smallest = None, float("inf")
    for index, hour in enumerate(registered):
        gap = abs(hours - hour)
        if gap < smallest:
            closest, smallest = index, gap

    if closest is not None and smallest <= window_hours:
        return closest

    registered.append(hours)
    return len(registered) - 1


def _best_pair(
    prices: Dict[_Selection, List[Tuple[float, str]]],
) -> Optional[Tuple[float, Sequence[Tuple[_Selection, float, str]]]]:
    """The cheapest way to cover both sides of one bet, across two books.

    Cheapest means the smallest sum of implied probabilities, which is the
    largest profit. Whether that sum is under 1, and so an arb at all, is left
    to the caller's `min_profit`, so a caller asking for near misses can see
    them.
    """
    if len(prices) != 2:
        return None

    (selection_a, prices_a), (selection_b, prices_b) = prices.items()
    best: Optional[Tuple[float, Sequence[Tuple[_Selection, float, str]]]] = None

    for price_a, book_a in prices_a:
        for price_b, book_b in prices_b:
            if book_a == book_b:
                continue
            margin = 1 / price_a + 1 / price_b
            if best is None or margin < best[0]:
                best = (
                    margin,
                    [(selection_a, price_a, book_a), (selection_b, price_b, book_b)],
                )

    return best


def _consensus_probabilities(
    by_book: Dict[str, Dict[_Selection, float]],
    weights: Optional[Mapping[str, float]],
    min_books: int,
) -> Optional[Dict[_Selection, float]]:
    """Fair probabilities agreed across books, rather than taken from one.

    Every book is de-vigged on its own first, then those fair odds are
    averaged. De-vigging first is what makes the books comparable: averaging
    the raw prices would just average the margins in with them.

    Odds are averaged rather than probabilities. The two are not the same, and
    averaging odds is what the live engines this was ported from do.

    Returns None when too few books priced the bet, since a consensus of two is
    not a consensus.
    """
    totals: Dict[_Selection, float] = {}
    weighted: Dict[_Selection, float] = {}
    contributing = 0

    for book, prices in by_book.items():
        if weights is not None and book not in weights:
            continue
        if len(prices) < 2:
            continue

        implied = sum(1 / price for price in prices.values())
        if implied < 1:
            continue

        weight = weights[book] if weights is not None else 1 / implied**2
        if weight <= 0:
            continue

        contributing += 1
        for selection, price in prices.items():
            # De-vigging lengthens a price by exactly the margin it carried.
            weighted[selection] = weighted.get(selection, 0.0) + price * implied * weight
            totals[selection] = totals.get(selection, 0.0) + weight

    if contributing < min_books:
        return None

    fair: Dict[_Selection, float] = {}
    for selection, accumulated in weighted.items():
        odds = accumulated / totals[selection]
        if _MIN_FAIR_ODDS <= odds <= _MAX_FAIR_ODDS:
            fair[selection] = 1 / odds
    return fair


def _fair_probabilities(prices: Dict[_Selection, float]) -> Optional[Dict[_Selection, float]]:
    """Strip a book's margin, leaving probabilities that sum to 1.

    Returns None when the prices already sum to under 1. That is the book
    arbing itself, which is a bad feed rather than a thin margin, and
    normalising it upwards would manufacture edge on every other book.
    """
    implied = {selection: 1 / price for selection, price in prices.items()}
    total = sum(implied.values())
    if total < 1:
        return None
    return {selection: value / total for selection, value in implied.items()}
