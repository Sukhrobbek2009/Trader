"""The one place a portfolio is valued, plus the daily snapshots built from it.

value_portfolio() is shared by GET /portfolio, the daily snapshot job and the
trading bot, so every number in the app agrees.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Holding, PortfolioSnapshot, PriceCache, User

CENT = Decimal("0.01")


@dataclass
class HoldingValue:
    coin_id: str
    quantity: Decimal
    avg_cost: Decimal
    current_price: Decimal | None      # None = no usable cached price
    current_value: Decimal | None      # quantity x price, to the cent
    gain_loss_pct: float | None        # vs avg_cost; None when unpriced or cost unknown


@dataclass
class Valuation:
    cash_balance: Decimal
    total_value: Decimal               # cash + priced holdings
    holdings: list[HoldingValue]
    unpriced_count: int                # holdings left OUT of total_value for lack of a price


def value_portfolio(
    cash: Decimal,
    holdings: Iterable[tuple[str, Decimal, Decimal]],   # (coin_id, quantity, avg_cost)
    prices: dict[str, Decimal],
) -> Valuation:
    rows, total, unpriced = [], cash, 0
    for coin_id, qty, avg in holdings:
        if qty <= 0:
            continue
        price = prices.get(coin_id)
        if price is None or price <= 0:
            unpriced += 1
            rows.append(HoldingValue(coin_id, qty, avg, None, None, None))
            continue
        value = (qty * price).quantize(CENT, ROUND_HALF_UP)
        total += value   # sum the rounded values so the table adds up to the total
        gain = float((price / avg - 1) * 100) if avg > 0 else None
        rows.append(HoldingValue(coin_id, qty, avg, price, value, gain))
    return Valuation(cash, total, rows, unpriced)


def value_user(session: Session, user: User) -> Valuation:
    prices = {p.coin_id: p.price for p in session.scalars(select(PriceCache))}
    held = session.scalars(select(Holding).where(Holding.user_id == user.id).order_by(Holding.coin_id))
    return value_portfolio(user.cash_balance, [(h.coin_id, h.quantity, h.avg_cost) for h in held], prices)


# ---- Daily snapshots (UTC days) ----

def _day_start(now: datetime) -> datetime:
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def yesterday_snapshot(session: Session, user_id: int, now: datetime | None = None) -> PortfolioSnapshot | None:
    """The user's latest snapshot taken before today (UTC), or None."""
    start = _day_start(now or datetime.now(timezone.utc))
    return session.scalars(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.user_id == user_id, PortfolioSnapshot.created_at < start)
        .order_by(PortfolioSnapshot.created_at.desc())
        .limit(1)
    ).first()


def take_daily_snapshots(session: Session, now: datetime | None = None, force: bool = False) -> int:
    """Record one snapshot per user per UTC day (first call of the day wins), so it
    is cheap to call often; the server's refresh loop does exactly that. With
    force=True, snapshot every user regardless (for testing). Returns rows written."""
    query = select(User)
    if not force:
        start = _day_start(now or datetime.now(timezone.utc))
        done = select(PortfolioSnapshot.user_id).where(PortfolioSnapshot.created_at >= start)
        query = query.where(User.id.not_in(done))
    users = list(session.scalars(query))
    for user in users:
        session.add(PortfolioSnapshot(user_id=user.id, total_value=value_user(session, user).total_value))
    session.commit()
    return len(users)


def snapshot_history(session: Session, user_id: int, limit: int = 365) -> list[PortfolioSnapshot]:
    """The user's most recent `limit` snapshots, oldest first."""
    rows = session.scalars(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.user_id == user_id)
        .order_by(PortfolioSnapshot.created_at.desc(), PortfolioSnapshot.id.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))
