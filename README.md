# rapidoddsapi

Official Python SDK for [RapidOddsAPI](https://rapidoddsapi.com) — sports betting odds,
live scores and player stats, over REST and WebSocket.

```bash
pip install rapidoddsapi
```

```python
from rapidoddsapi import RapidOddsAPI

client = RapidOddsAPI(api_key="oa_your_api_key_here")
games = client.get_odds("afl", market_types=["h2h"])
```

Full documentation: [rapidoddsapi.com/docs](https://rapidoddsapi.com/docs)

> This README is a placeholder — full install, quickstart, streaming, method
> reference and error handling docs land with the first release.

## License

MIT
