"""Sport ids and endpoints.

Sport ids are the same strings the API uses, passed straight through:
`client.get_odds("AFL", ...)`.

The sport tuples below are a snapshot, useful offline and for autocomplete.
`client.list_sports()` asks the API for the current list, and for each sport's
market keys, at no credit cost. Bookmakers have no such endpoint, so
`BOOKMAKERS` is the only list of those.
"""

BASE_URL = "https://api.rapidoddsapi.com"
ODDS_WS_URL = "wss://api.rapidoddsapi.com/ws"
RESULTS_WS_URL = "wss://api.rapidoddsapi.com/results-ws"

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3

SPORTS = (
    "NFL",
    "NBA",
    "WNBA",
    "MLB",
    "NHL",
    "AFL",
    "NRL",
    "EPL",
    "MLS",
    "WORLD_CUP",
    "MENS_AO",
    "MENS_RG",
    "MENS_WIMBLEDON",
    "MENS_USO",
)

# Accepted by the API but not yet scraped, so these return an empty games list.
UPCOMING_SPORTS = (
    "LA_LIGA",
    "SERIE_A",
    "BUNDESLIGA",
    "LIGUE_1",
    "UCL",
    "A_LEAGUE",
)

# Live scores and player stats cover fewer sports than odds do.
RESULTS_SPORTS = ("AFL", "MLB", "WNBA", "NRL")

RESULTS_INCLUDES = ("scores", "players")

# Bookmaker feeds. Many brands share one feed and therefore one set of prices,
# so requests name the feed rather than the individual brand: "Ladbrokes"
# covers Neds, "Betmakers" covers the 26 brands running on it. Asking for a
# brand name instead returns nothing.
AU_BOOKMAKERS = (
    "Bet365",
    "Sportsbet",
    "TAB",
    "Pointsbet",
    "Ladbrokes",
    "Unibet",
    "Betr",
    "BetRight",
    "PalmerBet",
    "NextBet",
    "PickleBet",
    "Dabble",
    "Amused",
    "Betmakers",
    "GenWeb",
    "PuntersTech",
    "BetCloud",
    "ApolloTech",
)

US_BOOKMAKERS = (
    "DraftKings",
    "BetMGM",
    "Fanatics",
    "theScoreBet",
    "Bovada",
    "Fliff",
    "Bet365",
    "Unibet",
)

EU_BOOKMAKERS = (
    "Bet365",
    "Pinnacle",
)

# Every feed once, in region order.
BOOKMAKERS = tuple(dict.fromkeys(AU_BOOKMAKERS + US_BOOKMAKERS + EU_BOOKMAKERS))
