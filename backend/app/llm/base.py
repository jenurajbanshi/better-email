"""LLM provider interface and the (redacted) context/result types it speaks.

Business logic only ever passes these neutral context objects -- never ORM
rows -- so providers are fully swappable and the redaction boundary is explicit.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class MessageContext:
    from_name: str | None
    subject: str | None
    snippet: str
    direction: str = "inbound"


@dataclass
class CustomerContext:
    customer_id: int
    display_name: str
    company: str | None
    known_snippets: list[str] = field(default_factory=list)


@dataclass
class RequestContext:
    request_id: int
    title: str
    summary: str | None
    status: str


@dataclass
class IdentityDecision:
    # matched_customer_id is None when the model believes this is a new customer.
    matched_customer_id: int | None
    confidence: float
    reason: str


@dataclass
class GroupingDecision:
    # matched_request_id is None when this should start a new request.
    matched_request_id: int | None
    confidence: float
    reason: str


@dataclass
class TriageResult:
    summary: str
    ask: str
    priority: str  # low|normal|high|urgent
    sentiment: str  # positive|neutral|negative
    title: str


class LLMProvider(ABC):
    """Interface every model backend implements. Implementations receive
    already-redacted text when redaction is enabled."""

    name: str = "base"

    @abstractmethod
    def classify_identity(
        self, message: MessageContext, candidates: list[CustomerContext]
    ) -> IdentityDecision:
        ...

    @abstractmethod
    def group_request(
        self, message: MessageContext, open_requests: list[RequestContext]
    ) -> GroupingDecision:
        ...

    @abstractmethod
    def triage(self, messages: list[MessageContext]) -> TriageResult:
        ...

    @abstractmethod
    def draft_reply(self, messages: list[MessageContext], summary: str) -> str:
        ...
