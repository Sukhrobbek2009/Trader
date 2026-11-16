from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# Money is NUMERIC(18,2); coin quantities/prices need more precision.
QTY = Numeric(28, 12)
PRICE = Numeric(28, 12)
MONEY = Numeric(18, 2)


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
