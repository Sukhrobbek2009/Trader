"""Paper-trading bots: each running bot trades one coin from its own cash pot.

Every buy and sell goes through trading.execute_bot_trade, which shares its
rules with POST /trade (trading.settle), and each bot_trades row carries a
`reason`. Run at most once per bar: the minimum timeframe is 1 hour.

CAVEAT: the hourly closes still come from history.get_price_history, which is a
FAKE random walk, so signals are not meaningful market signals. The machinery is
real; the data is not.
"""
import logging
import threading
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .history import get_price_history
from .models import Bot, BotPosition, PriceCache
from .strategy import evaluate
from .trading import TradeError, execute_bot_trade

log = logging.getLogger(__name__)

QTY_STEP = Decimal("0.000000000001")
MIN_TRADE_USD = Decimal("10")
HUNDRED = Decimal(100)


@dataclass
class BotConfig:
    timeframe_hours: int = 1       # candle size and run interval; minimum 1

    def __post_init__(self):
        if self.timeframe_hours < 1:
            raise ValueError("timeframe_hours must be at least 1")


def hourly_closes(coin_id: str, session: Session, cfg: BotConfig) -> list[float]:
    pts = get_price_history(coin_id, 7, session)  # hourly points
    return [p["price"] for p in pts][:: -1][:: cfg.timeframe_hours][:: -1]


def buy_quantity(equity: Decimal, bot_cash: Decimal, price: Decimal,
                 risk_pct: Decimal, stop_loss_pct: Decimal) -> Decimal:
    """Size a buy so that hitting the stop-loss loses about risk_pct% of equity:
        quantity = (equity x risk_pct/100) / (price x stop_loss_pct/100)
    capped so the cost never exceeds bot_cash. Returns 0 if the stop is 0."""
    if price <= 0 or stop_loss_pct <= 0:
        return Decimal(0)
    qty = (equity * risk_pct / HUNDRED) / (price * stop_loss_pct / HUNDRED)
    qty = min(qty, bot_cash / price)
    return qty.quantize(QTY_STEP, ROUND_DOWN)


def tick(session: Session, bot_id: int, cfg: BotConfig, closes_fn=hourly_closes) -> str:
    """One decision for one bot, in one transaction. Always returns a readable
    decision, e.g. 'BUY bitcoin $500.00 @ 100 (signal ...)' or 'HOLD (no signal)'."""
    with session.begin():
        bot = session.execute(select(Bot).where(Bot.id == bot_id).with_for_update()).scalar_one()
        if bot.status != "running":
            return "SKIP (not running)"
        price = session.scalar(select(PriceCache.price).where(PriceCache.coin_id == bot.coin_id))
        if price is None or price <= 0:
            return f"HOLD (no price for {bot.coin_id})"
        pos = session.get(BotPosition, (bot.id, bot.coin_id))

        # Risk exits come first and ignore the indicators.
        reason = None
        if pos:
            if price <= pos.avg_cost * (1 - bot.stop_loss_pct / HUNDRED):
                reason = "stop-loss"
            elif price >= pos.avg_cost * (1 + bot.take_profit_pct / HUNDRED):
                reason = "take-profit"
        sig = evaluate(closes_fn(bot.coin_id, session, cfg))

        if pos and (reason or sig.action == "sell"):
            reason = reason or "signal: " + ", ".join(sig.reasons)
            t = execute_bot_trade(session, bot, "sell", pos.quantity, reason)
        elif not pos and sig.action == "buy":
            equity = bot.bot_cash   # no open position, so equity is the cash
            qty = buy_quantity(equity, bot.bot_cash, price, bot.risk_pct, bot.stop_loss_pct)
            if qty * price < MIN_TRADE_USD:
                return f"HOLD (buy signal, but ${(qty * price):.2f} is under the ${MIN_TRADE_USD} minimum)"
            t = execute_bot_trade(session, bot, "buy", qty,
                                  f"signal (score {sig.score}): " + ", ".join(sig.reasons))
        else:
            return f"HOLD ({'holding' if pos else 'flat'}, signal {sig.action}, score {sig.score})"
        return f"{t.side.upper()} {t.coin_id} ${t.total} @ {t.price} ({t.reason})"


# One pass at a time: the background loop and POST /bots/tick both take this, so
# ticks can never overlap (and never double-trade the same bot).
_tick_lock = threading.Lock()


def tick_all(session: Session, cfg: BotConfig | None = None, closes_fn=hourly_closes,
             user_id: int | None = None) -> list[str] | None:
    """Tick every running bot (or only user_id's), logging each decision. A failure in
    one bot is logged and never stops the others. Returns the decisions, or None if
    another pass is already running."""
    if not _tick_lock.acquire(blocking=False):
        log.info("bots: previous tick still running; skipping this one")
        return None
    try:
        cfg = cfg or BotConfig()
        q = select(Bot.id).where(Bot.status == "running").order_by(Bot.id)
        if user_id is not None:
            q = q.where(Bot.user_id == user_id)
        ids = list(session.scalars(q))
        session.rollback()   # end the implicit read transaction so tick() can begin its own
        decisions = []
        for bot_id in ids:
            try:
                d = tick(session, bot_id, cfg, closes_fn)
            except TradeError as e:
                d = f"REJECTED ({e.message})"
            except Exception:
                log.exception("bot %s: tick failed", bot_id)
                session.rollback()
                d = "ERROR (see log)"
            log.info("bot %s: %s", bot_id, d)
            decisions.append(f"bot {bot_id}: {d}")
        if not ids:
            log.info("bots: none running")
        return decisions
    finally:
        _tick_lock.release()
