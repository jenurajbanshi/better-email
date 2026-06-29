"""Database engine/session setup.

Uses SQLAlchemy so the app works with SQLite (local/demo) and Postgres
(production / Railway) with no code change -- only DATABASE_URL differs.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(database_url: str):
    connect_args = {}
    if database_url.startswith("sqlite"):
        # Required for SQLite when used across threads (FastAPI).
        connect_args = {"check_same_thread": False}
    return create_engine(database_url, connect_args=connect_args, future=True)


engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    # Import models so they register on Base.metadata before create_all.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
