"""Shared base for real providers that return structured JSON.

Subclasses only implement ``_complete(system, user) -> str``; prompt building
and JSON parsing live here so OpenAI/Anthropic/Ollama stay thin.
"""
from __future__ import annotations

import json
from abc import abstractmethod

from .base import (
    CustomerContext,
    GroupingDecision,
    IdentityDecision,
    LLMProvider,
    MessageContext,
    RequestContext,
    TriageResult,
)

_IDENTITY_SYSTEM = (
    "You are an entity-resolution assistant for a support inbox. Decide whether "
    "an incoming message is from one of the known customers, or a new one. Bias "
    "toward 'new' unless evidence is strong: a false merge leaks one customer's "
    "data to another. Text may contain placeholders like <EMAIL_1>; treat equal "
    "placeholders as the same value. Respond ONLY with JSON: "
    '{"matched_customer_id": <int|null>, "confidence": <0..1>, "reason": <string>}.'
)
_GROUPING_SYSTEM = (
    "You group a support message into an existing open request or a new one. "
    "Respond ONLY with JSON: "
    '{"matched_request_id": <int|null>, "confidence": <0..1>, "reason": <string>}.'
)
_TRIAGE_SYSTEM = (
    "You triage a support request. Respond ONLY with JSON: "
    '{"title": <string>, "summary": <string>, "ask": <string>, '
    '"priority": "low|normal|high|urgent", "sentiment": "positive|neutral|negative"}.'
)
_DRAFT_SYSTEM = (
    "You draft a concise, empathetic support reply. Output only the reply body."
)


def _msg_lines(messages: list[MessageContext]) -> str:
    return "\n".join(
        f"- [{m.direction}] from={m.from_name or '?'} subject={m.subject or ''} :: {m.snippet}"
        for m in messages
    )


class JSONChatProvider(LLMProvider):
    @abstractmethod
    def _complete(self, system: str, user: str) -> str:
        ...

    def _json(self, system: str, user: str) -> dict:
        raw = self._complete(system, user).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[raw.find("{") :]
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            raw = raw[start : end + 1]
        return json.loads(raw)

    def classify_identity(self, message, candidates: list[CustomerContext]) -> IdentityDecision:
        cand = "\n".join(
            f"- id={c.customer_id} name={c.display_name} company={c.company or ''} "
            f"examples={' | '.join(c.known_snippets[:2])}"
            for c in candidates
        ) or "(none)"
        user = (
            f"Known customers:\n{cand}\n\nIncoming message:\n"
            f"from={message.from_name or '?'} subject={message.subject or ''}\n{message.snippet}"
        )
        d = self._json(_IDENTITY_SYSTEM, user)
        return IdentityDecision(d.get("matched_customer_id"), float(d.get("confidence", 0.0)), str(d.get("reason", "")))

    def group_request(self, message, open_requests: list[RequestContext]) -> GroupingDecision:
        reqs = "\n".join(
            f"- id={r.request_id} title={r.title} status={r.status} summary={r.summary or ''}"
            for r in open_requests
        ) or "(none)"
        user = (
            f"Open requests:\n{reqs}\n\nIncoming message:\n"
            f"subject={message.subject or ''}\n{message.snippet}"
        )
        d = self._json(_GROUPING_SYSTEM, user)
        return GroupingDecision(d.get("matched_request_id"), float(d.get("confidence", 0.0)), str(d.get("reason", "")))

    def triage(self, messages: list[MessageContext]) -> TriageResult:
        d = self._json(_TRIAGE_SYSTEM, f"Messages (oldest first):\n{_msg_lines(messages)}")
        return TriageResult(
            summary=str(d.get("summary", "")),
            ask=str(d.get("ask", "")),
            priority=str(d.get("priority", "normal")),
            sentiment=str(d.get("sentiment", "neutral")),
            title=str(d.get("title", "Customer request")),
        )

    def draft_reply(self, messages: list[MessageContext], summary: str) -> str:
        user = f"Request summary: {summary}\n\nConversation:\n{_msg_lines(messages)}\n\nWrite the reply body."
        return self._complete(_DRAFT_SYSTEM, user).strip()
