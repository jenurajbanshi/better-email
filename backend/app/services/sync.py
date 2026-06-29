"""Sync orchestration: pull from a connector and run each message through the
ingest pipeline. Structured as a plain callable so it can run in-process now
and be promoted to a dedicated worker / Railway cron job later unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..connectors.base import Connector
from ..connectors.mock import MockConnector
from ..llm.factory import get_llm
from .ingest import ingest_message


def build_connector(settings: Settings | None = None) -> Connector:
    settings = settings or get_settings()
    name = settings.connector.lower()
    if name == "mock":
        return MockConnector()
    if name == "gmail":
        # Real Gmail requires stored OAuth credentials; wired as a follow-up.
        raise RuntimeError(
            "Gmail connector requires OAuth credentials. Complete the Gmail OAuth "
            "setup, then configure CONNECTOR=gmail. The mock connector is the default."
        )
    raise ValueError(f"Unknown CONNECTOR: {settings.connector}")


@dataclass
class SyncResult:
    fetched: int
    ingested: int
    skipped: int


def run_sync(session: Session, owner_id: int, *, connector: Connector | None = None, llm=None) -> SyncResult:
    settings = get_settings()
    connector = connector or build_connector(settings)
    llm = llm or get_llm(settings)

    messages = sorted(connector.fetch_messages(), key=lambda m: m.received_at)
    ingested = skipped = 0
    for msg in messages:
        outcome = ingest_message(session, owner_id, msg, llm)
        if outcome.skipped:
            skipped += 1
        else:
            ingested += 1
    return SyncResult(fetched=len(messages), ingested=ingested, skipped=skipped)
