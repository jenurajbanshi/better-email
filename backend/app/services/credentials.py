"""Connector credential storage.

OAuth tokens are persisted ONLY as Fernet-encrypted blobs (via SECRET_KEY); the
plaintext token never touches the database. This is the bridge between the OAuth
flow (which obtains tokens) and the connector (which consumes them).
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ConnectorAccount
from ..security import decrypt_secret, encrypt_secret

GMAIL_PLATFORM = "gmail"


def get_account(session: Session, owner_id: int, platform: str = GMAIL_PLATFORM) -> ConnectorAccount | None:
    return session.scalar(
        select(ConnectorAccount).where(
            ConnectorAccount.owner_id == owner_id,
            ConnectorAccount.platform == platform,
        )
    )


def load_token(account: ConnectorAccount) -> dict:
    return json.loads(decrypt_secret(account.encrypted_token))


def save_account(
    session: Session,
    owner_id: int,
    *,
    token: dict,
    account_email: str | None = None,
    history_id: str | None = None,
    platform: str = GMAIL_PLATFORM,
) -> ConnectorAccount:
    """Create or update (upsert) the stored, encrypted connector credentials."""
    account = get_account(session, owner_id, platform)
    encrypted = encrypt_secret(json.dumps(token))
    if account is None:
        account = ConnectorAccount(
            owner_id=owner_id,
            platform=platform,
            account_email=account_email,
            encrypted_token=encrypted,
            history_id=history_id,
        )
        session.add(account)
    else:
        account.encrypted_token = encrypted
        if account_email is not None:
            account.account_email = account_email
        if history_id is not None:
            account.history_id = history_id
    session.commit()
    session.refresh(account)
    return account


def update_token(session: Session, account: ConnectorAccount, token: dict) -> None:
    """Persist a refreshed token without touching the sync cursor."""
    account.encrypted_token = encrypt_secret(json.dumps(token))
    session.commit()


def record_sync(
    session: Session,
    account: ConnectorAccount,
    *,
    last_sync_at: datetime,
    token: dict | None = None,
    history_id: str | None = None,
) -> None:
    """Advance the incremental-sync cursor (and persist a refreshed token)."""
    account.last_sync_at = last_sync_at
    if token is not None:
        account.encrypted_token = encrypt_secret(json.dumps(token))
    if history_id is not None:
        account.history_id = history_id
    session.commit()


def delete_account(session: Session, owner_id: int, platform: str = GMAIL_PLATFORM) -> bool:
    account = get_account(session, owner_id, platform)
    if account is None:
        return False
    session.delete(account)
    session.commit()
    return True
