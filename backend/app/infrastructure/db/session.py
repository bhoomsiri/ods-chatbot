"""Async engine + session factory for the chat-history database."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.infrastructure.db.models import Base


def build_engine(url: str) -> AsyncEngine:
    # pool_pre_ping recycles connections dropped by the DB/idle timeouts so a
    # long-lived API process does not hand out dead connections.
    return create_async_engine(url, pool_pre_ping=True)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False so entities returned from a committed transaction
    # stay usable (we map them to domain objects right after).
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine: AsyncEngine) -> None:
    """Create tables if missing. Greenfield schema management; swap for Alembic
    migrations once the schema starts evolving (e.g. when Clerk columns land)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
