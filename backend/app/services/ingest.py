"""The ingest pipeline: normalized message -> customer -> request -> triage.

Idempotent: re-ingesting the same (platform, platform_message_id) is a no-op,
so overlapping connector sync windows never duplicate data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..connectors.base import NormalizedMessage
from ..models import Direction, Message, Request
from .grouping import assign_request
from .identity import resolve_customer
from .triage import recompute_request


@dataclass
class IngestOutcome:
    skipped: bool
    message_id: int | None
    customer_id: int | None
    request_id: int | None
    method: str


def _request_for_thread(session: Session, owner_id: int, thread_id: str | None) -> Request | None:
    if not thread_id:
        return None
    return session.scalar(
        select(Request)
        .join(Message, Message.request_id == Request.id)
        .where(Request.owner_id == owner_id, Message.thread_id == thread_id)
        .limit(1)
    )


def ingest_message(
    session: Session, owner_id: int, msg: NormalizedMessage, llm, *, run_llm_triage: bool = True
) -> IngestOutcome:
    existing = session.scalar(
        select(Message).where(
            Message.owner_id == owner_id,
            Message.platform == msg.platform,
            Message.platform_message_id == msg.platform_message_id,
        )
    )
    if existing is not None:
        return IngestOutcome(True, existing.id, existing.customer_id, existing.request_id, "duplicate")

    # Store all timestamps as naive UTC so values are comparable whether they
    # were just created (aware) or reloaded from SQLite (naive).
    if msg.received_at.tzinfo is not None:
        msg.received_at = msg.received_at.astimezone(timezone.utc).replace(tzinfo=None)

    # Fast path: an existing thread already maps to a request (and a customer).
    request = _request_for_thread(session, owner_id, msg.thread_id)
    method = "thread"
    if request is not None:
        customer = request.customer
    else:
        res = resolve_customer(session, owner_id, msg, llm)
        customer = res.customer
        method = res.method
        request = assign_request(session, owner_id, customer, msg, llm)

    row = Message(
        owner_id=owner_id,
        platform=msg.platform,
        platform_message_id=msg.platform_message_id,
        thread_id=msg.thread_id,
        direction=Direction(msg.direction),
        from_name=msg.from_name,
        from_email=msg.from_email,
        to_addrs=msg.to_addrs,
        subject=msg.subject,
        body=msg.body,
        snippet=msg.snippet,
        received_at=msg.received_at,
        extra=msg.extra or {},
    )
    row.customer = customer
    row.request = request
    session.add(row)
    session.flush()

    recompute_request(session, request, llm, run_llm=run_llm_triage)
    session.commit()
    return IngestOutcome(False, row.id, customer.id, request.id, method)
