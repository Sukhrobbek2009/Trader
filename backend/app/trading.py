"""Execute a simulated trade at the server-side cached price."""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Holding, PriceCache, Transaction, User

CENT = Decimal("0.01")


class TradeError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def execute_trade(session: Session, user_id: int, coin_id: str, side: str,
                  quantity: Decimal) -> tuple[Transaction, User, Holding | None]:
    """Apply one buy/sell inside the caller's transaction (the caller commits or
    rolls back, so the three writes are all-or-nothing). Every check below runs
    before any row is modified, so a rejected trade changes nothing. The price comes only from
    price_cache, never from the client. Raises TradeError on any rule violation."""
    if side not in ("buy", "sell"):
        raise TradeError(422, "Side must be 'buy' or 'sell'")
    if not quantity.is_finite() or quantity <= 0:
        raise TradeError(422, "Quantity must be greater than 0")

    # Lock the user row so concurrent trades for one user are serialized.
    user = session.execute(
        select(User).where(User.id == user_id).with_for_update()
    ).scalar_one()

    cached = session.get(PriceCache, coin_id)
    if cached is None or cached.price <= 0:
        raise TradeError(404, f"Unknown coin '{coin_id}': no cached price")
    price = cached.price

    total = (quantity * price).quantize(CENT, ROUND_HALF_UP)
    if total < CENT:
        raise TradeError(422, "Order is too small")

    holding = session.get(Holding, (user_id, coin_id), with_for_update=True)

    if side == "buy":
        if total > user.cash_balance:
            raise TradeError(400, f"Insufficient cash: this buy costs ${total} but you have ${user.cash_balance}")
        user.cash_balance -= total
        if holding is None:
            holding = Holding(user_id=user_id, coin_id=coin_id, quantity=quantity, avg_cost=price)
            session.add(holding)
        else:
            new_qty = holding.quantity + quantity
            holding.avg_cost = ((holding.quantity * holding.avg_cost + quantity * price) / new_qty).quantize(Decimal("1e-12"))
            holding.quantity = new_qty
    else:
        held = holding.quantity if holding else Decimal(0)
        if held < quantity:
            raise TradeError(
                400,
                f"Insufficient holdings: you hold {held.normalize():f} {coin_id} but tried to sell {quantity.normalize():f}",
            )
        user.cash_balance += total
        holding.quantity -= quantity          # avg_cost is unchanged by a sale
        if holding.quantity == 0:
            session.delete(holding)
            holding = None

    tx = Transaction(user_id=user_id, coin_id=coin_id, side=side,
                     quantity=quantity, price=price, total=total)
    session.add(tx)
    session.flush()
    return tx, user, holding
