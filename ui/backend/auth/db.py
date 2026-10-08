"""Async SQLAlchemy engine and session factory for the user module."""

import os
from typing import AsyncGenerator
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "evidencelab")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "evidencelab")
POSTGRES_DBNAME = os.environ.get(
    "POSTGRES_DBNAME", os.environ.get("POSTGRES_DB", "evidencelab")
)

DATABASE_URL = (
    f"postgresql+asyncpg://{quote_plus(POSTGRES_USER)}:{quote_plus(POSTGRES_PASSWORD)}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DBNAME}"
)

# SQLAlchemy's default pool is 5 connections with 10 overflow. Requests queue
# (up to pool_timeout) rather than failing when it is full, so the default
# shows up as latency under load rather than errors. Size it from the
# environment so a deployment can match its request concurrency.
AUTH_DB_POOL_SIZE = int(os.environ.get("AUTH_DB_POOL_SIZE", "10"))
AUTH_DB_MAX_OVERFLOW = int(os.environ.get("AUTH_DB_MAX_OVERFLOW", "20"))

engine = create_async_engine(
    DATABASE_URL,
    pool_size=AUTH_DB_POOL_SIZE,
    max_overflow=AUTH_DB_MAX_OVERFLOW,
    pool_pre_ping=True,
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async with async_session_factory() as session:
        yield session
