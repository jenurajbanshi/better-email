"""API routes. Every query is scoped to the authenticated owner."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..connectors import gmail_oauth
from ..db import get_session
from ..llm.factory import get_llm
from ..models import (
    AuditLog,
    Customer,
    Direction,
    Identity,
    MergeSuggestion,
    Message,
    Owner,
    Request,
    RequestStatus,
    SuggestionStatus,
)
from ..services import credentials
from ..services.sync import build_connector, run_sync
from ..services.triage import is_forgotten, recompute_request
from ..security import sign_oauth_state, verify_oauth_state
from ..schemas import (
    AuthUrlOut,
    ConnectorStatusOut,
    CustomerDetailOut,
    CustomerInboxOut,
    DraftOut,
    IdentityOut,
    MessageOut,
    MergeSuggestionOut,
    NotesIn,
    ReplyIn,
    RequestDetailOut,
    RequestSummaryOut,
    StatsOut,
    SyncResultOut,
)
from .deps import get_current_owner

router = APIRouter(prefix="/api")

_PRIORITY_RANK = {"urgent": 3, "high": 2, "normal": 1, "low": 0}


def _identity_out(i: Identity) -> IdentityOut:
    return IdentityOut(kind=i.kind.value, value=i.value, source=i.source)


def _request_summary(r: Request) -> RequestSummaryOut:
    hours = get_settings().forgotten_after_hours
    return RequestSummaryOut(
        id=r.id,
        title=r.title,
        summary=r.summary,
        ask=r.ask,
        status=r.status.value,
        priority=r.priority.value,
        sentiment=r.sentiment,
        channel=r.channel,
        needs_response=r.needs_response,
        forgotten=is_forgotten(r, hours),
        message_count=len(r.messages),
        last_inbound_at=r.last_inbound_at,
        last_outbound_at=r.last_outbound_at,
    )


def _message_out(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id,
        direction=m.direction.value,
        platform=m.platform,
        from_name=m.from_name,
        from_email=m.from_email,
        subject=m.subject,
        body=m.body,
        snippet=m.snippet,
        received_at=m.received_at,
    )


def _customer_inbox(c: Customer) -> CustomerInboxOut:
    reqs = sorted(c.requests, key=lambda r: r.first_seen_at or datetime.min, reverse=True)
    summaries = [_request_summary(r) for r in reqs]
    open_reqs = [s for s in summaries if s.status != "resolved"]
    forgotten = [s for s in summaries if s.forgotten]
    activity = [t for r in reqs for t in (r.last_inbound_at, r.last_outbound_at) if t]
    highest = "low"
    for s in open_reqs:
        if _PRIORITY_RANK[s.priority] > _PRIORITY_RANK[highest]:
            highest = s.priority
    return CustomerInboxOut(
        id=c.id,
        display_name=c.display_name,
        company=c.company,
        identities=[_identity_out(i) for i in c.identities],
        requests=summaries,
        open_requests=len(open_reqs),
        forgotten_requests=len(forgotten),
        needs_response=any(s.needs_response for s in open_reqs),
        highest_priority=highest if open_reqs else "low",
        last_activity_at=max(activity) if activity else None,
    )


def _get_owned_request(session: Session, owner: Owner, request_id: int) -> Request:
    req = session.get(Request, request_id)
    if req is None or req.owner_id != owner.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return req


def _get_owned_customer(session: Session, owner: Owner, customer_id: int) -> Customer:
    cust = session.get(Customer, customer_id)
    if cust is None or cust.owner_id != owner.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return cust


@router.post("/sync", response_model=SyncResultOut)
def sync(session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    result = run_sync(session, owner.id)
    return SyncResultOut(fetched=result.fetched, ingested=result.ingested, skipped=result.skipped)


@router.get("/connectors", response_model=ConnectorStatusOut)
def connector_status(session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    settings = get_settings()
    account = credentials.get_account(session, owner.id)
    return ConnectorStatusOut(
        active=settings.connector,
        gmail_configured=bool(settings.gmail_client_id and settings.gmail_client_secret),
        gmail_connected=account is not None,
        gmail_address=account.account_email if account else None,
        last_sync_at=account.last_sync_at if account else None,
    )


@router.get("/connectors/gmail/authorize", response_model=AuthUrlOut)
def gmail_authorize(owner: Owner = Depends(get_current_owner)):
    settings = get_settings()
    if not (settings.gmail_client_id and settings.gmail_client_secret):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Gmail OAuth is not configured. Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET.",
        )
    state = sign_oauth_state(owner.id)
    return AuthUrlOut(authorization_url=gmail_oauth.authorization_url(settings, state))


def _callback_page(title: str, message: str, ok: bool) -> HTMLResponse:
    color = "#059669" if ok else "#e11d48"
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: system-ui, sans-serif; background:#f8fafc; color:#1e293b;
         display:flex; min-height:100vh; align-items:center; justify-content:center; margin:0; }}
  .card {{ background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:32px 40px;
           text-align:center; max-width:420px; }}
  h1 {{ color:{color}; font-size:20px; margin:0 0 8px; }}
  p {{ color:#475569; font-size:14px; line-height:1.5; }}
  a {{ color:#4f46e5; }}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{message}</p>
<p><a href="/">Return to better-email</a></p></div></body></html>"""
    return HTMLResponse(content=html, status_code=200 if ok else 400)


