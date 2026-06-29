"""Golden-scenario tests for the core thesis: cross-channel grouping, no false
merges, and direction-aware accountability status."""
from __future__ import annotations

from sqlalchemy import select

from app.llm.factory import get_llm
from app.models import Customer, Identity, Request, RequestStatus
from app.services.identity import normalize_email
from app.services.sync import run_sync


def _customer_by_identity(session, owner_id, normalized_value):
    ident = session.scalar(
        select(Identity).where(
            Identity.owner_id == owner_id, Identity.normalized_value == normalized_value
        )
    )
    return session.get(Customer, ident.customer_id) if ident else None


def test_form_and_email_stitch_to_same_customer(session, owner):
    run_sync(session, owner.id, llm=get_llm())

    by_email = _customer_by_identity(session, owner.id, normalize_email("sarah.chen@acme.com"))
    by_phone = _customer_by_identity(session, owner.id, "4155550117")
    assert by_email is not None, "email identity should exist"
    assert by_phone is not None, "form phone identity should exist"
    # The web-form submission (phone) is stitched to the same customer as the
    # email thread -- different channel, same person.
    assert by_email.id == by_phone.id
    assert "sarah" in by_email.display_name.lower()


def test_similar_names_are_not_merged(session, owner):
    run_sync(session, owner.id, llm=get_llm())
    john = _customer_by_identity(session, owner.id, normalize_email("john.smith@globex.com"))
    jon = _customer_by_identity(session, owner.id, normalize_email("jon@hobbymail.net"))
    assert john is not None and jon is not None
    # False merge would be a privacy incident -> must stay distinct.
    assert john.id != jon.id


def test_status_is_direction_aware(session, owner):
    run_sync(session, owner.id, llm=get_llm())

    marcus = _customer_by_identity(session, owner.id, normalize_email("marcus@bluewave.io"))
    assert any(r.status == RequestStatus.needs_reply for r in marcus.requests)

    priya = _customer_by_identity(session, owner.id, normalize_email("priya@northstar.dev"))
    # We already replied -> waiting on the customer.
    assert all(r.status == RequestStatus.waiting for r in priya.requests)


def test_sync_is_idempotent(session, owner):
    first = run_sync(session, owner.id, llm=get_llm())
    assert first.ingested > 0
    before = len(session.scalars(select(Customer).where(Customer.owner_id == owner.id)).all())

    second = run_sync(session, owner.id, llm=get_llm())
    assert second.ingested == 0
    assert second.skipped == first.fetched
    after = len(session.scalars(select(Customer).where(Customer.owner_id == owner.id)).all())
    assert before == after


def test_forgotten_detection(session, owner):
    run_sync(session, owner.id, llm=get_llm())
    # Sarah's original thread last heard from her ~40h ago with no reply -> forgotten.
    from app.config import get_settings
    from app.services.triage import is_forgotten

    hours = get_settings().forgotten_after_hours
    reqs = session.scalars(select(Request).where(Request.owner_id == owner.id)).all()
    assert any(is_forgotten(r, hours) for r in reqs)
