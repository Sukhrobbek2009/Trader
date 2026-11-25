import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .db import get_engine
from .coins import COINS, search_coin_ids
from .bot import BotConfig, tick_all
from .history import MAX_DAYS, get_price_history
from .models import Bot, BotPosition, PriceCache, Transaction, User
from .prices import refresh_prices
from .trading import TradeError, execute_trade
from .valuation import snapshot_history, value_portfolio, take_daily_snapshots, value_user, yesterday_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

# Seconds between CoinGecko refreshes. Clamped to 30-60 to respect the free
# tier's rate limit while keeping prices fresh.
REFRESH_SECONDS = min(60, max(30, int(os.environ.get("PRICE_REFRESH_SECONDS", "45"))))


def _refresh_once() -> int:
    with Session(get_engine()) as session:
        updated = refresh_prices(session)
    try:  # daily portfolio snapshots piggyback on the loop; a failure must not stop price refreshes
        with Session(get_engine()) as session:
            n = take_daily_snapshots(session)
        if n:
            log.info("Recorded %d daily portfolio snapshot(s)", n)
    except Exception:
        log.exception("Daily snapshot failed")
    return updated


async def _refresh_loop():
    while True:
        try:
            # refresh_prices does blocking I/O, so keep it off the event loop.
            await asyncio.to_thread(_refresh_once)
        except Exception:
            log.exception("Price refresh crashed; will retry next cycle")
        await asyncio.sleep(REFRESH_SECONDS)


# Bots trade only while their status is 'running' (POST /bots/{id}/start), so the loop always runs.
# BOT_TIMEFRAME_HOURS is the candle size; BOT_TICK_SECONDS is how often every running bot is ticked.
BOT_CONFIG = BotConfig(timeframe_hours=int(os.environ.get("BOT_TIMEFRAME_HOURS", "1")))
BOT_TICK_SECONDS = max(10, int(os.environ.get("BOT_TICK_SECONDS", "45")))


def _bot_once():
    with Session(get_engine()) as session:
        tick_all(session, BOT_CONFIG)


async def _bot_loop():
    await asyncio.sleep(60)  # let the first price refresh land
    while True:
        try:
            await asyncio.to_thread(_bot_once)   # tick_all isolates each bot; this guards the rest
        except Exception:
            log.exception("Bot tick pass crashed; will retry next cycle")
        await asyncio.sleep(BOT_TICK_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(_refresh_loop()), asyncio.create_task(_bot_loop())]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


app = FastAPI(title="CoinLab API", lifespan=lifespan)

# The frontend sends the device_id cookie cross-origin (same site, different port), so
# credentials are allowed; that requires an explicit origin list, never "*".
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if o.strip()
]
if "*" in CORS_ORIGINS:  # with credentials, "*" would let any website act as the user
    raise RuntimeError("CORS_ORIGINS must list explicit origins, not '*'")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

DEVICE_COOKIE = "device_id"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 5  # 5 years
# Set COOKIE_SECURE=1 when served over HTTPS.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE") == "1"


def get_session():
    with Session(get_engine()) as session:
        yield session


class PriceOut(BaseModel):
    id: str  # CoinGecko coin id, e.g. "bitcoin"
    price: float  # USD; a JSON number, as the frontend expects
    updated_at: datetime  # when this price was last fetched from CoinGecko


class MeOut(BaseModel):
    id: int
    cash_balance: Decimal  # serialized as a string, e.g. "10000.00"


def _valid_device_id(value: str | None) -> str | None:
    """Accept only well-formed UUIDs so junk cookies can't be stored."""
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


@app.get("/health")
def health():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        # Don't leak connection details (they may include credentials).
        return JSONResponse(
            status_code=503, content={"status": "error", "database": "unreachable"}
        )
    return {"status": "ok", "database": "ok"}


