"""Identity resolution: stitch a message to the right customer across channels.

Deterministic-first (cheap, exact, auditable), LLM only for the ambiguous
remainder. Biased toward *under*-merging: a wrong merge exposes one customer's
data to another, so anything short of strong evidence becomes a human-reviewed
merge suggestion rather than a silent merge.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..connectors.base import NormalizedMessage
from ..llm.base import CustomerContext, MessageContext
from ..models import Customer, Identity, IdentityKind, MergeSuggestion

# Confidence thresholds for LLM-proposed matches.
AUTO_MERGE_THRESHOLD = 0.82  # assign to existing customer automatically
SUGGEST_THRESHOLD = 0.50  # create new customer + flag a possible merge

_FREE_EMAIL_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"}


@dataclass
class IdentitySignal:
    kind: IdentityKind
    value: str
    normalized: str


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return email
    local, _, domain = email.partition("@")
    local = local.split("+", 1)[0]  # drop +tag for everyone
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.replace(".", "")  # gmail ignores dots
    return f"{local}@{domain}"


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else digits


def extract_signals(msg: NormalizedMessage) -> list[IdentitySignal]:
    """Pull identity signals identifying the *customer* on the message.

    For inbound mail that's the sender (unless it's a generic relay/form
    address, in which case the form's structured fields carry the real
    identity). For outbound mail *we* are the sender, so the customer is the
    recipient -- use ``to_addrs``."""
    signals: list[IdentitySignal] = []
    seen: set[tuple] = set()

    def add(kind: IdentityKind, value: str | None):
        if not value:
            return
        norm = normalize_email(value) if kind == IdentityKind.email else (
            normalize_phone(value) if kind == IdentityKind.phone else value.strip().lower()
        )
        if not norm:
            return
        key = (kind, norm)
        if key in seen:
            return
        seen.add(key)
        signals.append(IdentitySignal(kind, value.strip(), norm))

    if msg.direction == "outbound":
        for addr in msg.to_addrs or []:
            add(IdentityKind.email, addr)
        return signals

    # Inbound: the sender, unless it's a generic relay/form address.
    if msg.from_email and msg.platform != "webform":
        add(IdentityKind.email, msg.from_email)

    form = (msg.extra or {}).get("form_fields", {})
    if isinstance(form, dict):
        add(IdentityKind.email, form.get("email"))
        add(IdentityKind.phone, form.get("phone"))

    return signals


def _display_name(msg: NormalizedMessage, signals: list[IdentitySignal]) -> str:
    form = (msg.extra or {}).get("form_fields", {})
    if isinstance(form, dict) and form.get("name"):
        return str(form["name"]).strip()
    if msg.from_name and msg.platform != "webform":
        return msg.from_name.strip()
    for s in signals:
        if s.kind == IdentityKind.email:
            return s.value.split("@")[0]
    return "Unknown customer"


def _attach_signals(session: Session, owner_id: int, customer: Customer, signals: list[IdentitySignal], source: str) -> None:
    existing = {
        (i.kind, i.normalized_value)
        for i in session.scalars(select(Identity).where(Identity.customer_id == customer.id))
    }
    for s in signals:
        if (s.kind, s.normalized) in existing:
            continue
        # Don't steal an identity already owned by a different customer.
        clash = session.scalar(
            select(Identity).where(
                Identity.owner_id == owner_id,
                Identity.kind == s.kind,
                Identity.normalized_value == s.normalized,
            )
        )
        if clash is not None:
            continue
        session.add(Identity(
            owner_id=owner_id, customer_id=customer.id, kind=s.kind,
            value=s.value, normalized_value=s.normalized, source=source, confidence=1.0,
        ))
        existing.add((s.kind, s.normalized))


def _customer_context(session: Session, owner_id: int) -> list[tuple[Customer, CustomerContext]]:
    customers = list(session.scalars(select(Customer).where(Customer.owner_id == owner_id)))
    out = []
    for c in customers:
        snippets = [m.snippet or "" for m in sorted(c.messages, key=lambda m: m.received_at, reverse=True)[:3]]
        out.append((c, CustomerContext(c.id, c.display_name, c.company, [s for s in snippets if s])))
    return out


@dataclass
class ResolutionResult:
    customer: Customer
    created: bool
    method: str
    confidence: float


def resolve_customer(session: Session, owner_id: int, msg: NormalizedMessage, llm) -> ResolutionResult:
    signals = extract_signals(msg)

    # 1) Deterministic: any signal already maps to a known customer.
    for s in signals:
        ident = session.scalar(
            select(Identity).where(
                Identity.owner_id == owner_id,
                Identity.kind == s.kind,
                Identity.normalized_value == s.normalized,
            )
        )
        if ident is not None:
            customer = session.get(Customer, ident.customer_id)
            _attach_signals(session, owner_id, customer, signals, source=f"{msg.platform}:deterministic")
            return ResolutionResult(customer, created=False, method="deterministic", confidence=1.0)

    # 2) Ambiguous: ask the LLM to compare against known customers.
    candidates = _customer_context(session, owner_id)
    decision = None
    if candidates:
        mctx = MessageContext(msg.from_name, msg.subject, msg.snippet, msg.direction)
        decision = llm.classify_identity(mctx, [cc for _, cc in candidates])

    if decision and decision.matched_customer_id is not None:
        matched = next((c for c, _ in candidates if c.id == decision.matched_customer_id), None)
        if matched is not None and decision.confidence >= AUTO_MERGE_THRESHOLD:
            _attach_signals(session, owner_id, matched, signals, source=f"{msg.platform}:llm")
            return ResolutionResult(matched, created=False, method="llm-auto", confidence=decision.confidence)

    # 3) Create a new customer (under-merge bias). If the LLM saw a plausible
    #    but not strong match, record a suggestion for human review.
    new_customer = Customer(owner_id=owner_id, display_name=_display_name(msg, signals), confidence=1.0)
    session.add(new_customer)
    session.flush()
    _attach_signals(session, owner_id, new_customer, signals, source=f"{msg.platform}:new")

    if decision and decision.matched_customer_id is not None and SUGGEST_THRESHOLD <= decision.confidence < AUTO_MERGE_THRESHOLD:
        matched = next((c for c, _ in candidates if c.id == decision.matched_customer_id), None)
        if matched is not None:
            session.add(MergeSuggestion(
                owner_id=owner_id, customer_id_a=new_customer.id, customer_id_b=matched.id,
                reason=decision.reason, confidence=decision.confidence,
            ))

    return ResolutionResult(new_customer, created=True, method="new", confidence=1.0)
