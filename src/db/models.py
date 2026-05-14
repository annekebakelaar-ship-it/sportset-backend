"""
Sportset database models: User, OuraToken, Subscription, Payment

These extend the existing ORM setup in orm_models.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ============================================================================
# User Model (Sportset users)
# ============================================================================


class User(Base):
    """
    Sportset user account.
    
    Fields:
        id: UUID primary key
        email: Unique email address (used for login)
        name: Display name
        hashed_password: bcrypt-hashed password (for email/password auth)
        subscription_status: active | cancelled | expired
        is_active: Account enabled/disabled
        created_at: Registration timestamp
        updated_at: Last update timestamp
    """
    
    __tablename__ = "sportset_users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_sportset_user_email"),
    )
    
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    subscription_status: Mapped[str] = mapped_column(
        String(50), default="active",
        comment="active | cancelled | expired | trial"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    
    # Relationships
    oura_tokens: Mapped[list["OuraToken"]] = relationship(
        "OuraToken", back_populates="user", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="user", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment", back_populates="user", cascade="all, delete-orphan"
    )


# ============================================================================
# Oura OAuth Token Model (encrypted token storage)
# ============================================================================


class OuraToken(Base):
    """
    Oura OAuth tokens for a user (access_token + refresh_token).
    
    Tokens are encrypted at-rest using AES-256-GCM (see src/core/security.py).
    
    Fields:
        id: UUID primary key
        user_id: FK to User
        encrypted_data: AES-256-GCM encrypted JSON with:
            - access_token
            - refresh_token
            - expires_at (ISO timestamp)
            - token_type: "Bearer"
        created_at: When token was first obtained
        last_refreshed_at: When token was last refreshed
        expires_at: Cached expiry time (helps avoid decryption for expiry checks)
    """
    
    __tablename__ = "sportset_oura_tokens"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_oura_token_user_id"),
    )
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("sportset_users.id"), nullable=False)
    encrypted_data: Mapped[str] = mapped_column(Text, nullable=False, comment="AES-256-GCM encrypted JSON")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="Cached expiry for quick checks")
    
    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="oura_tokens")


# ============================================================================
# Subscription Model
# ============================================================================


class Subscription(Base):
    """
    User subscription to Sportset premium.
    
    Fields:
        id: UUID primary key
        user_id: FK to User
        status: active | cancelled | expired | trial
        plan_id: Subscription plan identifier (e.g., "premium", "pro")
        started_at: Subscription start date
        expires_at: When subscription expires (None = indefinite)
        renewal_date: Next automatic renewal (or None if cancelled)
    """
    
    __tablename__ = "sportset_subscriptions"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("sportset_users.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="active",
        comment="active | cancelled | expired | trial"
    )
    plan_id: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    renewal_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    
    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="subscriptions")


# ============================================================================
# Payment Model (Mollie integration)
# ============================================================================


class Payment(Base):
    """
    Payment transaction via Mollie.
    
    Fields:
        id: UUID primary key
        user_id: FK to User
        mollie_payment_id: Mollie payment ID (returned from checkout creation)
        amount: Amount in cents (e.g., 2999 = €29.99)
        currency: ISO currency code (e.g., "EUR")
        status: open | pending | paid | expired | failed | cancelled
        mollie_checkout_url: Redirect URL for user to complete payment
        plan_id: What subscription plan was purchased
        paid_at: When payment was successfully completed
        created_at: Payment record creation timestamp
        updated_at: Last webhook/status update
        metadata: Additional JSON data (e.g., order details)
    """
    
    __tablename__ = "sportset_payments"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("sportset_users.id"), nullable=False)
    mollie_payment_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    amount: Mapped[int] = mapped_column(nullable=False, comment="Amount in cents")
    currency: Mapped[str] = mapped_column(String(3), default="EUR", comment="ISO currency code")
    status: Mapped[str] = mapped_column(
        String(50), default="open",
        comment="open | pending | paid | expired | failed | cancelled"
    )
    mollie_checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_id: Mapped[str] = mapped_column(String(100), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    metadata: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON metadata")
    
    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="payments")
