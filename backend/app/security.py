"""Security primitives: secret encryption at rest and API-key hashing.

Connector credentials/tokens are encrypted with a key derived from
SECRET_KEY so they are never stored in plaintext. API keys are stored only as
salted hashes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

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