@app.get("/prices", response_model=list[PriceOut])
def prices(session: Session = Depends(get_session)):
    rows = session.scalars(select(PriceCache).order_by(PriceCache.coin_id))
    return [PriceOut(id=r.coin_id, price=r.price, updated_at=r.fetched_at) for r in rows]


class HistoryPoint(BaseModel):
    t: int  # unix milliseconds
    price: float


@app.get("/prices/{coin_id}/history", response_model=list[HistoryPoint])
def price_history(
    coin_id: str,
    days: int = Query(7, ge=1, le=MAX_DAYS),
    session: Session = Depends(get_session),
):
    """Fake (random-walk) history ending at the cached price; see app/history.py."""
    try:
        return get_price_history(coin_id, days, session)
    except LookupError:
        raise HTTPException(status_code=404, detail="Unknown coin")


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path not in ("/trade", "/bots"):
        return await request_validation_exception_handler(request, exc)
    # Flatten to one readable message for the trade form.
    err = exc.errors()[0]
    if err["type"] == "value_error":      # raised by our own validators: the message is already user-ready
        return JSONResponse(status_code=422, content={"detail": str(err["ctx"]["error"])})
    field = ".".join(str(x) for x in err["loc"] if x != "body") or "request"
    return JSONResponse(status_code=422, content={"detail": f"Invalid {field}: {err['msg']}"})


class HoldingOut(BaseModel):
    coin_id: str
    quantity: Decimal
    avg_cost: Decimal
    current_price: Decimal | None
    current_value: Decimal | None   # null when the coin has no cached price
    gain_loss_pct: float | None     # vs avg_cost


class VsYesterdayOut(BaseModel):
    snapshot_at: datetime
    previous_value: Decimal
    gain_loss: Decimal
    gain_loss_pct: float | None


class PortfolioOut(BaseModel):
    cash_balance: Decimal
    total_value: Decimal
    unpriced_count: int             # holdings excluded from total_value (no price)
    vs_yesterday: VsYesterdayOut | None   # null until a snapshot from a previous day exists
    holdings: list[HoldingOut]


@app.get("/portfolio", response_model=PortfolioOut)
def portfolio(
    device_id: str | None = Cookie(default=None),
    session: Session = Depends(get_session),
):
    device = _valid_device_id(device_id)
    user = session.scalar(select(User).where(User.device_id == device)) if device else None
    if user is None:
        raise HTTPException(status_code=401, detail="No guest session; call GET /me first")

    val = value_user(session, user)          # the one shared valuation function
    snap = yesterday_snapshot(session, user.id)
    vs = None
    if snap is not None:
        gain = val.total_value - snap.total_value
        pct = float(gain / snap.total_value * 100) if snap.total_value > 0 else None
        vs = VsYesterdayOut(snapshot_at=snap.created_at, previous_value=snap.total_value,
                            gain_loss=gain, gain_loss_pct=pct)
    return PortfolioOut(
        cash_balance=val.cash_balance, total_value=val.total_value,
        unpriced_count=val.unpriced_count, vs_yesterday=vs,
        holdings=[HoldingOut(**vars(h)) for h in val.holdings],
    )


class SnapshotOut(BaseModel):
    created_at: datetime
    total_value: Decimal


@app.get("/portfolio/history", response_model=list[SnapshotOut])
def portfolio_history(
    limit: int = Query(365, ge=1, le=1000),
    device_id: str | None = Cookie(default=None),
    session: Session = Depends(get_session),
):
    """The guest user's daily snapshots, oldest first (the latest `limit` of them)."""
    device = _valid_device_id(device_id)
    user_id = session.scalar(select(User.id).where(User.device_id == device)) if device else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="No guest session; call GET /me first")
    return [SnapshotOut(created_at=r.created_at, total_value=r.total_value)
            for r in snapshot_history(session, user_id, limit)]


