"""Refresh price_cache from CoinGecko's free /simple/price endpoint (no API key)."""
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import PriceCache

log = logging.getLogger(__name__)

SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
TIMEOUT_SECONDS = 10


def fetch_prices(coin_ids: list[str]) -> dict[str, Decimal]:
    """Return {coin_id: usd_price}. Raises on network/HTTP/parse errors.

    Coins that CoinGecko omits, or returns with a missing/non-positive price,
    are left out of the result.
    """
    query = urllib.parse.urlencode({"ids": ",".join(coin_ids), "vs_currencies": "usd"})
    req = urllib.request.Request(
        f"{SIMPLE_PRICE_URL}?{query}", headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        # parse_float=Decimal avoids binary-float rounding of prices.
        data = json.load(resp, parse_float=Decimal, parse_int=Decimal)

    prices: dict[str, Decimal] = {}
    for coin_id in coin_ids:
        try:
            price = Decimal(data[coin_id]["usd"])
        except (KeyError, TypeError, ArithmeticError):
            continue
        if price.is_finite() and price > 0:
            prices[coin_id] = price
    return prices


def refresh_prices(session: Session) -> int:
    """Update price and fetched_at for every coin in price_cache.

    On any CoinGecko failure (timeout, HTTP error such as 429, bad JSON) the
    cache is left untouched, so the last known prices stay in place. Coins
    missing from a response keep their old row too. Returns rows updated.
    """
    coin_ids = list(session.scalars(select(PriceCache.coin_id)))
    if not coin_ids:
        return 0
    try:
        prices = fetch_prices(coin_ids)
    except Exception as exc:
        log.warning("CoinGecko refresh failed; serving stale cached prices: %s", exc)
        return 0

    stale = sorted(set(coin_ids) - set(prices))
    if stale:
        log.warning("No fresh price for %s; keeping stale cached price", ", ".join(stale))

    now = datetime.now(timezone.utc)
    for coin_id, price in prices.items():
        session.execute(
            update(PriceCache)
            .where(PriceCache.coin_id == coin_id)
            .values(price=price, fetched_at=now)
        )
    session.commit()
    if prices:
        log.info("Refreshed %d/%d cached prices from CoinGecko", len(prices), len(coin_ids))
    return len(prices)


if __name__ == "__main__":
    from .db import get_engine

    logging.basicConfig(level=logging.INFO)
    with Session(get_engine()) as s:
        print(f"Updated {refresh_prices(s)} price(s).")
