# rapidoddsapi

Official Python SDK for [RapidOddsAPI](https://rapidoddsapi.com). Bookmaker odds
from 100+ books, live scores and player stats, over REST and WebSocket.

```bash
pip install rapidoddsapi
```

Requires Python 3.9 or newer. Get a key at [rapidoddsapi.com](https://rapidoddsapi.com);
the free tier is 250 credits with no card.

## Quickstart

```python
from rapidoddsapi import RapidOddsAPI

client = RapidOddsAPI(api_key="oa_your_api_key_here")

odds = client.get_odds("AFL", ["head_to_head"], ["Sportsbet", "TAB", "Ladbrokes"])

for entry in odds["games"]:
    game = entry["game"]
    print(f"{game['away_team']} at {game['home_team']}")
    for book in entry["bookmakers"]:
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                print(f"  {book['name']:<12} {outcome['name']:<20} {outcome['price']}")
```

## Streaming

Odds are pushed to you the moment a scrape cycle finishes, so you are never
polling and never working off a stale price. Included on Pro and Elite at no
extra cost.

```python
for update in client.stream_odds("AFL", ["head_to_head"], ["Sportsbet", "TAB"]):
    for entry in update["data"]["games"]:
        print(entry["game"]["home_team"], update["credits_charged"])
```

That is the whole thing. The connection is kept alive, and if it drops (laptop
sleeps, network cuts out, server restarts) the client reconnects with backoff and
replays your subscription automatically.

Live scores stream the same way:

```python
for update in client.stream_results("AFL", status="live"):
    for entry in update["data"]["games"]:
        game, score = entry["game"], entry["score"]
        print(game["home_team"], score["home"]["points"],
              game["away_team"], score["away"]["points"])
```

Async is identical, with `async for`:

```python
from rapidoddsapi import AsyncRapidOddsAPI

async with AsyncRapidOddsAPI(api_key="oa_your_api_key_here") as client:
    async for update in client.stream_odds("NBA", ["head_to_head"], ["Pinnacle"]):
        print(update["data"]["games"])
```

Tuning, if you need it:

```python
client.stream_odds(
    "AFL", ["head_to_head"], ["Sportsbet"],
    reconnect=True,              # False to raise on the first drop
    max_reconnect_attempts=None, # consecutive failures before giving up
    initial_backoff=1.0,
    max_backoff=30.0,
)
```

## Finding bets

`find_arbitrage` and `find_value_bets` work on a response you already have, so
they cost no extra credits.

```python
from rapidoddsapi import find_arbitrage, find_value_bets

odds = client.get_odds("MLB", ["head_to_head"],
                       ["Bet365", "Sportsbet", "TAB", "Pinnacle", "DraftKings"])

for arb in find_arbitrage(odds, stake=100):
    print(f"{arb['away_team']} at {arb['home_team']}  +{arb['profit_percent']:.2f}%")
    for leg in arb["legs"]:
        print(f"  {leg['team']} {leg['price']} @ {leg['bookmaker']}  stake ${leg['stake']}")
```

```
Toronto Blue Jays at Boston Red Sox  +4.85%
  Toronto Blue Jays 2.18 @ Bet365  stake $48.10
  Boston Red Sox 2.02 @ Sportsbet  stake $51.90
```

`find_value_bets` de-vigs a sharp book to get a fair price, then reports every
book paying more than that.

```python
for bet in find_value_bets(odds, sharp="Pinnacle", min_edge=1.0):
    print(f"+{bet['edge_percent']:.1f}%  {bet['selection']} {bet['price']} "
          f"@ {bet['bookmaker']}  (fair {bet['fair_price']:.2f})")
```

### Which markets these work on

Two-way head to head markets, including the period variants
(`head_to_head_1st_half`, `_1st_5_innings`, `_1st_period`, `_1st_set`) and
soccer's `draw_no_bet`.

Anything else raises `ValidationError`. Totals, spreads, team totals, player
props and three-way markets are coming in a later version.

```python
find_arbitrage(odds, market="alternate_total_runs")
# ValidationError: 'alternate_total_runs' carries a line, so its outcomes have
# to be grouped by point before they can be paired.
```

Both helpers match games across bookmakers on team names plus a time window, so
books listing slightly different start times still line up.

## Methods

| Method | Returns | Credits |
|---|---|---|
| `get_odds(sport, market_types, bookmakers)` | `OddsResponse` | `market_types x ceil(bookmakers / 5)` |
| `get_results(sport, status=, include=, game_id=, round_number=, days=)` | `ResultsResponse` | 1 |
| `list_sports(markets=)` | `list[SportInfo]` | 0 |
| `get_sport(sport, markets=)` | `SportInfo` | 0 |
| `list_results_sports()` | `list[SportInfo]` | 0 |
| `get_usage()` | `Usage` | 0 |
| `stream_odds(sport, market_types, bookmakers)` | iterator of `OddsUpdate` | same as `get_odds`, per push |
| `stream_results(sport, status=, include=, days=)` | iterator of `ResultsUpdate` | 1 per push |
| `credits_used` | `int` | — |

Credits are only charged when games come back, so a query that matches nothing
is free.

`credits_used` counts what this client has spent since you created it. It knows
nothing about other processes or earlier runs. For the real balance, ask the
server:

```python
usage = client.get_usage()
print(f"{usage['credits_remaining']} of {usage['credits_limit']} left")
```

On the free tier `usage["resets"]` is False: those credits are a one off
allowance, not a monthly one.

`AsyncRapidOddsAPI` has the same methods, awaited.

Helpers: `find_arbitrage`, `find_value_bets`, `group_games`, `parse_time`.

### Sports

Pass the sport id as a string.

```python
from rapidoddsapi import SPORTS, RESULTS_SPORTS

SPORTS
# ('NFL', 'NBA', 'WNBA', 'MLB', 'NHL', 'AFL', 'NRL', 'EPL', 'MLS',
#  'WORLD_CUP', 'MENS_AO', 'MENS_RG', 'MENS_WIMBLEDON', 'MENS_USO')

RESULTS_SPORTS
# ('AFL', 'MLB', 'WNBA', 'NRL')
```

Tennis reuses the team fields for player names, so `home_team` and `away_team`
hold players on the four `MENS_` ids. One slam is in season at a time.

Six more soccer leagues (La Liga, Serie A, Bundesliga, Ligue 1, Champions
League, A-League) are accepted as ids but return no games yet. They are in
`UPCOMING_SPORTS` rather than `SPORTS`.

Those tuples are a snapshot shipped with the package. To ask the API itself,
which costs nothing:

```python
client.list_sports()
# [{'id': 'NBA', 'name': 'NBA'}, {'id': 'AFL', 'name': 'AFL'}, ...]
```

Market keys vary by sport, and `get_sport` returns the ones a sport carries:

```python
afl = client.get_sport("AFL")
afl["markets"]["game"]
# ['alternate_lines', 'alternate_total_points', 'head_to_head', ...]

client.get_odds("AFL", afl["markets"]["game"][:1], ["Sportsbet"])
```

The [coverage page](https://rapidoddsapi.com/coverage) is the same information
in a browser.

### Bookmakers

Many brands share one odds feed and so quote identical prices. Requests name
the feed, not the brand: `"Ladbrokes"` covers Neds, `"Betmakers"` covers the 26
brands running on it. Asking for a brand name returns nothing.

```python
from rapidoddsapi import BOOKMAKERS, AU_BOOKMAKERS, US_BOOKMAKERS, EU_BOOKMAKERS

client.get_odds("AFL", ["head_to_head"], list(AU_BOOKMAKERS))
```

Every feed costs credits, so request the ones you need rather than all of them.
Which feeds carry a given sport and market varies; the
[coverage page](https://rapidoddsapi.com/coverage) is the current picture.

## Errors

```python
from rapidoddsapi import (
    RapidOddsAPI, AuthenticationError, InsufficientCreditsError,
    RateLimitError, NotFoundError,
)

try:
    odds = client.get_odds("AFL", ["head_to_head"], ["Sportsbet"])
except InsufficientCreditsError as exc:
    print(f"Out of credits, {exc.credits_remaining} left")
except AuthenticationError:
    print("Bad key")
```

| Exception | When |
|---|---|
| `AuthenticationError` | 401, key missing or not recognised |
| `SubscriptionError` | 403, subscription not active |
| `NotFoundError` | 404, unknown sport |
| `ValidationError` | 400 or 422, bad parameter |
| `RateLimitError` | 429, over 30 requests per second |
| `InsufficientCreditsError` | 429, out of credits. Carries `credits_remaining` |
| `ServerError` | 5xx |
| `NetworkError` | timeout, DNS failure, connection reset |
| `StreamAuthError` | stream rejected: bad key, or plan without WebSocket |
| `StreamError` | stream failed for another reason |

All inherit `RapidOddsAPIError`. The two 429s share a `QuotaError` parent, so
you can catch either separately or both at once.

Requests are retried three times with backoff on 5xx, rate limits and network
failures. Insufficient credits is never retried, since retrying cannot help.

## Timestamps

Timestamps are naive UTC strings with no offset, like `2026-07-23T09:30:00`.
Anything that reads a missing offset as local time will be wrong, so use
`parse_time` when you need a real datetime.

```python
from rapidoddsapi import parse_time

start = parse_time(entry["game"]["commence_time"])  # aware, UTC
```

The odds and results APIs can disagree on a game's start time by several
minutes, since one comes from bookmaker feeds and the other from the official
league feed. Don't join them on an exact timestamp. `group_games` matches on
teams plus a time window instead.

## Settling from results

`score.totals.full_time` is `None` until a game is `CONCLUDED`, and each other
named total is `None` until the periods it covers have finished. That is
deliberate, so a live scoreline can never be mistaken for a final one. For a
live running total, sum `by_period`.

```python
totals = entry["score"]["totals"]

if totals["full_time"] is not None:
    settle(total_points=totals["full_time"]["points"])
else:
    running = sum(period["points"] for period in totals["by_period"])
```

Do not hardcode how many periods a half is: `half_time` waits for period 2 in a
sport played in quarters but only period 1 in a sport played in halves, and MLB
carries `first_5_innings` instead. Let the `None` tell you.

## Use cases

- Arbitrage and positive EV scanners, using the helpers above
- Odds comparison screens and line-shopping tools
- Line movement tracking and alerting off the stream
- Automatic bet settlement from the results API
- Bonus bet conversions
- Model backtesting against live prices

Worked examples for each are in the [guides](https://rapidoddsapi.com/blog).

## Links

- [rapidoddsapi.com](https://rapidoddsapi.com)
- [API documentation](https://rapidoddsapi.com/docs)
- [Coverage: sports, bookmakers, market keys](https://rapidoddsapi.com/coverage)
- [Guides](https://rapidoddsapi.com/blog)
- support@rapidoddsapi.com

## License

MIT
