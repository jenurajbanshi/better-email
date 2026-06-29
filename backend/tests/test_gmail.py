"""Tests for the live Gmail connector: OAuth state, token storage (encrypted
at rest), credential-backed connector building, and incremental sync.

Everything runs offline -- Google network calls are stubbed."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import get_settings
from app.connectors import gmail_oauth
from app.connectors.base import NormalizedMessage
from app.llm.factory import get_llm
from app.security import sign_oauth_state, verify_oauth_state
from app.services import credentials
from app.services.sync import build_connector, run_sync


@pytest.fixture
def gmail_settings():
    """Configure Gmail OAuth on the cached settings for the duration of a test."""
    s = get_settings()
    original = (s.gmail_client_id, s.gmail_client_secret, s.gmail_redirect_uri, s.connector)
    s.gmail_client_id = "test-client-id"
    s.gmail_client_secret = "test-client-secret"
    s.gmail_redirect_uri = "http://localhost:8000/api/connectors/gmail/callback"
    yield s
    s.gmail_client_id, s.gmail_client_secret, s.gmail_redirect_uri, s.connector = original


# --------------------------------------------------------------------------- #
# OAuth state signing
# --------------------------------------------------------------------------- #

def test_oauth_state_round_trip():
    state = sign_oauth_state(42)
    assert verify_oauth_state(state) == 42


def test_oauth_state_rejects_tampering():
    state = sign_oauth_state(7)
    body, _sig = state.split(".", 1)
    forged = f"{body}.deadbeef"
    with pytest.raises(ValueError):
        verify_oauth_state(forged)


def test_oauth_state_rejects_expired():
    state = sign_oauth_state(7)
    with pytest.raises(ValueError):
        verify_oauth_state(state, max_age_seconds=-1)


# --------------------------------------------------------------------------- #
# Authorize URL
# --------------------------------------------------------------------------- #

def test_authorization_url_has_least_privilege_scopes(gmail_settings):
    url = gmail_oauth.authorization_url(gmail_settings, state="abc")
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert qs["client_id"] == ["test-client-id"]
    assert qs["state"] == ["abc"]
    assert qs["access_type"] == ["offline"]
    assert qs["response_type"] == ["code"]
    scope = qs["scope"][0]
    assert "gmail.readonly" in scope
    assert "gmail.send" in scope
    # Least-privilege: never the full-mailbox scope.
    assert "mail.google.com" not in scope


def test_authorize_endpoint_returns_consent_url(client, gmail_settings):
    resp = client.get("/api/connectors/gmail/authorize")
    assert resp.status_code == 200
    url = resp.json()["authorization_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")


def test_authorize_endpoint_requires_configuration(client):
    s = get_settings()
    s.gmail_client_id = ""
    s.gmail_client_secret = ""
    resp = client.get("/api/connectors/gmail/authorize")
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Credential storage (encrypted at rest)
# --------------------------------------------------------------------------- #

def test_token_is_encrypted_at_rest(session, owner):
    token = {"access_token": "ya29.secret", "refresh_token": "1//refresh-secret"}
    account = credentials.save_account(
        session, owner.id, token=token, account_email="me@gmail.com", history_id="123"
    )
    assert "ya29.secret" not in account.encrypted_token
    assert "1//refresh-secret" not in account.encrypted_token
    assert credentials.load_token(account) == token
    assert account.account_email == "me@gmail.com"


# --------------------------------------------------------------------------- #
# OAuth callback
# --------------------------------------------------------------------------- #

def test_callback_stores_account(client, session, owner, gmail_settings, monkeypatch):
    monkeypatch.setattr(
        gmail_oauth, "exchange_code",
        lambda settings, code: {"access_token": "ya29.new", "refresh_token": "1//r"},
    )
    monkeypatch.setattr(
        gmail_oauth, "fetch_profile",
        lambda token: {"emailAddress": "owner.real@gmail.com", "historyId": 999},
    )
    state = sign_oauth_state(owner.id)
    resp = client.get(f"/api/connectors/gmail/callback?code=abc123&state={state}")
    assert resp.status_code == 200
    assert "Gmail connected" in resp.text

    account = credentials.get_account(session, owner.id)
    assert account is not None
    assert account.account_email == "owner.real@gmail.com"
    assert account.history_id == "999"
    assert credentials.load_token(account)["access_token"] == "ya29.new"


def test_callback_rejects_bad_state(client):
    resp = client.get("/api/connectors/gmail/callback?code=abc&state=not-a-valid-state")
    assert resp.status_code == 400
    assert "Invalid or expired" in resp.text


def test_connector_status_reflects_connection(client, session, owner):
    before = client.get("/api/connectors").json()
    assert before["gmail_connected"] is False

    credentials.save_account(session, owner.id, token={"access_token": "x"}, account_email="me@gmail.com")
    after = client.get("/api/connectors").json()
    assert after["gmail_connected"] is True
    assert after["gmail_address"] == "me@gmail.com"


def test_disconnect_removes_account(client, session, owner):
    credentials.save_account(session, owner.id, token={"access_token": "x"}, account_email="me@gmail.com")
    resp = client.post("/api/connectors/gmail/disconnect")
    assert resp.status_code == 200
    assert resp.json()["gmail_connected"] is False
    assert credentials.get_account(session, owner.id) is None


# --------------------------------------------------------------------------- #
# build_connector with stored credentials
# --------------------------------------------------------------------------- #

def test_build_connector_gmail_requires_credentials(session, owner, gmail_settings):
    gmail_settings.connector = "gmail"
    with pytest.raises(RuntimeError, match="not connected"):
        build_connector(gmail_settings, session=session, owner_id=owner.id)


def test_build_connector_gmail_with_credentials(session, owner, gmail_settings):
    gmail_settings.connector = "gmail"
    credentials.save_account(
        session, owner.id, token={"access_token": "ya29.x"}, account_email="me@gmail.com"
    )
    connector = build_connector(gmail_settings, session=session, owner_id=owner.id)
    assert connector.platform == "gmail"
    assert connector.token["access_token"] == "ya29.x"
    assert connector.owner_address == "me@gmail.com"


# --------------------------------------------------------------------------- #
# Incremental sync + token persistence
# --------------------------------------------------------------------------- #

class _FakeGmail:
    """Stands in for GmailConnector: records the incremental `since` cursor and
    reports a refreshed token, without any Google network calls."""

    platform = "gmail"

    def __init__(self, messages):
        self._messages = messages
        self.since_calls: list = []
        self.refreshed_token = {"access_token": "ya29.refreshed", "refresh_token": "1//r"}

    def fetch_messages(self, since=None):
        self.since_calls.append(since)
        if since is None:
            return list(self._messages)
        return [m for m in self._messages if m.received_at >= since]

    def export_token(self):
        return self.refreshed_token

    def send_reply(self, **kwargs):  # pragma: no cover - not exercised here
        return "SENT-1"


def _gmail_msg(i: int, when: datetime) -> NormalizedMessage:
    return NormalizedMessage(
        platform="gmail",
        platform_message_id=f"g{i}",
        direction="inbound",
        received_at=when,
        from_name=f"Customer {i}",
        from_email=f"customer{i}@example.com",
        to_addrs=["me@gmail.com"],
        subject=f"Help request {i}",
        body=f"Please help with issue {i}.",
        thread_id=f"t{i}",
    )


def test_incremental_sync_persists_cursor_and_token(session, owner):
    account = credentials.save_account(
        session, owner.id, token={"access_token": "ya29.old"}, account_email="me@gmail.com"
    )
    assert account.last_sync_at is None

    msgs = [_gmail_msg(1, datetime(2026, 1, 1, tzinfo=timezone.utc)),
            _gmail_msg(2, datetime(2026, 1, 2, tzinfo=timezone.utc))]
    fake = _FakeGmail(msgs)

    result = run_sync(session, owner.id, connector=fake, llm=get_llm())
    assert result.fetched == 2
    assert result.ingested == 2

    session.refresh(account)
    # First run starts from no cursor, then advances it and persists the token.
    assert fake.since_calls == [None]
    assert account.last_sync_at is not None
    assert credentials.load_token(account)["access_token"] == "ya29.refreshed"

    # Second run resumes from the stored cursor (incremental).
    run_sync(session, owner.id, connector=fake, llm=get_llm())
    assert fake.since_calls[1] is not None
