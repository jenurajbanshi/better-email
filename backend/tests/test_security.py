"""Security is part of the automated test suite: every privacy claim has a test
that fails if the claim stops being true."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.llm.base import CustomerContext, LLMProvider, MessageContext
from app.llm.factory import RedactingProvider
from app.llm.mock import MockLLMProvider
from app.models import Owner
from app.security import decrypt_secret, encrypt_secret, hash_api_key, verify_api_key


class _SpyProvider(MockLLMProvider):
    """Records every piece of text it is asked to reason over."""

    def __init__(self):
        self.seen: list[str] = []

    def _record(self, *parts):
        self.seen.extend(p for p in parts if p)

    def classify_identity(self, message, candidates):
        self._record(message.from_name, message.subject, message.snippet)
        for c in candidates:
            self._record(c.display_name, *c.known_snippets)
        return super().classify_identity(message, candidates)

    def triage(self, messages):
        for m in messages:
            self._record(m.from_name, m.subject, m.snippet)
        return super().triage(messages)


def test_no_raw_pii_reaches_the_model():
    spy = _SpyProvider()
    redacting = RedactingProvider(spy)
    msg = MessageContext(
        from_name="Sarah Chen",
        subject="Login broken",
        snippet="Email me at sarah.chen@acme.com or call +1 415-555-0117",
    )
    redacting.classify_identity(msg, [CustomerContext(1, "Marcus Lee", None, ["card 4242 4242 4242 4242"])])
    blob = " ".join(spy.seen)
    assert "sarah.chen@acme.com" not in blob
    assert "415-555-0117" not in blob
    assert "4242 4242 4242 4242" not in blob
    assert "<EMAIL_1>" in blob  # placeholder did reach the model


def test_redacting_provider_returns_unredacted_results():
    redacting = RedactingProvider(MockLLMProvider())
    msg = MessageContext("Sarah", "Help", "write to sarah.chen@acme.com please")
    result = redacting.triage([msg])
    # The user-facing summary must contain the real value, not the placeholder.
    assert "<EMAIL_1>" not in (result.summary + result.ask + result.title)


def test_secret_encryption_round_trip_and_not_plaintext():
    token = "ya29.super-secret-oauth-token"
    enc = encrypt_secret(token)
    assert token not in enc
    assert decrypt_secret(enc) == token


def test_api_key_is_hashed_not_stored_plaintext(session):
    owner = session.scalar(select(Owner))
    assert owner.api_key_hash != "test-owner-key"
    assert verify_api_key("test-owner-key", owner.api_key_hash)
    assert not verify_api_key("wrong-key", owner.api_key_hash)
    assert hash_api_key("test-owner-key") == owner.api_key_hash


def test_no_dotenv_committed():
    repo_root = Path(__file__).resolve().parents[2]
    assert not (repo_root / ".env").exists(), ".env must never be committed"
    assert (repo_root / ".env.example").exists()


def test_prod_rejects_insecure_secret(monkeypatch):
    from app.config import Settings

    s = Settings(app_env="prod", secret_key="dev-only-insecure-change-me")
    with pytest.raises(RuntimeError):
        s.validate_for_runtime()


def test_cors_is_not_wildcard():
    from app.config import get_settings

    assert "*" not in get_settings().cors_origin_list
