"""Paper-trading bot: hourly candles, multi-indicator signals, risk controls.

Trades only the simulated account (users/holdings/transactions rows). Run it at
most once per bar: the minimum timeframe is 1 hour, enforced in BotConfig.

CAVEAT: until a real historical-price table exists (see history.py), the hourly
closes it reads are a FAKE random walk, so signals are not meaningful market
signals. The machinery is real; the data is not.
"""
import logging
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .history import get_price_history
from .models import Holding, PriceCache, Transaction, User
from .strategy import evaluate
from .valuation import value_portfolio

log = logging.getLogger(__name__)

CENT = Decimal("0.01")
QTY_STEP = Decimal("0.000000000001")


@dataclass
class BotConfig:
    timeframe_hours: int = 1       # candle size and run interval; minimum 1
    position_pct: Decimal = Decimal("0.10")   # equity risked per buy
    max_coin_pct: Decimal = Decimal("0.25")   # max equity in any one coin
    stop_loss_pct: Decimal = Decimal("0.05")  # sell if price <= avg_cost * (1 - x)
    take_profit_pct: Decimal = Decimal("0.10")  # sell if price >= avg_cost * (1 + x)
    skip_coins: tuple[str, ...] = ("tether",)   # stablecoins don't trend

    def __post_init__(self):
        if self.timeframe_hours < 1:
            raise ValueError("timeframe_hours must be at least 1")


def hourly_closes(coin_id: str, session: Session, cfg: BotConfig) -> list[float]:
    pts = get_price_history(coin_id, 7, session)  # hourly points
    return [p["price"] for p in pts][:: -1][:: cfg.timeframe_hours][:: -1]


def run_bot_cycle(session: Session, user_id: int, cfg: BotConfig | None = None,
                  closes_fn=hourly_closes) -> list[str]:
    """One pass over every cached coin. Returns human-readable actions taken."""
    cfg = cfg or BotConfig()
    user = session.execute(
        select(User).where(User.id == user_id).with_for_update()
    ).scalar_one()
    prices = {p.coin_id: p.price for p in session.scalars(select(PriceCache))}
    holdings = {h.coin_id: h for h in session.scalars(select(Holding).where(Holding.user_id == user_id))}

    def equity() -> Decimal:
        return value_portfolio(
            user.cash_balance, [(c, h.quantity, h.avg_cost) for c, h in holdings.items()], prices
        ).total_value

    actions = []
    for coin_id, price in prices.items():
        if coin_id in cfg.skip_coins or price <= 0:
            continue
        held = holdings.get(coin_id)

        # Risk exits come first and ignore the indicators.
        reason = None
        if held:
            if price <= held.avg_cost * (1 - cfg.stop_loss_pct):
                reason = "stop-loss"
            elif price >= held.avg_cost * (1 + cfg.take_profit_pct):
                reason = "take-profit"
        sig = evaluate(closes_fn(coin_id, session, cfg))
        if held and not reason and sig.action == "sell":
            reason = "signal " + ",".join(sig.reasons)

        if held and reason:
            total = (held.quantity * price).quantize(CENT, ROUND_DOWN)
            session.add(Transaction(user_id=user_id, coin_id=coin_id, side="sell",
                                    quantity=held.quantity, price=price, total=total))
            user.cash_balance += total
            session.delete(held); del holdings[coin_id]
            actions.append(f"SELL {coin_id} @ {price} ({reason})")
        elif not held and sig.action == "buy":
            eq = equity()
            spend = min(user.cash_balance, eq * cfg.position_pct, eq * cfg.max_coin_pct).quantize(CENT, ROUND_DOWN)
            if spend < Decimal("1.00"):
                continue
            qty = (spend / price).quantize(QTY_STEP, ROUND_DOWN)
            if qty <= 0:
                continue
            session.add(Transaction(user_id=user_id, coin_id=coin_id, side="buy",
                                    quantity=qty, price=price, total=spend))
            h = Holding(user_id=user_id, coin_id=coin_id, quantity=qty, avg_cost=price)
            session.add(h); holdings[coin_id] = h
            user.cash_balance -= spend
            actions.append(f"BUY {coin_id} ${spend} @ {price} (score {sig.score}: {', '.join(sig.reasons)})")

    session.commit()
    for a in actions:
        log.info("bot user=%s %s", user_id, a)
    if not actions:
        log.info("bot user=%s: no trades this cycle", user_id)
    return actions
