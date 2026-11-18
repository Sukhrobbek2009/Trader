"""Display names for the coins the app lists (mirrors COINS in index.html).

price_cache only stores CoinGecko ids, so names and symbols live here. Keep this
in sync with the frontend list when coins are added.
"""
COINS: dict[str, tuple[str, str]] = {  # coin_id -> (name, symbol)
    "bitcoin": ("Bitcoin", "BTC"),
    "ethereum": ("Ethereum", "ETH"),
    "tether": ("Tether", "USDT"),
    "solana": ("Solana", "SOL"),
    "binancecoin": ("BNB", "BNB"),
    "ripple": ("XRP", "XRP"),
    "dogecoin": ("Dogecoin", "DOGE"),
    "cardano": ("Cardano", "ADA"),
    "avalanche-2": ("Avalanche", "AVAX"),
    "chainlink": ("Chainlink", "LINK"),
}


def search_coin_ids(term: str) -> list[str]:
    """Coin ids whose name or symbol contains `term` (case-insensitive), like the frontend search."""
    t = term.strip().lower()
    return [cid for cid, (name, sym) in COINS.items() if t in name.lower() or t in sym.lower()]
