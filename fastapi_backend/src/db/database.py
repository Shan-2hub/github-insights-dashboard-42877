import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel


def _build_db_url() -> str:
    """
    Compose a PostgreSQL DSN from environment variables.

    Expected env vars (provided by platform):
    - POSTGRES_URL, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_PORT

    Note: We intentionally do not guess the shape of POSTGRES_URL; we compose a standard DSN.
    """
    host = os.getenv("POSTGRES_URL", "")
    user = os.getenv("POSTGRES_USER", "")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db = os.getenv("POSTGRES_DB", "")
    port = os.getenv("POSTGRES_PORT", "")

    # host may already include protocol in some environments; keep it simple and safe:
    # We only handle the common "hostname" form here.
    if not host:
        raise RuntimeError("POSTGRES_URL is required")

    port_part = f":{port}" if port else ""
    return f"postgresql+asyncpg://{user}:{password}@{host}{port_part}/{db}"


DATABASE_URL = _build_db_url()

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# PUBLIC_INTERFACE
async def init_db() -> None:
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


# PUBLIC_INTERFACE
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with AsyncSessionLocal() as session:
        yield session
