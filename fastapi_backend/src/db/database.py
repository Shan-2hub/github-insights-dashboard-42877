import os
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel


def _build_db_url() -> str:
    """
    Compose a PostgreSQL DSN from environment variables.

    Expected env vars (provided by platform):
    - POSTGRES_URL, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_PORT

    Notes:
    - In some preview environments, the DB container can start slightly after the API container
      and env var injection can be delayed/misconfigured. We therefore avoid crashing at import
      time and instead raise a clear runtime error when DB access is required.
    - We intentionally do not guess the shape of POSTGRES_URL; we compose a standard DSN.
    """
    host = (os.getenv("POSTGRES_URL") or "").strip()
    user = os.getenv("POSTGRES_USER", "")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db = os.getenv("POSTGRES_DB", "")
    port = (os.getenv("POSTGRES_PORT") or "").strip()

    if not host:
        raise RuntimeError(
            "Database configuration missing: POSTGRES_URL is required. "
            "Ensure the postgresql_database container is running and POSTGRES_* env vars are set."
        )

    # Only include port when present; omitting it is valid and avoids parsing edge cases.
    port_part = f":{port}" if port else ""
    return f"postgresql+asyncpg://{user}:{password}@{host}{port_part}/{db}"


_ENGINE: Optional[AsyncEngine] = None
_AsyncSessionLocal = None


def _get_engine() -> AsyncEngine:
    """
    Lazily create and return the AsyncEngine.

    This prevents import-time crashes when POSTGRES_* env vars are not set yet.
    """
    global _ENGINE, _AsyncSessionLocal
    if _ENGINE is None:
        database_url = _build_db_url()
        _ENGINE = create_async_engine(
            database_url,
            echo=False,
            pool_pre_ping=True,
        )
        _AsyncSessionLocal = sessionmaker(_ENGINE, class_=AsyncSession, expire_on_commit=False)
    return _ENGINE


# PUBLIC_INTERFACE
async def init_db() -> None:
    """Initialize database tables."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


# PUBLIC_INTERFACE
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    _get_engine()  # ensures sessionmaker is created or raises a clear error
    async with _AsyncSessionLocal() as session:
        yield session
