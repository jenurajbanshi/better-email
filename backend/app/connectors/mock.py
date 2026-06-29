"""Mock connector with a rich, realistic seed dataset.

The scenarios are deliberately tricky so the product's value is visible on the
very first run, offline, with no Gmail and no API key:

  * Sarah Chen  -- the SAME person arriving via a thread reply, a brand-new
                   email from a DIFFERENT address, and a web form.
  * Marcus Lee  -- a single urgent request awaiting our reply (forgotten risk).
  * Priya Patel -- a request we already answered (waiting on customer).
  * John vs Jon Smith -- two DIFFERENT people with similar names that must NOT
                   be merged (false-merge = data leak).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import Connector, NormalizedMessage

OWNER_ADDR = "support@ourcompany.com"


def _ago(hours: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _seed() -> list[NormalizedMessage]:
    msgs: list[NormalizedMessage] = []

    # --- Scenario A: Sarah Chen across three channels / two addresses --------
    msgs.append(NormalizedMessage(
        platform="gmail", platform_message_id="A1", thread_id="T-A",
        direction="inbound", received_at=_ago(72),
        from_name="Sarah Chen", from_email="sarah.chen@acme.com",
        to_addrs=[OWNER_ADDR], subject="Login broken after the latest update",
        body="Hi team, since the update this morning I can't log into my Acme dashboard. "
             "It just spins and times out. Can you help?",
    ))
    msgs.append(NormalizedMessage(
        platform="gmail", platform_message_id="A2", thread_id="T-A",
        direction="outbound", received_at=_ago(71),
        from_name="Support Team", from_email=OWNER_ADDR,
        to_addrs=["sarah.chen@acme.com"], subject="Re: Login broken after the latest update",
        body="Hi Sarah, sorry about that! Could you try clearing your cache and let us know?",
    ))
    msgs.append(NormalizedMessage(
        platform="gmail", platform_message_id="A3", thread_id="T-A",
        direction="inbound", received_at=_ago(40),
        from_name="Sarah Chen", from_email="sarah.chen@acme.com",
        to_addrs=[OWNER_ADDR], subject="Re: Login broken after the latest update",
        body="I cleared the cache and tried a different browser, still not working. "
             "This is blocking my whole team.",
    ))
    # Different address, no thread -- same human.
    msgs.append(NormalizedMessage(
        platform="gmail", platform_message_id="A4", thread_id="T-A4",
        direction="inbound", received_at=_ago(20),
        from_name="Sarah Chen", from_email="s.chen.personal@gmail.com",
        to_addrs=[OWNER_ADDR], subject="Urgent: still cannot log in to Acme",
        body="Emailing from my personal account since I'm locked out. The login to the "
             "Acme dashboard is still completely broken and it's urgent.",
    ))
    # Web form submission -- structured fields tie it back deterministically.
    msgs.append(NormalizedMessage(
        platform="webform", platform_message_id="F1", thread_id=None,
        direction="inbound", received_at=_ago(6),
        from_name="Website Form", from_email="forms@ourcompany.com",
        to_addrs=[OWNER_ADDR], subject="Contact form: Account access",
        body="Login still down. Please call me. Very frustrated.",
        extra={"form_fields": {"name": "Sarah Chen", "email": "sarah.chen@acme.com",
                                "phone": "+1 415-555-0117", "topic": "Account access"}},
    ))

    # --- Scenario B: Marcus Lee, urgent, awaiting our reply ------------------
    msgs.append(NormalizedMessage(
        platform="gmail", platform_message_id="B1", thread_id="T-B",
        direction="inbound", received_at=_ago(5),
        from_name="Marcus Lee", from_email="marcus@bluewave.io",
        to_addrs=[OWNER_ADDR], subject="Double charged - need a refund ASAP",
        body="I was charged twice for my subscription this month. Please refund the "
             "duplicate charge as soon as possible. This is really frustrating.",
    ))

    # --- Scenario C: Priya Patel, already answered (waiting on customer) ------
    msgs.append(NormalizedMessage(
        platform="gmail", platform_message_id="C1", thread_id="T-C",
        direction="inbound", received_at=_ago(30),
        from_name="Priya Patel", from_email="priya@northstar.dev",
        to_addrs=[OWNER_ADDR], subject="How do I export my data?",
        body="Hello, could you tell me how to export all my project data to CSV?",
    ))
    msgs.append(NormalizedMessage(
        platform="gmail", platform_message_id="C2", thread_id="T-C",
        direction="outbound", received_at=_ago(28),
        from_name="Support Team", from_email=OWNER_ADDR,
        to_addrs=["priya@northstar.dev"], subject="Re: How do I export my data?",
        body="Hi Priya! Go to Settings > Data > Export and choose CSV. Let us know if that helps!",
    ))

    # --- Scenario D: two DIFFERENT people, similar names, MUST NOT merge ------
    msgs.append(NormalizedMessage(
        platform="gmail", platform_message_id="D1", thread_id="T-D",
        direction="inbound", received_at=_ago(10),
        from_name="John Smith", from_email="john.smith@globex.com",
        to_addrs=[OWNER_ADDR], subject="Invoice question for Globex account",
        body="Can you resend the March invoice for the Globex enterprise account? Thanks.",
    ))
    msgs.append(NormalizedMessage(
        platform="gmail", platform_message_id="E1", thread_id="T-E",
        direction="inbound", received_at=_ago(8),
        from_name="Jon Smith", from_email="jon@hobbymail.net",
        to_addrs=[OWNER_ADDR], subject="Feature request: dark mode",
        body="Love the app! Any chance of a dark mode for the mobile client?",
    ))

    return msgs


class MockConnector(Connector):
    platform = "mock"

    def __init__(self, messages: list[NormalizedMessage] | None = None):
        self._messages = messages if messages is not None else _seed()
        self._sent: list[dict] = []

    def fetch_messages(self, since: datetime | None = None) -> list[NormalizedMessage]:
        if since is None:
            return list(self._messages)
        return [m for m in self._messages if m.received_at >= since]

    def send_reply(self, *, to, subject, body, thread_id=None) -> str:
        msg_id = f"MOCK-SENT-{len(self._sent) + 1}"
        self._sent.append({"id": msg_id, "to": to, "subject": subject, "body": body, "thread_id": thread_id})
        return msg_id
