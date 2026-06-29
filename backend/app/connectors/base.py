"""Connector interface and the normalized message it must produce.

Adding a new platform = implementing this interface. Nothing downstream
(identity, grouping, triage, UI) ever sees a platform-specific shape.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NormalizedMessage:
    platform: str
    platform_message_id: str
    direction: str  # "inbound" | "outbound"
    received_at: datetime
    from_name: str | None = None
    from_email: str | None = None
    to_addrs: list[str] = field(default_factory=list)
    subject: str | None = None
    body: str = ""
    thread_id: str | None = None
    # Channel-specific structured signals (e.g. form fields: phone, order id).
    # Used by identity resolution but never blindly trusted.
    extra: dict = field(default_factory=dict)

    @property
    def snippet(self) -> str:
        text = (self.body or "").strip().replace("\r", "")
        return text[:300]


class Connector(ABC):
    """A source/sink of messages for one platform."""

    platform: str = "base"

    @abstractmethod
    def fetch_messages(self, since: datetime | None = None) -> list[NormalizedMessage]:
        """Return normalized messages, newest sync window. Must be idempotent:
        callers dedupe on (platform, platform_message_id)."""
        ...

    @abstractmethod
    def send_reply(self, *, to: list[str], subject: str, body: str, thread_id: str | None) -> str:
        """Send an outbound reply. Returns the new platform_message_id.
        v1 callers only invoke this on explicit human action."""
        ...
