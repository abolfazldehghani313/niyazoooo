from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ads: Mapped[list["Ad"]] = relationship(back_populates="owner")

class Ad(Base):
    __tablename__ = "ads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    city: Mapped[str] = mapped_column(String(80), default="")
    category: Mapped[str] = mapped_column(String(80), default="عمومی", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    owner: Mapped[User] = relationship(back_populates="ads")


class AdCampaign(Base):
    __tablename__ = "ad_campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(150))
    ad_type: Mapped[str] = mapped_column(String(20), index=True)  # banner | interstitial
    image_url: Mapped[str] = mapped_column(Text, default="")
    video_url: Mapped[str] = mapped_column(Text, default="")
    media_type: Mapped[str] = mapped_column(String(20), default="image")  # image | video
    target_url: Mapped[str] = mapped_column(Text, default="")
    placement: Mapped[str] = mapped_column(String(80), default="home")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    frequency_cap: Mapped[int] = mapped_column(Integer, default=3)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    service_name: Mapped[str] = mapped_column(String(200))
    checkout_token: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    payment_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="initiated", index=True)
    trace_status: Mapped[str] = mapped_column(String(60), default="unpaid")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Wallet(Base):
    __tablename__ = "wallets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"), unique=True, nullable=True, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30), default="credit")
    title: Mapped[str] = mapped_column(String(160), default="شارژ کیف پول")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
