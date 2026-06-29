"""API response/request schemas (the typed contract shared with the frontend)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IdentityOut(BaseModel):
    kind: str
    value: str
    source: str


class MessageOut(BaseModel):
    id: int
    direction: str
    platform: str
    from_name: str | None
    from_email: str | None
    subject: str | None
    body: str
    snippet: str | None
    received_at: datetime


class RequestSummaryOut(BaseModel):
    id: int
    title: str
    summary: str | None
    ask: str | None
    status: str
    priority: str
    sentiment: str | None
    channel: str | None
    needs_response: bool
    forgotten: bool
    message_count: int
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None


class RequestDetailOut(RequestSummaryOut):
    customer_id: int
    customer_name: str
    messages: list[MessageOut]


class CustomerInboxOut(BaseModel):
    id: int
    display_name: str
    company: str | None
    identities: list[IdentityOut]
    requests: list[RequestSummaryOut]
    open_requests: int
    forgotten_requests: int
    needs_response: bool
    highest_priority: str
    last_activity_at: datetime | None


class CustomerDetailOut(BaseModel):
    id: int
    display_name: str
    company: str | None
    notes: str | None
    identities: list[IdentityOut]
    requests: list[RequestSummaryOut]


class MergeSuggestionOut(BaseModel):
    id: int
    customer_a: dict
    customer_b: dict
    reason: str
    confidence: float
    status: str


class SyncResultOut(BaseModel):
    fetched: int
    ingested: int
    skipped: int


class StatsOut(BaseModel):
    customers: int
    open_requests: int
    needs_response: int
    forgotten: int
    pending_suggestions: int


class DraftOut(BaseModel):
    draft: str


class ConnectorStatusOut(BaseModel):
    active: str
    gmail_configured: bool
    gmail_connected: bool
    gmail_address: str | None
    last_sync_at: datetime | None


class AuthUrlOut(BaseModel):
    authorization_url: str


class ReplyIn(BaseModel):
    body: str


class NotesIn(BaseModel):
    notes: str
