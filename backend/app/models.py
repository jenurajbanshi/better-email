"""Normalized data model.

Everything downstream of a connector speaks this schema -- never a
platform-specific shape. Every row carries an ``owner_id`` so the API can be
strictly tenant-scoped (a security control, enforced in the data layer).
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Direction(str, enum.Enum):
    inbound = "inbound"  # from the customer to us
    outbound = "outbound"  # from us to the customer


class RequestStatus(str, enum.Enum):
    needs_reply = "needs_reply"  # awaiting OUR response
    waiting = "waiting"  # awaiting the customer
    resolved = "resolved"


class Priority(str, enum.Enum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class IdentityKind(str, enum.Enum):
    email = "email"
    phone = "phone"
    handle = "handle"
    external_id = "external_id"


class SuggestionStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class Owner(Base):
    """The tenant. v1 is single-owner, but the column exists everywhere so
    multi-tenant is an additive change, not a refactor."""

    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    api_key_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    identities: Mapped[list["Identity"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    requests: Mapped[list["Request"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(back_populates="customer")


class Identity(Base):
    """A signal that ties a message to a customer (an address, phone, handle).
    The set of identities is how we stitch one customer across many channels."""

    __tablename__ = "identities"
    __table_args__ = (
        UniqueConstraint("owner_id", "kind", "normalized_value", name="uq_identity_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[IdentityKind] = mapped_column(Enum(IdentityKind))
    value: Mapped[str] = mapped_column(String(320))
    normalized_value: Mapped[str] = mapped_column(String(320), index=True)
    source: Mapped[str] = mapped_column(String(64), default="ingest")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    customer: Mapped[Customer] = relationship(back_populates="identities")


class Request(Base):
    """A single ask/case for a customer. A customer may have several."""

    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ask: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RequestStatus] = mapped_column(Enum(RequestStatus), default=RequestStatus.needs_reply)
    priority: Mapped[Priority] = mapped_column(Enum(Priority), default=Priority.normal)
    sentiment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    needs_response: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    customer: Mapped[Customer] = relationship(back_populates="requests")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="request", order_by="Message.received_at"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("owner_id", "platform", "platform_message_id", name="uq_platform_msg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(64))
    platform_message_id: Mapped[str] = mapped_column(String(255))
    thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    direction: Mapped[Direction] = mapped_column(Enum(Direction), default=Direction.inbound)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    from_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    to_addrs: Mapped[list] = mapped_column(JSON, default=list)
    subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[str | None] = mapped_column(String(512), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id", ondelete="SET NULL"), nullable=True, index=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    customer: Mapped[Customer | None] = relationship(back_populates="messages")
    request: Mapped[Request | None] = relationship(back_populates="messages")


class MergeSuggestion(Base):
    """A 'these might be the same customer' suggestion. We never silently merge
    across differing addresses -- a false merge is a privacy incident, so
    ambiguous cases land here for human confirmation."""

    __tablename__ = "merge_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    customer_id_a: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    customer_id_b: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[SuggestionStatus] = mapped_column(Enum(SuggestionStatus), default=SuggestionStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConnectorAccount(Base):
    """A connected external account (e.g. Gmail) for one owner.

    The OAuth token is stored ONLY encrypted at rest (Fernet via SECRET_KEY).
    ``last_sync_at`` is the incremental-sync cursor and ``history_id`` is kept
    for a future Gmail history.list / Pub/Sub push upgrade.
    """

    __tablename__ = "connector_accounts"
    __table_args__ = (
        UniqueConstraint("owner_id", "platform", name="uq_connector_owner_platform"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(64))
    account_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    encrypted_token: Mapped[str] = mapped_column(Text)
    history_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    """Append-only record of consequential actions (merges, sends, splits)."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