class TransactionOut(BaseModel):
    id: int
    coin_id: str
    coin_name: str | None
    symbol: str | None
    side: str
    quantity: Decimal
    price: Decimal
    total: Decimal
    created_at: datetime


class TransactionsOut(BaseModel):
    items: list[TransactionOut]          # newest first
    next_before: int | None              # pass as ?before= for the next (older) page; null = no more
    counts: dict[str, int]               # all/buy/sell under the coin + search filters (ignores side and paging)
    total_trades: int                    # all of this user's trades, unfiltered


@app.get("/transactions", response_model=TransactionsOut)
def transactions(
    side: Literal["all", "buy", "sell"] = "all",
    coin_id: str | None = Query(None, max_length=64),
    q: str | None = Query(None, max_length=64, description="matches coin name or symbol"),
    limit: int = Query(50, ge=1, le=200),
    before: int | None = Query(None, ge=1, description="return trades with id below this (cursor)"),
    device_id: str | None = Cookie(default=None),
    session: Session = Depends(get_session),
):
    """The guest user's trades, newest first, with the history page's filters."""
    device = _valid_device_id(device_id)
    user_id = session.scalar(select(User.id).where(User.device_id == device)) if device else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="No guest session; call GET /me first")

    base = [Transaction.user_id == user_id]            # coin + search filters (shared by items and counts)
    if coin_id and coin_id != "all":
        base.append(Transaction.coin_id == coin_id)
    if q and q.strip():
        base.append(Transaction.coin_id.in_(search_coin_ids(q)))   # no match -> empty IN -> no rows

    by_side = dict(session.execute(
        select(Transaction.side, func.count()).where(*base).group_by(Transaction.side)).all())
    counts = {"buy": by_side.get("buy", 0), "sell": by_side.get("sell", 0)}
    counts["all"] = counts["buy"] + counts["sell"]
    total_trades = session.scalar(select(func.count()).where(Transaction.user_id == user_id)) or 0

    where = list(base)
    if side != "all":
        where.append(Transaction.side == side)
    if before is not None:
        where.append(Transaction.id < before)
    # Fetch one extra row to learn whether another page exists.
    rows = session.scalars(select(Transaction).where(*where).order_by(Transaction.id.desc()).limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return TransactionsOut(
        items=[TransactionOut(id=t.id, coin_id=t.coin_id, coin_name=COINS.get(t.coin_id, (None, None))[0],
                              symbol=COINS.get(t.coin_id, (None, None))[1], side=t.side, quantity=t.quantity,
                              price=t.price, total=t.total, created_at=t.created_at) for t in rows],
        next_before=rows[-1].id if more else None,
        counts=counts,
        total_trades=total_trades,
    )


MAX_TRADE_QUANTITY = Decimal("1000000000")   # 1e9 units: far beyond anything the $10k simulator can afford


class TradeIn(BaseModel):
    # No price (or user id) field on purpose: the server uses its cached price and the cookie's user.
    # extra="forbid" turns any attempt to send one into an error instead of silently ignoring it.
    model_config = ConfigDict(extra="forbid")

    coin_id: str = Field(min_length=1, max_length=64)
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(max_digits=28, decimal_places=12)

    @field_validator("quantity")
    @classmethod
    def sensible_quantity(cls, v: Decimal) -> Decimal:
        # Runs while the request is parsed, i.e. before the cookie lookup, any query or any lock.
        if not v.is_finite() or v <= 0:
            raise ValueError("Quantity must be greater than 0")
        if v > MAX_TRADE_QUANTITY:
            raise ValueError("Quantity is too large")
        return v


class TradeOut(BaseModel):
    transaction_id: int
    coin_id: str
    side: str
    quantity: Decimal
    price: Decimal
    total: Decimal
    cash_balance: Decimal
    holding_quantity: Decimal  # 0 after selling everything
    holding_avg_cost: Decimal | None


@app.post("/trade", response_model=TradeOut)
def trade(
    body: TradeIn,
    device_id: str | None = Cookie(default=None),
    session: Session = Depends(get_session),
):
    device = _valid_device_id(device_id)
    if device is None:
        raise HTTPException(status_code=401, detail="No guest session; call GET /me first")
    try:
        # One database transaction: the cash update, the holdings update and the
        # transactions insert commit together, or (on any error, including a crash
        # before COMMIT) none of them do. execute_trade first takes a row lock on
        # the user (SELECT ... FOR UPDATE), so two simultaneous trades for the same
        # user run one after the other, each seeing the other's committed result.
        with session.begin():
            user_id = session.scalar(select(User.id).where(User.device_id == device))
            if user_id is None:
                raise HTTPException(status_code=401, detail="No guest session; call GET /me first")
            tx, user, holding = execute_trade(session, user_id, body.coin_id, body.side, body.quantity)
            out = TradeOut(
                transaction_id=tx.id, coin_id=tx.coin_id, side=tx.side, quantity=tx.quantity,
                price=tx.price, total=tx.total, cash_balance=user.cash_balance,
                holding_quantity=holding.quantity if holding else Decimal(0),
                holding_avg_cost=holding.avg_cost if holding else None,
            )
    except TradeError as e:
        # session.begin() has already rolled everything back.
        raise HTTPException(status_code=e.status, detail=e.message)
    return out


# Strategy names a bot can run. Only the multi-indicator signal in strategy.py exists so far.
BOT_STRATEGIES = ("indicators",)
CENT = Decimal("0.01")


class BotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coin_id: str = Field(min_length=1, max_length=64)
    strategy: Literal[BOT_STRATEGIES]  # type: ignore[valid-type]
    amount: Decimal = Field(max_digits=18, decimal_places=2)

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Decimal) -> Decimal:
        if not v.is_finite() or v <= 0:
            raise ValueError("Amount must be greater than 0")
        return v


