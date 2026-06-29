"""PII redaction layer.

Masks personally identifying tokens before any text is sent to an LLM, and
restores them on the way back. Deterministic and provider-agnostic, so even a
cloud model sees placeholders (``<EMAIL_1>``) rather than raw identifiers.

The redaction is lossless: ``unredact(redact(text)[0], mapping) == text``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# International-ish phone numbers (loose on purpose).
PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\-\s().]{7,}\d)(?!\w)")
CREDIT_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")

# Order matters: most specific first so a card isn't caught as a phone.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SSN", SSN_RE),
    ("CARD", CREDIT_CARD_RE),
    ("EMAIL", EMAIL_RE),
    ("PHONE", PHONE_RE),
]


@dataclass
class RedactionResult:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)


def redact(text: str) -> RedactionResult:
    if not text:
        return RedactionResult(text=text or "", mapping={})

    mapping: dict[str, str] = {}
    reverse: dict[str, str] = {}
    counters: dict[str, int] = {}

    def make_token(label: str, value: str) -> str:
        if value in reverse:
            return reverse[value]
        counters[label] = counters.get(label, 0) + 1
        token = f"<{label}_{counters[label]}>"
        mapping[token] = value
        reverse[value] = token
        return token

    result = text
    for label, pattern in _PATTERNS:
        def _sub(m: re.Match[str], _label=label) -> str:
            return make_token(_label, m.group(0))

        result = pattern.sub(_sub, result)

    return RedactionResult(text=result, mapping=mapping)


def unredact(text: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return text
    result = text
    for token, value in mapping.items():
        result = result.replace(token, value)
    return result


def maybe_redact(text: str, enabled: bool) -> RedactionResult:
    return redact(text) if enabled else RedactionResult(text=text or "", mapping={})
