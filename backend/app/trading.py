"""Execute a simulated trade at the server-side cached price.

Two entry points share one set of rules (settle): execute_trade for a user's
wallet (POST /trade) and execute_bot_trade for a bot's own cash pot. The price
comes only from price_cache, never from the caller.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Bot, BotPosition, BotTrade, Holding, PriceCache, Transaction, User

CENT = Decimal("0.01")


class TradeError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Fill:
    total: Decimal       # quantity x price, to the cent
    cash: Decimal        # cash after the trade
    quantity: Decimal    # position quantity after the trade (0 = closed)
    avg_cost: Decimal    # position average cost after the trade


def check_order(side: str, quantity: Decimal) -> None:
    if side not in ("buy", "sell"):
        raise TradeError(422, "Side must be 'buy' or 'sell'")
    if not quantity.is_finite() or quantity <= 0:
        raise TradeError(422, "Quantity must be greater than 0")


def cached_price(session: Session, coin_id: str) -> Decimal:
    cached = session.get(PriceCache, coin_id)
    if cached is None or cached.price <= 0:
        raise TradeError(404, f"Unknown coin '{coin_id}': no cached price")
    return cached.price


def settle(coin_id: str, side: str, quantity: Decimal, price: Decimal,
           cash: Decimal, held_qty: Decimal, held_avg: Decimal) -> Fill:
    """The buy/sell rules, as pure arithmetic: nothing is modified, so a rejected
    order (TradeError) changes nothing. Used for both wallet and bot trades."""
    check_order(side, quantity)
    total = (quantity * price).quantize(CENT, ROUND_HALF_UP)
    if total < CENT:
        raise TradeError(422, "Order is too small")

    if side == "buy":
        if total > cash:
            raise TradeError(400, f"Insufficient cash: this buy costs ${total} but you have ${cash}")
        new_qty = held_qty + quantity
        avg = ((held_qty * held_avg + quantity * price) / new_qty).quantize(Decimal("1e-12"))
        return Fill(total, cash - total, new_qty, avg)

    if held_qty < quantity:
        raise TradeError(
            400,
            f"Insufficient holdings: you hold {held_qty.normalize():f} {coin_id} but tried to sell {quantity.normalize():f}",
        )
    return Fill(total, cash + total, held_qty - quantity, held_avg)   # avg_cost is unchanged by a sale


def execute_trade(session: Session, user_id: int, coin_id: str, side: str,
                  quantity: Decimal) -> tuple[Transaction, User, Holding | None]:
    """Apply one buy/sell inside the caller's transaction (the caller commits or
    rolls back, so the three writes are all-or-nothing). Every check runs
    before any row is modified, so a rejected trade changes nothing.
    Raises TradeError on any rule violation."""
    check_order(side, quantity)

    # Lock the user row so concurrent trades for one user are serialized.
    user = session.execute(
        select(User).where(User.id == user_id).with_for_update()
    ).scalar_one()

    price = cached_price(session, coin_id)
    holding = session.get(Holding, (user_id, coin_id), with_for_update=True)
    fill = settle(coin_id, side, quantity, price, user.cash_balance,
                  holding.quantity if holding else Decimal(0),
                  holding.avg_cost if holding else Decimal(0))

    user.cash_balance = fill.cash
    if fill.quantity == 0:
        session.delete(holding)
        holding = None
    elif holding is None:
        holding = Holding(user_id=user_id, coin_id=coin_id, quantity=fill.quantity, avg_cost=fill.avg_cost)
        session.add(holding)
    else:
        holding.quantity, holding.avg_cost = fill.quantity, fill.avg_cost

    tx = Transaction(user_id=user_id, coin_id=coin_id, side=side,
                     quantity=quantity, price=price, total=fill.total)
    session.add(tx)
    session.flush()
    return tx, user, holding


def execute_bot_trade(session: Session, bot: Bot, side: str, quantity: Decimal,
                      reason: str) -> BotTrade:
    """Same rules as execute_trade, but against the bot's own cash (bot.bot_cash)
    and position (bot_positions), recording a bot_trades row tagged with `reason`.
    The caller must hold the bot row lock and commit or roll back."""
    check_order(side, quantity)
    price = cached_price(session, bot.coin_id)
    pos = session.get(BotPosition, (bot.id, bot.coin_id), with_for_update=True)
    fill = settle(bot.coin_id, side, quantity, price, bot.bot_cash,
                  pos.quantity if pos else Decimal(0),
                  pos.avg_cost if pos else Decimal(0))

    bot.bot_cash = fill.cash
    if fill.quantity == 0:
        session.delete(pos)
    elif pos is None:
        session.add(BotPosition(bot_id=bot.id, coin_id=bot.coin_id,
                                quantity=fill.quantity, avg_cost=fill.avg_cost))
    else:
        pos.quantity, pos.avg_cost = fill.quantity, fill.avg_cost

    trade = BotTrade(bot_id=bot.id, coin_id=bot.coin_id, side=side, quantity=quantity,
                     price=price, total=fill.total, reason=reason)
    session.add(trade)
    session.flush()
    return trade