@router.get("/connectors/gmail/callback")
def gmail_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: Session = Depends(get_session),
):
    if error:
        return _callback_page("Gmail connection cancelled", f"Google returned: {error}", ok=False)
    if not code or not state:
        return _callback_page("Gmail connection failed", "Missing authorization code or state.", ok=False)
    try:
        owner_id = verify_oauth_state(state)
    except ValueError:
        return _callback_page("Gmail connection failed", "Invalid or expired authorization state.", ok=False)
    owner = session.get(Owner, owner_id)
    if owner is None:
        return _callback_page("Gmail connection failed", "Unknown account.", ok=False)

    settings = get_settings()
    try:
        token = gmail_oauth.exchange_code(settings, code)
        profile = gmail_oauth.fetch_profile(token)
    except httpx.HTTPError as e:
        return _callback_page("Gmail connection failed", f"Token exchange failed: {e}", ok=False)

    credentials.save_account(
        session,
        owner_id,
        token=token,
        account_email=profile.get("emailAddress"),
        history_id=str(profile["historyId"]) if profile.get("historyId") else None,
    )
    session.add(
        AuditLog(owner_id=owner_id, action="gmail_connected", detail={"address": profile.get("emailAddress")})
    )
    session.commit()
    return _callback_page(
        "Gmail connected",
        f"{profile.get('emailAddress', 'Your mailbox')} is now connected. You can start syncing.",
        ok=True,
    )