class BotOut(BaseModel):
    id: int
    name: str
    coin_id: str
    strategy: str
    status: str
    bot_cash: Decimal
    cash_balance: Decimal  # the user's cash after funding the bot


@app.post("/bots", response_model=BotOut, status_code=201)
def create_bot(
    body: BotIn,
    device_id: str | None = Cookie(default=None),
    session: Session = Depends(get_session),
):
    device = _valid_device_id(device_id)
    if device is None:
        raise HTTPException(status_code=401, detail="No guest session; call GET /me first")
    if body.coin_id not in COINS:
        raise HTTPException(status_code=404, detail=f"Unknown coin '{body.coin_id}'")
    # One database transaction: the balance check, the debit and the bot insert
    # commit together or not at all. The FOR UPDATE lock on the user row makes two
    # simultaneous requests check the balance one after the other, so they can't
    # both spend the same cash.
    with session.begin():
        user = session.execute(
            select(User).where(User.device_id == device).with_for_update()
        ).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=401, detail="No guest session; call GET /me first")
        if body.amount > user.cash_balance:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient cash: the bot needs ${body.amount} but you have ${user.cash_balance}",
            )
        user.cash_balance -= body.amount
        name = f"{COINS[body.coin_id][1]} {body.strategy}"
        bot = Bot(user_id=user.id, name=name, coin_id=body.coin_id,
                  strategy=body.strategy, bot_cash=body.amount)
        session.add(bot)
        session.flush()
        out = BotOut(id=bot.id, name=bot.name, coin_id=bot.coin_id, strategy=bot.strategy,
                     status=bot.status, bot_cash=bot.bot_cash, cash_balance=user.cash_balance)
    return out


class BotStatusOut(BaseModel):
    id: int
    status: str
    bot_cash: Decimal


class BotWithdrawOut(BaseModel):
    id: int
    withdrawn: Decimal
    bot_cash: Decimal      # 0.00 after a withdrawal
    cash_balance: Decimal  # the user's wallet afterwards


