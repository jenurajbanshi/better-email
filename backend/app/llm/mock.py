"""Deterministic mock LLM provider.

Lets the entire app run and be tested offline, with no API key and no cost.
Its outputs are plausible and derived from simple heuristics so the demo and
the test suite are meaningful and reproducible.
"""
from __future__ import annotations

import re

from .base import (
    CustomerContext,
    GroupingDecision,
    IdentityDecision,
    LLMProvider,
    MessageContext,
    RequestContext,
    TriageResult,
)

_STOPWORDS = {
    "the", "a", "an", "to", "of", "and", "for", "in", "on", "is", "it", "i",
    "we", "you", "my", "our", "re", "fwd", "hi", "hello", "hey", "please",
    "with", "this", "that", "about", "re:", "fw:",
}

_URGENT_HINTS = ("urgent", "asap", "immediately", "refund", "charged", "broken", "down", "angry", "cancel")
_NEGATIVE_HINTS = ("not working", "broken", "frustrat", "angry", "disappointed", "refund", "wrong", "still")
_POSITIVE_HINTS = ("thank", "great", "love", "appreciate", "awesome")


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _name_tokens(name: str | None) -> set[str]:
    if not name:
        return set()
    return {w for w in re.findall(r"[a-z]+", name.lower()) if len(w) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class MockLLMProvider(LLMProvider):
    name = "mock"

    def classify_identity(
        self, message: MessageContext, candidates: list[CustomerContext]
    ) -> IdentityDecision:
        msg_name = _name_tokens(message.from_name)
        msg_content = _tokens(message.subject) | _tokens(message.snippet)

        best: tuple[float, CustomerContext | None] = (0.0, None)
        for c in candidates:
            name_score = _jaccard(msg_name, _name_tokens(c.display_name))
            content_score = 0.0
            for snip in c.known_snippets:
                content_score = max(content_score, _jaccard(msg_content, _tokens(snip)))
            score = 0.7 * name_score + 0.3 * content_score
            if score > best[0]:
                best = (score, c)

        score, candidate = best
        if candidate is None or score < 0.34:
            return IdentityDecision(None, round(1.0 - score, 3), "No strong match; treating as new customer.")
        reason = f"Name/content overlap with '{candidate.display_name}' (score={score:.2f})."
        return IdentityDecision(candidate.customer_id, round(min(score + 0.15, 0.99), 3), reason)

    def group_request(
        self, message: MessageContext, open_requests: list[RequestContext]
    ) -> GroupingDecision:
        msg_content = _tokens(message.subject) | _tokens(message.snippet)
        best: tuple[float, RequestContext | None] = (0.0, None)
        for r in open_requests:
            score = _jaccard(msg_content, _tokens(r.title) | _tokens(r.summary or ""))
            if score > best[0]:
                best = (score, r)
        score, req = best
        if req is None or score < 0.3:
            return GroupingDecision(None, round(1.0 - score, 3), "Distinct topic; new request.")
        return GroupingDecision(req.request_id, round(min(score + 0.1, 0.99), 3), f"Overlaps request '{req.title}'.")

    def triage(self, messages: list[MessageContext]) -> TriageResult:
        inbound = [m for m in messages if m.direction == "inbound"] or messages
        latest = inbound[-1]
        blob = " ".join(f"{m.subject or ''} {m.snippet}" for m in inbound).lower()

        priority = "normal"
        if any(h in blob for h in _URGENT_HINTS):
            priority = "urgent" if ("urgent" in blob or "asap" in blob) else "high"

        sentiment = "neutral"
        if any(h in blob for h in _NEGATIVE_HINTS):
            sentiment = "negative"
        elif any(h in blob for h in _POSITIVE_HINTS):
            sentiment = "positive"

        title = (latest.subject or latest.snippet or "Customer request").strip()
        title = re.sub(r"^(re|fwd|fw)\s*:\s*", "", title, flags=re.IGNORECASE)[:80]

        snippet = latest.snippet.strip().replace("\n", " ")
        summary = f"Customer wrote in regarding: {title}. Latest message: \"{snippet[:160]}\""
        ask = snippet[:140] if snippet else "Clarify the customer's request."
        return TriageResult(summary=summary, ask=ask, priority=priority, sentiment=sentiment, title=title or "Customer request")

    def draft_reply(self, messages: list[MessageContext], summary: str) -> str:
        name = next((m.from_name for m in messages if m.from_name), None)
        greeting = f"Hi {name.split()[0]}," if name else "Hi there,"
        return (
            f"{greeting}\n\n"
            "Thanks for reaching out, and apologies for any inconvenience. "
            "I've reviewed your message and I'm looking into it now. "
            "I'll follow up shortly with an update.\n\n"
            "Best regards,\nSupport Team"
        )
