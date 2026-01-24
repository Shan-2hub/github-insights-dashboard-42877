import os
from typing import AsyncGenerator, Optional
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel


def _normalize_async_dsn(dsn: str) -> str:
    """
    Normalize a PostgreSQL DSN to use SQLAlchemy's asyncpg driver.

    Accepts either:
      - postgresql+asyncpg://...
      - postgresql://...

    Returns:
      DSN string with 'postgresql+asyncpg://' scheme.
    """
    dsn = dsn.strip()
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return "postgresql+asyncpg://" + dsn[len("postgresql://") :]
    return dsn


def _first_non_empty(*values: Optional[str]) -> str:
    """Return the first non-empty string from the provided values."""
    for v in values:
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return ""


def _build_db_url() -> str:
    """
    Compose a PostgreSQL DSN from environment variables.

    Supported env var shapes (varies by platform/runtime):
    1) Full DSN:
       - DATABASE_URL=postgresql+asyncpg://user:pass@host:port/db
       - POSTGRES_URL=postgresql://user:pass@host:port/db

       Important:
       - Some runtimes provide POSTGRES_URL without credentials (e.g., postgresql://host:port/db).
         In that case, we MUST use POSTGRES_USER/POSTGRES_PASSWORD, otherwise asyncpg will fall back
         to the OS user (often 'kavia') and the connection fails with "role does not exist".

    2) Component fields:
       - POSTGRES_HOST (or POSTGRES_URL as hostname), POSTGRES_PORT, POSTGRES_DB,
         POSTGRES_USER, POSTGRES_PASSWORD

    Notes:
    - We avoid import-time crashes due to slightly different env var conventions.
    - If a full DSN is provided *with userinfo*, we use it verbatim (normalized to asyncpg).
    """
    explicit_dsn = _first_non_empty(os.getenv("DATABASE_URL"), os.getenv("POSTGRES_URL"))
    if explicit_dsn.startswith(("postgresql://", "postgresql+asyncpg://")):
        parsed = urlparse(explicit_dsn)
        # If username is missing, treat it as a host-only DSN and fall back to composing
        # with POSTGRES_USER/POSTGRES_PASSWORD/etc.
        if parsed.username:
            return _normalize_async_dsn(explicit_dsn)

    host = _first_non_empty(os.getenv("POSTGRES_HOST"), os.getenv("POSTGRES_URL"))
    user = _first_non_empty(os.getenv("POSTGRES_USER"))
    password = _first_non_empty(os.getenv("POSTGRES_PASSWORD"))
    db = _first_non_empty(os.getenv("POSTGRES_DB"))
    port = _first_non_empty(os.getenv("POSTGRES_PORT"))

    if not host:
        raise RuntimeError(
            "Database host is required. Set DATABASE_URL/POSTGRES_URL to a full DSN "
            "or provide POSTGRES_HOST."
        )

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