def _locked_own_bot(session: Session, device: str | None, bot_id: int) -> tuple[User, Bot]:
    """Lock the caller's user row, then the bot, and return both (call inside session.begin()).

    A bot that doesn't exist and one that belongs to someone else both give the same 404,
    so ids can't be probed. Lock order (user, then bot) matches POST /bots.
    """
    if device is None:
        raise HTTPException(status_code=401, detail="No guest session; call GET /me first")
    user = session.execute(
        select(User).where(User.device_id == device).with_for_update()
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="No guest session; call GET /me first")
    bot = session.execute(
        select(Bot).where(Bot.id == bot_id, Bot.user_id == user.id).with_for_update()
    ).scalar_one_or_none()
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return user, bot


def _set_bot_status(bot_id: int, status: str, device_id: str | None, session: Session) -> BotStatusOut:
    # Only the status flips. Stopping never touches bot_positions or sells anything: the
    # bot just stops opening new entries. Repeating a call is harmless.
    with session.begin():
        _, bot = _locked_own_bot(session, _valid_device_id(device_id), bot_id)
        bot.status = status
        return BotStatusOut(id=bot.id, status=bot.status, bot_cash=bot.bot_cash)


@app.post("/bots/{bot_id}/start", response_model=BotStatusOut)
def start_bot(bot_id: int, device_id: str | None = Cookie(default=None),
              session: Session = Depends(get_session)):
    return _set_bot_status(bot_id, "running", device_id, session)


@app.post("/bots/{bot_id}/stop", response_model=BotStatusOut)
def stop_bot(bot_id: int, device_id: str | None = Cookie(default=None),
             session: Session = Depends(get_session)):
    return _set_bot_status(bot_id, "stopped", device_id, session)


@app.post("/bots/{bot_id}/withdraw", response_model=BotWithdrawOut)
def withdraw_bot(bot_id: int, device_id: str | None = Cookie(default=None),
                 session: Session = Depends(get_session)):
    with session.begin():
        user, bot = _locked_own_bot(session, _valid_device_id(device_id), bot_id)
        open_count = session.scalar(
            select(func.count()).select_from(BotPosition).where(BotPosition.bot_id == bot.id)
        )
        if open_count:
            raise HTTPException(
                status_code=409,
                detail="This bot has an open position. Wait for it to close before withdrawing.",
            )
        amount = bot.bot_cash
        if amount <= 0:
            raise HTTPException(status_code=400, detail="This bot has no cash to withdraw")
        user.cash_balance += amount
        bot.bot_cash = Decimal("0.00")
        return BotWithdrawOut(id=bot.id, withdrawn=amount, bot_cash=bot.bot_cash,
                              cash_balance=user.cash_balance)


class BotPositionOut(BaseModel):
    coin_id: str
    quantity: Decimal
    avg_cost: Decimal
    opened_at: datetime
    current_price: Decimal | None   # null when the coin has no usable cached price
    current_value: Decimal | None
    gain_loss_pct: float | None     # vs avg_cost


class BotDetailOut(BaseModel):
    id: int
    name: str
    coin_id: str
    strategy: str
    status: str
    risk_pct: Decimal
    stop_loss_pct: Decimal
    take_profit_pct: Decimal
    created_at: datetime
    bot_cash: Decimal
    position: BotPositionOut | None   # null when the bot holds nothing
    total_equity: Decimal             # bot_cash + position at the cached price
    unpriced_count: int               # positions left out of total_equity for lack of a price