@router.post("/connectors/gmail/disconnect", response_model=ConnectorStatusOut)
def gmail_disconnect(session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    removed = credentials.delete_account(session, owner.id)
    if removed:
        session.add(AuditLog(owner_id=owner.id, action="gmail_disconnected", detail={}))
        session.commit()
    return connector_status(session, owner)


@router.get("/inbox", response_model=list[CustomerInboxOut])
def inbox(session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    customers = session.scalars(select(Customer).where(Customer.owner_id == owner.id)).all()
    items = [_customer_inbox(c) for c in customers]

    def sort_key(c: CustomerInboxOut):
        # Accountability-first: forgotten, then needs-response, then priority,
        # then most recent activity. This is the "never leave customers
        # forgotten" ordering.
        return (
            c.forgotten_requests > 0,
            c.needs_response,
            _PRIORITY_RANK[c.highest_priority],
            c.last_activity_at or datetime.min,
        )

    items.sort(key=sort_key, reverse=True)
    return items


@router.get("/customers/{customer_id}", response_model=CustomerDetailOut)
def customer_detail(customer_id: int, session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    c = _get_owned_customer(session, owner, customer_id)
    reqs = sorted(c.requests, key=lambda r: r.first_seen_at or datetime.min, reverse=True)
    return CustomerDetailOut(
        id=c.id,
        display_name=c.display_name,
        company=c.company,
        notes=c.notes,
        identities=[_identity_out(i) for i in c.identities],
        requests=[_request_summary(r) for r in reqs],
    )


@router.put("/customers/{customer_id}/notes", response_model=CustomerDetailOut)
def update_notes(customer_id: int, payload: NotesIn, session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    c = _get_owned_customer(session, owner, customer_id)
    c.notes = payload.notes
    session.commit()
    return customer_detail(customer_id, session, owner)


@router.get("/requests/{request_id}", response_model=RequestDetailOut)
def request_detail(request_id: int, session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    r = _get_owned_request(session, owner, request_id)
    base = _request_summary(r)
    return RequestDetailOut(
        **base.model_dump(),
        customer_id=r.customer_id,
        customer_name=r.customer.display_name,
        messages=[_message_out(m) for m in sorted(r.messages, key=lambda m: m.received_at)],
    )


@router.post("/requests/{request_id}/draft", response_model=DraftOut)
def draft_reply(request_id: int, session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    from ..llm.base import MessageContext

    r = _get_owned_request(session, owner, request_id)
    llm = get_llm()
    msgs = sorted(r.messages, key=lambda m: m.received_at)
    ctx = [MessageContext(m.from_name, m.subject, m.snippet or "", m.direction.value) for m in msgs]
    draft = llm.draft_reply(ctx, r.summary or r.title)
    return DraftOut(draft=draft)


@router.post("/requests/{request_id}/reply", response_model=RequestDetailOut)
def send_reply(request_id: int, payload: ReplyIn, session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    r = _get_owned_request(session, owner, request_id)
    msgs = sorted(r.messages, key=lambda m: m.received_at)
    last_inbound = next((m for m in reversed(msgs) if m.direction == Direction.inbound), None)
    to_addr = last_inbound.from_email if last_inbound and last_inbound.from_email else None
    if not to_addr:
        # Fall back to a customer email identity.
        ident = next((i for i in r.customer.identities if i.kind.value == "email"), None)
        to_addr = ident.value if ident else None
    if not to_addr:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No customer email to reply to")

    subject = r.title if r.title.lower().startswith("re:") else f"Re: {r.title}"
    thread_id = next((m.thread_id for m in reversed(msgs) if m.thread_id), None)

    connector = build_connector(session=session, owner_id=owner.id)
    sent_id = connector.send_reply(to=[to_addr], subject=subject, body=payload.body, thread_id=thread_id)

    # Persist any token the connector refreshed while sending.
    if hasattr(connector, "export_token"):
        account = credentials.get_account(session, owner.id)
        refreshed = connector.export_token()
        if account is not None and refreshed is not None:
            credentials.update_token(session, account, refreshed)

    # Attach the outbound message directly to THIS request (no re-grouping).
    reply_msg = Message(
        owner_id=owner.id,
        platform=connector.platform,
        platform_message_id=sent_id,
        thread_id=thread_id,
        direction=Direction.outbound,
        from_name="Support Team",
        from_email=owner.email,
        to_addrs=[to_addr],
        subject=subject,
        body=payload.body,
        snippet=payload.body[:300],
        received_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    reply_msg.request = r
    reply_msg.customer = r.customer
    session.add(reply_msg)
    session.flush()
    recompute_request(session, r, get_llm(), run_llm=False)
    session.add(AuditLog(owner_id=owner.id, action="reply_sent", detail={"request_id": r.id, "to": to_addr}))
    session.commit()
    session.refresh(r)
    return request_detail(request_id, session, owner)


@router.post("/requests/{request_id}/resolve", response_model=RequestSummaryOut)
def resolve_request(request_id: int, session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    r = _get_owned_request(session, owner, request_id)
    r.status = RequestStatus.resolved
    r.needs_response = False
    session.add(AuditLog(owner_id=owner.id, action="request_resolved", detail={"request_id": r.id}))
    session.commit()
    session.refresh(r)
    return _request_summary(r)


@router.post("/requests/{request_id}/reopen", response_model=RequestSummaryOut)
def reopen_request(request_id: int, session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    r = _get_owned_request(session, owner, request_id)
    r.status = RequestStatus.needs_reply
    recompute_request(session, r, get_llm(), run_llm=False)
    session.commit()
    session.refresh(r)
    return _request_summary(r)


def _suggestion_out(session: Session, s: MergeSuggestion) -> MergeSuggestionOut:
    a = session.get(Customer, s.customer_id_a)
    b = session.get(Customer, s.customer_id_b)
    return MergeSuggestionOut(
        id=s.id,
        customer_a={"id": a.id, "name": a.display_name} if a else {},
        customer_b={"id": b.id, "name": b.display_name} if b else {},
        reason=s.reason,
        confidence=s.confidence,
        status=s.status.value,
    )


@router.get("/suggestions", response_model=list[MergeSuggestionOut])
def list_suggestions(session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    rows = session.scalars(
        select(MergeSuggestion).where(
            MergeSuggestion.owner_id == owner.id,
            MergeSuggestion.status == SuggestionStatus.pending,
        )
    ).all()
    return [_suggestion_out(session, s) for s in rows]


@router.post("/suggestions/{suggestion_id}/accept", response_model=CustomerDetailOut)
def accept_suggestion(suggestion_id: int, session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    s = session.get(MergeSuggestion, suggestion_id)
    if s is None or s.owner_id != owner.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suggestion not found")
    # Merge A into B (keep the older / target customer B).
    a = _get_owned_customer(session, owner, s.customer_id_a)
    b = _get_owned_customer(session, owner, s.customer_id_b)
    target, source = (b, a) if a.id > b.id else (a, b)

    for ident in list(source.identities):
        clash = session.scalar(
            select(Identity).where(
                Identity.owner_id == owner.id, Identity.kind == ident.kind,
                Identity.normalized_value == ident.normalized_value, Identity.customer_id == target.id,
            )
        )
        if clash is None:
            ident.customer_id = target.id
        else:
            session.delete(ident)
    for req in list(source.requests):
        req.customer_id = target.id
    for msg in list(source.messages):
        msg.customer_id = target.id

    session.flush()
    session.delete(source)
    s.status = SuggestionStatus.accepted
    session.add(AuditLog(owner_id=owner.id, action="customers_merged",
                         detail={"kept": target.id, "merged": source.id, "suggestion": s.id}))
    session.commit()
    return customer_detail(target.id, session, owner)


@router.post("/suggestions/{suggestion_id}/reject", response_model=MergeSuggestionOut)
def reject_suggestion(suggestion_id: int, session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    s = session.get(MergeSuggestion, suggestion_id)
    if s is None or s.owner_id != owner.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suggestion not found")
    s.status = SuggestionStatus.rejected
    session.commit()
    return _suggestion_out(session, s)


@router.get("/stats", response_model=StatsOut)
def stats(session: Session = Depends(get_session), owner: Owner = Depends(get_current_owner)):
    hours = get_settings().forgotten_after_hours
    customers = session.scalars(select(Customer).where(Customer.owner_id == owner.id)).all()
    requests = session.scalars(select(Request).where(Request.owner_id == owner.id)).all()
    pending = session.scalars(
        select(MergeSuggestion).where(
            MergeSuggestion.owner_id == owner.id, MergeSuggestion.status == SuggestionStatus.pending
        )
    ).all()
    return StatsOut(
        customers=len(customers),
        open_requests=len([r for r in requests if r.status != RequestStatus.resolved]),
        needs_response=len([r for r in requests if r.needs_response]),
        forgotten=len([r for r in requests if is_forgotten(r, hours)]),
        pending_suggestions=len(pending),
    )
