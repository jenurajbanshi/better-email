"""Provider selection + a redaction wrapper.

``get_llm()`` returns a provider chosen by config. The returned provider is
wrapped so that, when enabled, all text is PII-redacted before reaching the
model and un-redacted on the way back -- a single choke point for the privacy
guarantee.
"""
from __future__ import annotations

from dataclasses import replace

from ..config import Settings, get_settings
from ..redaction import redact, unredact
from .base import (
    CustomerContext,
    GroupingDecision,
    IdentityDecision,
    LLMProvider,
    MessageContext,
    RequestContext,
    TriageResult,
)
from .mock import MockLLMProvider


def _build_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return MockLLMProvider()
    if provider == "openai":
        from .providers import OpenAIProvider

        return OpenAIProvider(settings.openai_api_key, settings.llm_model)
    if provider == "anthropic":
        from .providers import AnthropicProvider

        return AnthropicProvider(settings.anthropic_api_key, settings.llm_model)
    if provider == "ollama":
        from .providers import OllamaProvider

        return OllamaProvider(settings.ollama_base_url, settings.llm_model)
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")


class RedactingProvider(LLMProvider):
    """Wraps a provider, redacting all outbound text and restoring it on return."""

    def __init__(self, inner: LLMProvider):
        self.inner = inner
        self.name = f"redacting({inner.name})"

    def _rmsg(self, m: MessageContext, mapping: dict) -> MessageContext:
        s_name = redact(m.from_name or "")
        s_subj = redact(m.subject or "")
        s_snip = redact(m.snippet or "")
        mapping.update(s_name.mapping)
        mapping.update(s_subj.mapping)
        mapping.update(s_snip.mapping)
        return replace(m, from_name=s_name.text or None, subject=s_subj.text or None, snippet=s_snip.text)

    def classify_identity(self, message, candidates) -> IdentityDecision:
        mapping: dict[str, str] = {}
        rmsg = self._rmsg(message, mapping)
        rcands = []
        for c in candidates:
            snips = []
            for s in c.known_snippets:
                r = redact(s)
                mapping.update(r.mapping)
                snips.append(r.text)
            name = redact(c.display_name)
            mapping.update(name.mapping)
            rcands.append(CustomerContext(c.customer_id, name.text, c.company, snips))
        d = self.inner.classify_identity(rmsg, rcands)
        return IdentityDecision(d.matched_customer_id, d.confidence, unredact(d.reason, mapping))

    def group_request(self, message, open_requests) -> GroupingDecision:
        mapping: dict[str, str] = {}
        rmsg = self._rmsg(message, mapping)
        rreqs = []
        for r in open_requests:
            t = redact(r.title)
            s = redact(r.summary or "")
            mapping.update(t.mapping)
            mapping.update(s.mapping)
            rreqs.append(RequestContext(r.request_id, t.text, s.text, r.status))
        d = self.inner.group_request(rmsg, rreqs)
        return GroupingDecision(d.matched_request_id, d.confidence, unredact(d.reason, mapping))

    def triage(self, messages) -> TriageResult:
        mapping: dict[str, str] = {}
        rmsgs = [self._rmsg(m, mapping) for m in messages]
        t = self.inner.triage(rmsgs)
        return TriageResult(
            summary=unredact(t.summary, mapping),
            ask=unredact(t.ask, mapping),
            priority=t.priority,
            sentiment=t.sentiment,
            title=unredact(t.title, mapping),
        )

    def draft_reply(self, messages, summary) -> str:
        mapping: dict[str, str] = {}
        rmsgs = [self._rmsg(m, mapping) for m in messages]
        rsum = redact(summary)
        mapping.update(rsum.mapping)
        out = self.inner.draft_reply(rmsgs, rsum.text)
        return unredact(out, mapping)


def get_llm(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    provider = _build_provider(settings)
    if settings.llm_redact_pii:
        return RedactingProvider(provider)
    return provider
