"""Request dependencies: DB session and API-key authentication.

Every protected route resolves the owner from the API key and all queries are
scoped to that ``owner_id`` -- tenant isolation enforced in the data layer.
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..models import Owner
from ..security import hash_api_key, verify_api_key


def bootstrap_owner(session: Session) -> Owner:
    """Ensure the single configured owner exists (idempotent)."""
    settings = get_settings()
    owner = session.scalar(select(Owner).where(Owner.email == settings.owner_email))
    if owner is None:
        owner = Owner(email=settings.owner_email, api_key_hash=hash_api_key(settings.owner_api_key))
        session.add(owner)
        session.commit()
        session.refresh(owner)
    return owner


def _extract_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def get_current_owner(
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> Owner:
    api_key = _extract_key(authorization, x_api_key)
    if not api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")

    # Resolve strictly by hash match -- never trust a client-supplied owner id.
    for owner in session.scalars(select(Owner)):
        if verify_api_key(api_key, owner.api_key_hash):
            return owner
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
