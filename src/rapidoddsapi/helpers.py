"""Tools that work on an odds response.

Each of these takes the dict returned by `get_odds` (or the `data` field of a
stream update) and needs no further API calls.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from .exceptions import ValidationError
from .types import Arbitrage, ArbLeg, GameOdds, OddsResponse, ValueBet

DEFAULT_MATCH_WINDOW_HOURS = 4.0


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


def group_games(
    response: OddsResponse, *, window_hours: float = DEFAULT_MATCH_WINDOW_HOURS
) -> List[GameOdds]:
    """Merge the per bookmaker entries that belong to the same game.

    Matching on team names alone breaks two ways: the same two teams can play
    twice in a day, and books disagree on the listed start time by a few
    minutes. So games match on teams plus a time window, wide enough to absorb
    the disagreement and narrow enough to keep a doubleheader apart.

    Widen `window_hours` for sports that never play twice in a day, narrow it
    for tight turnarounds.
    """
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
    window_hours: float = DEFAULT_MATCH_WINDOW_HOURS,
) -> List[Arbitrage]:
    """Find two way markets where backing both sides at different books profits.

    An arb exists when the implied probabilities of the two sides sum to under
    1. Every pair of books is checked rather than just the best price on each
    side, because one book topping both sides would otherwise hide an arb.

    `min_profit` is a percentage. A small buffer is worth setting: prices move
    while you are placing the second leg, so an edge under about 1 percent
    often will not survive.

    Only markets with exactly two outcomes and no line are handled, so this
    covers head_to_head and draw_no_bet. Passing a market with a line, or a
    three way market, raises rather than returning nothing, since an empty list
    would read as "no opportunities".

    Results are sorted by profit, best first.
    """
    games = group_games(response, window_hours=window_hours)
    _require_two_way(games, market)

    found: List[Arbitrage] = []

    for game in games:
        prices = _prices_by_selection(game, market)
        if len(prices) != 2:
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
                    ArbLeg(
                        team=team,
                        price=price,
                        bookmaker=book,
                        stake=round(stake * (1 / price) / margin, 2),
                    )
                    for team, price, book in legs
                ],
            }
        )

    found.sort(key=lambda a: a["profit_percent"], reverse=True)
    return found


def find_value_bets(
    response: OddsResponse,
    *,
    sharp: str = "Pinnacle",
    market: str = "head_to_head",
    min_edge: float = 1.0,
    window_hours: float = DEFAULT_MATCH_WINDOW_HOURS,
) -> List[ValueBet]:
    """Find prices that beat a sharp book's fair value.

    A sharp book runs thin margins and moves fast, so its prices track true
    probability closely. Stripping its margin gives a fair probability for each
    side, and any other book paying more than that fair price is +EV.

    Edge is `fair_probability x price - 1`, as a percentage. `min_edge` filters
    out the small ones, which are usually inside the error of the fair price.

    Needs the sharp book in the response, so include it in the `bookmakers` you
    request. Two way markets with no line only, same as `find_arbitrage`.

    Results are sorted by edge, best first.
    """
    games = group_games(response, window_hours=window_hours)
    _require_two_way(games, market)

    found: List[ValueBet] = []

    for game in games:
        by_book = _prices_by_bookmaker(game, market)
        sharp_prices = by_book.get(sharp)
        if not sharp_prices or len(sharp_prices) != 2:
            continue

        fair = _fair_probabilities(sharp_prices)

        for book, prices in by_book.items():
            if book == sharp:
                continue
            for selection, price in prices.items():
                probability = fair.get(selection)
                if probability is None:
                    continue

                edge = (probability * price - 1) * 100
                if edge < min_edge:
                    continue

                found.append(
                    {
                        "home_team": game["game"].get("home_team", ""),
                        "away_team": game["game"].get("away_team", ""),
                        "commence_time": game["game"].get("commence_time", ""),
                        "selection": selection,
                        "price": price,
                        "bookmaker": book,
                        "fair_price": 1 / probability,
                        "fair_probability": probability,
                        "edge_percent": edge,
                    }
                )

    found.sort(key=lambda v: v["edge_percent"], reverse=True)
    return found


def _require_two_way(games: List[GameOdds], market: str) -> None:
    """Reject markets these tools cannot price correctly.

    Both helpers pair one selection against the other, which only holds for a
    two way market with no line. Returning an empty list for a totals or three
    way market would look identical to finding nothing, so say so instead.

    A market simply absent from the response is not an error: that is a book
    not offering it, and an empty result is the honest answer.
    """
    has_line = False
    max_selections = 0

    for game in games:
        for book in game.get("bookmakers", []):
            for entry in book.get("markets", []):
                if entry.get("key") != market:
                    continue
                outcomes = entry.get("outcomes", [])
                if any("point" in outcome for outcome in outcomes):
                    has_line = True
                max_selections = max(
                    max_selections, len({outcome["name"] for outcome in outcomes})
                )

    if has_line:
        raise ValidationError(
            f"'{market}' carries a line, so its outcomes have to be grouped by "
            f"point before they can be paired. Only two way markets with no "
            f"line are supported: head_to_head and its period variants, and "
            f"draw_no_bet."
        )
    if max_selections > 2:
        raise ValidationError(
            f"'{market}' has {max_selections} outcomes. Only two way markets "
            f"are supported, so three way markets like head_to_head_3_way "
            f"cannot be priced this way."
        )


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


def _prices_by_selection(game: GameOdds, market: str) -> Dict[str, List[Tuple[float, str]]]:
    prices: Dict[str, List[Tuple[float, str]]] = {}
    for book in game.get("bookmakers", []):
        for entry in book.get("markets", []):
            if entry.get("key") != market:
                continue
            for outcome in entry.get("outcomes", []):
                if "point" in outcome:
                    continue
                prices.setdefault(outcome["name"], []).append((outcome["price"], book["name"]))
    return prices


def _prices_by_bookmaker(game: GameOdds, market: str) -> Dict[str, Dict[str, float]]:
    prices: Dict[str, Dict[str, float]] = {}
    for book in game.get("bookmakers", []):
        for entry in book.get("markets", []):
            if entry.get("key") != market:
                continue
            for outcome in entry.get("outcomes", []):
                if "point" in outcome:
                    continue
                prices.setdefault(book["name"], {})[outcome["name"]] = outcome["price"]
    return prices


def _best_pair(
    prices: Dict[str, List[Tuple[float, str]]],
) -> Optional[Tuple[float, Sequence[Tuple[str, float, str]]]]:
    (team_a, prices_a), (team_b, prices_b) = prices.items()
    best: Optional[Tuple[float, Sequence[Tuple[str, float, str]]]] = None

    for price_a, book_a in prices_a:
        for price_b, book_b in prices_b:
            if book_a == book_b:
                continue
            margin = 1 / price_a + 1 / price_b
            if margin >= 1:
                continue
            if best is None or margin < best[0]:
                best = (margin, [(team_a, price_a, book_a), (team_b, price_b, book_b)])

    return best


def _fair_probabilities(prices: Dict[str, float]) -> Dict[str, float]:
    implied = {selection: 1 / price for selection, price in prices.items()}
    total = sum(implied.values())
    return {selection: value / total for selection, value in implied.items()}
