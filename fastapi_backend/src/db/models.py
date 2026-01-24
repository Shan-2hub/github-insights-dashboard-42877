from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Profile(SQLModel, table=True):
    """Cached GitHub profile + computed insights."""

    id: Optional[int] = Field(default=None, primary_key=True)

    username: str = Field(index=True, nullable=False, unique=True)
    full_name: Optional[str] = Field(default=None)
    bio: Optional[str] = Field(default=None)

    avatar_url: Optional[str] = Field(default=None)
    followers: int = Field(default=0)
    following: int = Field(default=0)
    public_repos: int = Field(default=0)

    total_stars: int = Field(default=0)

    # Store language distribution as JSONB: { "Python": 12345, "TypeScript": 9000, ... }
    top_languages: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB))

    last_updated: datetime = Field(default_factory=datetime.utcnow, index=True)


class ActivityLog(SQLModel, table=True):
    """Search log for admin analytics."""

    id: Optional[int] = Field(default=None, primary_key=True)

    username_searched: str = Field(index=True, nullable=False)
    searched_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    request_latency_ms: int = Field(default=0)
