"""Sync orchestration: pull from a connector and run each message through the
ingest pipeline. Structured as a plain callable so it can run in-process now
and be promoted to a dedicated worker / Railway cron job later unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..connectors.base import Connector
from ..connectors.gmail import GmailConnector
from ..connectors.mock import MockConnector
from ..llm.factory import get_llm
from . import credentials
from .ingest import ingest_message


def build_connector(
    settings: Settings | None = None,
    *,
    session: Session | None = None,
    owner_id: int | None = None,
) -> Connector:
    """Construct the configured connector.

    The Gmail connector needs per-owner OAuth credentials, so a ``session`` and
    ``owner_id`` must be supplied when ``CONNECTOR=gmail``.
    """
    settings = settings or get_settings()
    name = settings.connector.lower()
    if name == "mock":
        return MockConnector()
    if name == "gmail":
        return _build_gmail_connector(settings, session, owner_id)
    raise ValueError(f"Unknown CONNECTOR: {settings.connector}")


def _build_gmail_connector(
    settings: Settings, session: Session | None, owner_id: int | None
) -> GmailConnector:
    if session is None or owner_id is None:
        raise RuntimeError("Gmail connector requires a database session and owner id.")
    account = credentials.get_account(session, owner_id)
    if account is None:
        raise RuntimeError(
            "Gmail is not connected. Authorize it via GET /api/connectors/gmail/authorize, "
            "then retry."
        )
    token = credentials.load_token(account)
    return GmailConnector(
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        token=token,
        owner_address=account.account_email or get_settings().owner_email,
    )


@dataclass
class SyncResult:
    fetched: int
    ingested: int
    skipped: int


def run_sync(session: Session, owner_id: int, *, connector: Connector | None = None, llm=None) -> SyncResult:
    settings = get_settings()
    if connector is None:
        connector = build_connector(settings, session=session, owner_id=owner_id)
    llm = llm or get_llm(settings)

    # Incremental sync: resume from the stored cursor for credential-backed
    # connectors (e.g. Gmail). Ingest is idempotent, so any overlap is deduped.
    account = None
    if connector.platform == GmailConnector.platform:
        account = credentials.get_account(session, owner_id)
    since = account.last_sync_at if account is not None else None
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    messages = sorted(connector.fetch_messages(since=since), key=lambda m: m.received_at)
    ingested = skipped = 0
    for msg in messages:
        outcome = ingest_message(session, owner_id, msg, llm)
        if outcome.skipped:
            skipped += 1
        else:
            ingested += 1

    if account is not None:
        token = connector.export_token() if hasattr(connector, "export_token") else None
        credentials.record_sync(session, account, last_sync_at=started_at, token=token)

    return SyncResult(fetched=len(messages), ingested=ingested, skipped=skipped)
