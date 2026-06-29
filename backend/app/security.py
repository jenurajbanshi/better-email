"""Security primitives: secret encryption at rest and API-key hashing.

Connector credentials/tokens are encrypted with a key derived from
SECRET_KEY so they are never stored in plaintext. API keys are stored only as
salted hashes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from cryptography.fernet import Fernet

from .config import get_settings


def _derive_fernet_key(secret_key: str) -> bytes:
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_derive_fernet_key(get_settings().secret_key))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret (e.g. an OAuth token) for storage at rest."""
    if plaintext is None:
        plaintext = ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def hash_api_key(api_key: str) -> str:
    """Salted (via SECRET_KEY) one-way hash for API-key storage."""
    return hmac.new(
        get_settings().secret_key.encode("utf-8"),
        api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_api_key(api_key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(api_key), stored_hash)


def _state_sig(body: str) -> str:
    return hmac.new(
        get_settings().secret_key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def sign_oauth_state(owner_id: int) -> str:
    """Create a tamper-proof OAuth ``state`` that carries the owner id.

    The OAuth callback is hit by the browser without our API key, so the owner
    must be carried (and authenticated) inside the signed state instead.
    """
    payload = {"owner_id": owner_id, "ts": int(time.time()), "nonce": secrets.token_urlsafe(8)}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    return f"{body}.{_state_sig(body)}"


def verify_oauth_state(state: str, *, max_age_seconds: int = 600) -> int:
    """Validate a signed OAuth state and return the embedded owner id.

    Raises ``ValueError`` if the signature is invalid or the state is expired.
    """
    try:
        body, sig = state.split(".", 1)
    except (ValueError, AttributeError) as e:
        raise ValueError("Malformed OAuth state") from e
    if not hmac.compare_digest(sig, _state_sig(body)):
        raise ValueError("Invalid OAuth state signature")
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode("utf-8")))
    except (ValueError, TypeError) as e:
        raise ValueError("Corrupt OAuth state") from e
    if int(time.time()) - int(payload.get("ts", 0)) > max_age_seconds:
        raise ValueError("OAuth state expired")
    return int(payload["owner_id"])
