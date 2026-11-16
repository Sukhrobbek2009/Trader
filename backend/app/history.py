"""Price history for charts and sparklines.

NOTE: this is FAKE data, on purpose. get_price_history() builds a believable
random walk that ends exactly at the current cached price; it is not real market
history. A real historical-price table (stored CoinGecko snapshots or a
market_chart import) is a "Beyond Launch" upgrade. When that lands, only the body
of this function needs to change: keep the same signature and return shape so the
endpoint and frontend don't have to.
"""
import math
import random
import time

from sqlalchemy.orm import Session

from .models import PriceCache

# Rough typical daily volatility (std dev of daily log-return) by coin.
DEFAULT_DAILY_VOL = 0.025
DAILY_VOL = {"tether": 0.0005}
MAX_DAYS = 365


def get_price_history(coin_id: str, days: int, session: Session) -> list[dict]:
    """Return [{"t": unix_ms, "price": float}, ...] oldest -> newest (fake, see above).

    Hourly points for ranges up to 7 days, daily points beyond that. The newest
    point is the current cached price. Raises LookupError if the coin isn't cached.
    """
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_DAYS}")
    row = session.get(PriceCache, coin_id)
    if row is None:
        raise LookupError(coin_id)

    step_hours = 1 if days <= 7 else 24
    n = days * 24 // step_hours + 1
    step_ms = step_hours * 3_600_000
    sigma = DAILY_VOL.get(coin_id, DEFAULT_DAILY_VOL) * math.sqrt(step_hours / 24)

    now_ms = int(time.time() * 1000)
    # Seed per coin/range/hour: the curve is stable between refreshes (no sparkline
    # flicker) but drifts slowly over time.
    rng = random.Random(f"{coin_id}:{days}:{now_ms // 3_600_000}")

    # Walk backwards from the current price so the series ends exactly on it.
    price = float(row.price)
    points = [{"t": now_ms, "price": price}]
    for i in range(1, n):
        price *= math.exp(-rng.gauss(0, sigma))
        points.append({"t": now_ms - i * step_ms, "price": price})
    points.reverse()
    return points
