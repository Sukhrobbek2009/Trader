import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .db import get_engine
from .bot import BotConfig, run_bot_cycle
from .history import MAX_DAYS, get_price_history
from .models import PriceCache, User
from .prices import refresh_prices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

# Seconds between CoinGecko refreshes. Clamped to 30-60 to respect the free
# tier's rate limit while keeping prices fresh.
REFRESH_SECONDS = min(60, max(30, int(os.environ.get("PRICE_REFRESH_SECONDS", "45"))))


def _refresh_once() -> int:
    with Session(get_engine()) as session:
        return refresh_prices(session)


async def _refresh_loop():
    while True:
        try:
            # refresh_prices does blocking I/O, so keep it off the event loop.
            await asyncio.to_thread(_refresh_once)
        except Exception:
            log.exception("Price refresh crashed; will retry next cycle")
        await asyncio.sleep(REFRESH_SECONDS)


# Trading bot is OFF unless BOT_USER_IDS lists users to trade for, e.g. "1,2".
# BOT_TIMEFRAME_HOURS is both the candle size and the run interval (minimum 1).
BOT_USER_IDS = [int(x) for x in os.environ.get("BOT_USER_IDS", "").split(",") if x.strip()]
BOT_CONFIG = BotConfig(timeframe_hours=int(os.environ.get("BOT_TIMEFRAME_HOURS", "1")))


def _bot_once():
    for uid in BOT_USER_IDS:
        try:
            with Session(get_engine()) as session:
                run_bot_cycle(session, uid, BOT_CONFIG)
        except Exception:
            log.exception("Bot cycle failed for user %s", uid)


async def _bot_loop():
    await asyncio.sleep(60)  # let the first price refresh land
    while True:
        await asyncio.to_thread(_bot_once)
        await asyncio.sleep(BOT_CONFIG.timeframe_hours * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(_refresh_loop())]
    if BOT_USER_IDS:
        tasks.append(asyncio.create_task(_bot_loop()))
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


app = FastAPI(title="CoinLab API", lifespan=lifespan)

# /prices is public and cookie-free, so no credentials are needed cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.environ.get(
            "CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
        ).split(",")
        if o.strip()
    ],
    allow_methods=["GET"],
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
