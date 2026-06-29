"""Gmail OAuth 2.0 web flow (authorization-code grant).

Implemented with plain HTTP (httpx, already a dependency) so the flow has no
hard dependency on the optional Google client libraries and is fully testable
offline. The Google client libraries are only needed at message fetch/send time
(see ``gmail.py``).
"""
from __future__ import annotations

from urllib.parse import urlencode

import httpx

from ..config import Settings
from .gmail import GMAIL_SCOPES

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
PROFILE_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/profile"


def authorization_url(settings: Settings, state: str) -> str:
    """Build the Google consent-screen URL.

    ``access_type=offline`` + ``prompt=consent`` ensures Google returns a
    refresh token so we can keep syncing without re-prompting the user.
    """
    params = {
        "client_id": settings.gmail_client_id,
        "redirect_uri": settings.gmail_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_code(settings: Settings, code: str) -> dict:
    """Exchange an authorization code for an OAuth token dict."""
    data = {
        "code": code,
        "client_id": settings.gmail_client_id,
        "client_secret": settings.gmail_client_secret,
        "redirect_uri": settings.gmail_redirect_uri,
        "grant_type": "authorization_code",
    }
    resp = httpx.post(TOKEN_ENDPOINT, data=data, timeout=30.0)
    resp.raise_for_status()
    token = resp.json()
    return {
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "scope": token.get("scope"),
        "token_type": token.get("token_type"),
        "expires_in": token.get("expires_in"),
    }


def fetch_profile(token: dict) -> dict:
    """Return the connected mailbox profile (``emailAddress``, ``historyId``).

    Uses the Gmail profile endpoint, which is covered by ``gmail.readonly`` so
    no extra OpenID/email scope is required.
    """
    resp = httpx.get(
        PROFILE_ENDPOINT,
        headers={"Authorization": f"Bearer {token.get('access_token')}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()
