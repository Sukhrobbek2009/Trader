"""Seed price_cache with placeholder prices. Usage: python seed_prices.py

Safe to re-run: existing rows (e.g. real prices fetched later) are never
overwritten. Run create_tables.py first.
"""
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert

from app.db import get_engine
from app.models import PriceCache

# coin_id values are CoinGecko's own ids, covering every coin the frontend lists.
# Prices are placeholders only (the frontend's old fallback prices).
PLACEHOLDERS = {
    "bitcoin": Decimal("67000"),
    "ethereum": Decimal("2600"),
    "tether": Decimal("1"),
    "solana": Decimal("165"),
    "binancecoin": Decimal("590"),
    "ripple": Decimal("0.52"),
    "dogecoin": Decimal("0.14"),
    "cardano": Decimal("0.45"),
    "avalanche-2": Decimal("28"),
    "chainlink": Decimal("14"),
}

if __name__ == "__main__":
    stmt = (
        insert(PriceCache)
        .values([{"coin_id": c, "price": p} for c, p in PLACEHOLDERS.items()])
        .on_conflict_do_nothing(index_elements=["coin_id"])
    )
    with get_engine().begin() as conn:
        result = conn.execute(stmt)
    print(f"Inserted {result.rowcount} new row(s); {len(PLACEHOLDERS)} coins seeded.")
