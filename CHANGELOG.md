# Changelog

Notable changes to this package. Versions follow [semantic versioning](https://semver.org).

## 0.3.0

`find_arbitrage` and `find_value_bets` now work on markets carrying a line.

Breaking: `find_value_bets` takes `devig` where it took `sharp`, and
`window_hours` is gone from `group_games`, `find_arbitrage` and
`find_value_bets`.

- Totals, handicaps, team totals and player props are supported. Outcomes are
  grouped into individual bets before being paired, so Over 8.5 is never
  matched against Under 9.5, one player's prop never against another's, and one
  team's total never against the other team's
- Handicaps pair a team against its opponent on the mirrored line. Books
  disagree on who is giving start, so `-1.5` and `+1.5` on the same number are
  two separate bets and backing the same side at two books is not an arb
- Which kind of market a response holds is read from the outcomes themselves,
  not from a list of market keys, so a market the API adds later works without
  an SDK release
- `ArbLeg` and `ValueBet` carry `point` on any market with a line, `player_name`
  on player props and `team_name` on team totals. Head to head results are
  unchanged, since none of the three applies
- One result per line, so a totals market with ten lines can return ten
- `find_arbitrage` no longer discards pairs whose implied probabilities sum to
  1 or more, leaving `min_profit` as the only filter, so a negative value now
  shows near misses. At the default of 0.0 the only new result is a pair
  summing to exactly 1, reported as a 0% arb
- `find_value_bets` takes `devig` in place of `sharp`, and the fair price can
  now come from more than one book. `devig="Pinnacle"` is the old behaviour,
  `devig="all"` averages every book in the response, and
  `devig={"Pinnacle": 0.8, "TAB": 0.2}` averages the books you name at your own
  weights. Each book is de-vigged on its own before the fair odds are averaged,
  weighted by `1 / (1 + margin) ** 2` unless you supply weights
- `min_books` on `find_value_bets`, four by default, is how many books have to
  price a bet before a consensus is trusted. Naming books lowers it to the
  number named. It does not apply when de-vigging a single book
- Under a consensus no book is excluded from the results, so both sides of a
  game can show value at once. A single book is still excluded, since it cannot
  beat its own price
- `find_value_bets` skips a book whose own two prices sum to under 1. That is
  the book arbing itself, which is a bad feed rather than a thin margin, and
  normalising it would have invented edge at every other book
- Under a consensus, a fair price outside 1.1 to 50, or an edge over 50%, is
  discarded as bad data. One stale price drags an average in a way it cannot
  drag a single book's de-vig, so these bounds apply to consensus only
- A handicap outcome naming neither team is ignored. Books disagree on team
  names, and one quoting the Oakland Athletics as "Athletics" would otherwise
  read as a third side and make every line of that game unpairable
- A handicap of zero is ignored. It pushes when the teams finish level, so both
  sides come back rather than one winning, and the pair is not a locked profit
- Only three-way markets now raise `ValidationError`, recognised by a draw or
  tie among the outcomes rather than by counting them. A bet left with more
  than two sides for any other reason is skipped, so one book's naming cannot
  take down a whole market
- The window for matching a game across bookmakers now comes from the sport,
  and `window_hours` is gone from `group_games`, `find_arbitrage` and
  `find_value_bets`. MLB gets 1.8 hours and everything else 6, in
  `MATCH_WINDOW_HOURS`. The old flat 4 hours merged a split doubleheader
  starting three hours after the first game, which compared prices across two
  different games. `match_window` reports what a response will get

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
