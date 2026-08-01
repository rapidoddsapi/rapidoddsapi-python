# Changelog

Notable changes to this package. Versions follow [semantic versioning](https://semver.org).

## Unreleased

Planned for the next release:

- Arbitrage and value bets on markets with a line: totals, spreads, team totals
  and player props
- Three-way markets

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
