# Changelog

Notable changes to this package. Versions follow [semantic versioning](https://semver.org).

## Unreleased

Planned for the next release:

- Arbitrage and value bets on markets with a line: totals, spreads, team totals
  and player props
- Three-way markets

## 0.2.0

Four methods for things the API can now answer directly. None of them cost
credits, and all need the API at v1.1.0 or later.

- `list_sports` and `get_sport`, which return the sports the API accepts and,
  on request, each one's market keys. The market keys are what `get_odds` takes
  as `market_types`, so they no longer have to be looked up by hand
- `list_results_sports` for the sports carrying live scores and player stats
- `get_usage` for the credit balance the server holds. Unlike `credits_used` it
  survives restarts and counts spend from anywhere, not just this client
- `SportInfo`, `SportMarkets` and `Usage` response types

The sport tuples in `constants` stay as an offline snapshot, and `BOOKMAKERS`
remains the only list of bookmaker feeds, since the API has no endpoint for
them.

## 0.1.0

First release.

- `RapidOddsAPI` and `AsyncRapidOddsAPI` clients over REST
- `get_odds` and `get_results`, with full type hints on every response
- `stream_odds` and `stream_results` over WebSocket, with automatic reconnect
  and re-subscribe
- `find_arbitrage` and `find_value_bets` for two-way head to head markets
- `group_games` to match a game across bookmakers on teams plus a time window
- `parse_time` for the API's naive UTC timestamps
- Typed exceptions, including separate classes for rate limiting and running
  out of credits
- Automatic retry with backoff on 5xx, rate limits and network failures
- `credits_used` tally per client