def _bot_detail(bot: Bot, positions: list[BotPosition], prices: dict[str, Decimal]) -> BotDetailOut:
    # Same valuation routine as /portfolio, with the bot's own cash as the "cash".
    val = value_portfolio(bot.bot_cash, [(p.coin_id, p.quantity, p.avg_cost) for p in positions], prices)
    opened = {p.coin_id: p.opened_at for p in positions}
    shown = next(
        (BotPositionOut(coin_id=h.coin_id, quantity=h.quantity, avg_cost=h.avg_cost,
                        opened_at=opened[h.coin_id], current_price=h.current_price,
                        current_value=h.current_value, gain_loss_pct=h.gain_loss_pct)
         for h in val.holdings),
        None,
    )
    return BotDetailOut(
        id=bot.id, name=bot.name, coin_id=bot.coin_id, strategy=bot.strategy, status=bot.status,
        risk_pct=bot.risk_pct, stop_loss_pct=bot.stop_loss_pct, take_profit_pct=bot.take_profit_pct,
        created_at=bot.created_at, bot_cash=bot.bot_cash, position=shown,
        total_equity=val.total_value, unpriced_count=val.unpriced_count,
    )


def _current_user_id(session: Session, device_id: str | None) -> int:
    device = _valid_device_id(device_id)
    user_id = session.scalar(select(User.id).where(User.device_id == device)) if device else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="No guest session; call GET /me first")
    return user_id


@app.post("/bots/tick")
def tick_bots(device_id: str | None = Cookie(default=None), session: Session = Depends(get_session)):
    """Run one tick pass now over the caller's running bots; each decision is logged.
    Scoped to the caller so one guest can't trigger trades on another's bots."""
    user_id = _current_user_id(session, device_id)
    session.rollback()
    decisions = tick_all(session, BOT_CONFIG, user_id=user_id)
    if decisions is None:
        raise HTTPException(status_code=409, detail="A tick is already running; try again in a moment")
    return {"decisions": decisions}


@app.get("/bots", response_model=list[BotDetailOut])
def list_bots(device_id: str | None = Cookie(default=None), session: Session = Depends(get_session)):
    user_id = _current_user_id(session, device_id)
    bots = session.scalars(select(Bot).where(Bot.user_id == user_id).order_by(Bot.id)).all()
    prices = {p.coin_id: p.price for p in session.scalars(select(PriceCache))}
    by_bot: dict[int, list[BotPosition]] = {}
    for pos in session.scalars(
        select(BotPosition).where(BotPosition.bot_id.in_([b.id for b in bots]))
    ):
        by_bot.setdefault(pos.bot_id, []).append(pos)
    return [_bot_detail(b, by_bot.get(b.id, []), prices) for b in bots]


@app.get("/bots/{bot_id}", response_model=BotDetailOut)
def get_bot(bot_id: int, device_id: str | None = Cookie(default=None),
            session: Session = Depends(get_session)):
    user_id = _current_user_id(session, device_id)
    # Someone else's bot and a missing bot both give 404, as in the other /bots routes.
    bot = session.scalar(select(Bot).where(Bot.id == bot_id, Bot.user_id == user_id))
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    positions = list(session.scalars(select(BotPosition).where(BotPosition.bot_id == bot.id)))
    prices = {p.coin_id: p.price for p in session.scalars(select(PriceCache))}
    return _bot_detail(bot, positions, prices)


@app.get("/me", response_model=MeOut)
def me(
    response: Response,
    device_id: str | None = Cookie(default=None),
    session: Session = Depends(get_session),
):
    device = _valid_device_id(device_id)
    is_new_device = device is None
    if is_new_device:
        device = str(uuid.uuid4())

    # Idempotent create: if the cookie exists but its row doesn't (e.g. DB reset),
    # or two requests race, the unique device_id makes this a no-op.
    # cash_balance uses the column default of 10000.00.
    session.execute(
        insert(User).values(device_id=device).on_conflict_do_nothing(index_elements=["device_id"])
    )
    user = session.execute(select(User).where(User.device_id == device)).scalar_one()
    session.commit()

    if is_new_device:
        response.set_cookie(
            DEVICE_COOKIE,
            device,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=COOKIE_SECURE,
        )
    return MeOut(id=user.id, cash_balance=user.cash_balance)
