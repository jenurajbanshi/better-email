"""Triage: summarize a request, set priority/sentiment, and -- crucially --
derive its accountability status so customers are never forgotten.

Status is direction-aware:
  * last message inbound  -> needs_reply (the ball is in OUR court)
  * last message outbound -> waiting     (awaiting the customer)
A manually-resolved request stays resolved until a new inbound message arrives.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..llm.base import MessageContext
from ..models import Direction, Priority, Request, RequestStatus


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def recompute_request(session: Session, request: Request, llm, *, run_llm: bool = True) -> None:
    messages = sorted(request.messages, key=lambda m: m.received_at)
    if not messages:
        return

    inbound = [m for m in messages if m.direction == Direction.inbound]
    outbound = [m for m in messages if m.direction == Direction.outbound]
    # Stored as naive UTC for consistency with reloaded SQLite values.
    request.last_inbound_at = inbound[-1].received_at if inbound else None
    request.last_outbound_at = outbound[-1].received_at if outbound else None
    request.first_seen_at = messages[0].received_at

    last = messages[-1]
    if request.status != RequestStatus.resolved:
        request.status = (
            RequestStatus.needs_reply if last.direction == Direction.inbound else RequestStatus.waiting
        )
    request.needs_response = request.status == RequestStatus.needs_reply

    if run_llm:
        ctx = [
            MessageContext(m.from_name, m.subject, m.snippet or "", m.direction.value)
            for m in messages
        ]
        triage = llm.triage(ctx)
        request.summary = triage.summary
        request.ask = triage.ask
        request.sentiment = triage.sentiment
        try:
            request.priority = Priority(triage.priority)
        except ValueError:
            request.priority = Priority.normal
        if not request.title or request.title == "Customer request":
            request.title = triage.title or request.title


def is_forgotten(request: Request, forgotten_after_hours: int) -> bool:
    """A request awaiting our reply, with no response for too long."""
    if not request.needs_response or request.status != RequestStatus.needs_reply:
        return False
    last_in = _as_aware(request.last_inbound_at)
    if last_in is None:
        return False
    return last_in < datetime.now(timezone.utc) - timedelta(hours=forgotten_after_hours)
