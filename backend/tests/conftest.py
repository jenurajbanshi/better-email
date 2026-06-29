"""Test fixtures. Everything runs offline against a temp SQLite DB with the
mock connector + mock LLM provider -- no network, no API key, deterministic.
"""
from __future__ import annotations

import os
import tempfile

import pytest

# Configure the environment BEFORE importing the app (engine binds at import).
_TMP_DB = os.path.join(tempfile.gettempdir(), "better_email_test.db")
os.environ.update(
    {
        "APP_ENV": "dev",
        "DATABASE_URL": f"sqlite:///{_TMP_DB}",
        "SECRET_KEY": "test-secret-key",
        "OWNER_API_KEY": "test-owner-key",
        "OWNER_EMAIL": "owner@test.local",
        "CORS_ORIGINS": "http://localhost:5173",
        "LLM_PROVIDER": "mock",
        "CONNECTOR": "mock",
        "LLM_REDACT_PII": "true",
        "FORGOTTEN_AFTER_HOURS": "24",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from app.api.deps import bootstrap_owner  # noqa: E402
from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as session:
        bootstrap_owner(session)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def owner(session):
    return bootstrap_owner(session)


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": "test-owner-key"})
        yield c
