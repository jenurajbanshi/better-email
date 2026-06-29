"""Request grouping: attach a message to a new or existing request for the
customer. Same thread => same request (deterministic). Otherwise the LLM
decides whether it's a follow-up to an open request or a fresh ask.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..connectors.base import NormalizedMessage
from ..llm.base import MessageContext, RequestContext
from ..models import Customer, Message, Request, RequestStatus

GROUP_THRESHOLD = 0.55


def _clean_title(text: str | None) -> str:
    text = (text or "Customer request").strip()
    text = re.sub(r"^\s*(re|fwd|fw)\s*:\s*", "", text, flags=re.IGNORECASE)
    return (text or "Customer request")[:120]


def assign_request(session: Session, owner_id: int, customer: Customer, msg: NormalizedMessage, llm) -> Request:
    # 1) Deterministic: an existing request already contains this thread.
    if msg.thread_id:
        existing = session.scalar(
            select(Request)
            .join(Message, Message.request_id == Request.id)
            .where(Request.customer_id == customer.id, Message.thread_id == msg.thread_id)
            .limit(1)
        )
        if existing is not None:
            return existing

    # 2) LLM: does this belong to an open request?
    open_reqs = list(session.scalars(
        select(Request).where(Request.customer_id == customer.id, Request.status != RequestStatus.resolved)
    ))
    if open_reqs:
        mctx = MessageContext(msg.from_name, msg.subject, msg.snippet, msg.direction)
        rctx = [RequestContext(r.id, r.title, r.summary, r.status.value) for r in open_reqs]
        decision = llm.group_request(mctx, rctx)
        if decision.matched_request_id is not None and decision.confidence >= GROUP_THRESHOLD:
            match = next((r for r in open_reqs if r.id == decision.matched_request_id), None)
            if match is not None:
                return match

    # 3) New request.
    req = Request(
        owner_id=owner_id,
        customer_id=customer.id,
        title=_clean_title(msg.subject or msg.snippet),
        channel=msg.platform,
        status=RequestStatus.needs_reply,
        first_seen_at=msg.received_at,
    )
    session.add(req)
    session.flush()
    return req
