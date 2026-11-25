from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# Money is NUMERIC(18,2); coin quantities/prices need more precision.
QTY = Numeric(28, 12)
PRICE = Numeric(28, 12)
MONEY = Numeric(18, 2)
PCT = Numeric(6, 2)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable + unique: anonymous device-based users now, real email later.
    device_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    cash_balance: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("10000.00"), server_default="10000.00"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Holding(Base):
    __tablename__ = "holdings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    coin_id: Mapped[str] = mapped_column(String, primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(PRICE, nullable=False)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="ck_transactions_side"),
        Index("ix_transactions_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    coin_id: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PriceCache(Base):
    __tablename__ = "price_cache"

    coin_id: Mapped[str] = mapped_column(String, primary_key=True)
    price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (Index("ix_snapshots_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    total_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Bot(Base):
    __tablename__ = "bots"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'stopped')", name="ck_bots_status"),
        CheckConstraint("bot_cash >= 0", name="ck_bots_bot_cash"),
        Index("ix_bots_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    coin_id: Mapped[str] = mapped_column(String, nullable=False)
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    # Cash set aside for this bot; moved out of users.cash_balance on creation.
    bot_cash: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0"), server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="stopped", server_default="stopped"
    )
    # Percentages as plain numbers: 2.5 means 2.5%.
    risk_pct: Mapped[Decimal] = mapped_column(
        PCT, nullable=False, default=Decimal("2.5"), server_default="2.5"
    )
    stop_loss_pct: Mapped[Decimal] = mapped_column(
        PCT, nullable=False, default=Decimal("5"), server_default="5"
    )
    take_profit_pct: Mapped[Decimal] = mapped_column(
        PCT, nullable=False, default=Decimal("10"), server_default="10"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BotPosition(Base):
    __tablename__ = "bot_positions"

    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True
    )
    coin_id: Mapped[str] = mapped_column(String, primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BotTrade(Base):
    __tablename__ = "bot_trades"
    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="ck_bot_trades_side"),
        Index("ix_bot_trades_bot_created", "bot_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    coin_id: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BotEquity(Base):
    __tablename__ = "bot_equity"
    __table_args__ = (Index("ix_bot_equity_bot_created", "bot_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
