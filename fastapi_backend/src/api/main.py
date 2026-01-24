from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_session, init_db
from src.db.models import ActivityLog
from src.services.insights import get_profile_insights

openapi_tags = [
    {"name": "Health", "description": "Service health endpoints."},
    {"name": "Search", "description": "Public GitHub profile search & insights."},
    {"name": "Admin", "description": "Admin endpoints for history and system stats."},
]

app = FastAPI(
    title="GitHub Insights Dashboard API",
    description="Backend API for GitHub Explorer & Developer Persona Insights. All GitHub calls happen server-side.",
    version="0.1.0",
    openapi_tags=openapi_tags,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchResponse(BaseModel):
    source: str = Field(..., description="Whether data came from 'cache' or 'github'.")
    profile: Dict[str, Any] = Field(..., description="Cached/computed profile record.")
    repos_count: Optional[int] = Field(None, description="Number of repos processed (when fetched from GitHub).")


class AdminHistoryRow(BaseModel):
    username_searched: str = Field(..., description="Searched username.")
    searched_at: str = Field(..., description="ISO timestamp.")
    request_latency_ms: int = Field(..., description="Request latency measured at backend.")


class AdminStatsResponse(BaseModel):
    rate_limit_remaining: Optional[str] = Field(None, description="GitHub x-ratelimit-remaining header (if available).")
    top_languages: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Placeholder for aggregated top languages across searches (computed later).",
    )


@app.on_event("startup")
async def _startup() -> None:
    """Initialize database tables on service startup."""
    await init_db()


@app.get("/", tags=["Health"], summary="Health Check")
def health_check() -> Dict[str, str]:
    """Service health check endpoint."""
    return {"message": "Healthy"}


@app.get(
    "/api/search/{username}",
    tags=["Search"],
    summary="Search GitHub user insights",
    response_model=SearchResponse,
)
async def api_search(username: str, session: AsyncSession = Depends(get_session)) -> SearchResponse:
    """
    Search and return insights for a GitHub username.

    Behavior:
    - Uses PostgreSQL caching: if last_updated < 24 hours, returns cached record.
    - Otherwise fetches from GitHub using async httpx (backend-only token).
    - Records an ActivityLog row for admin analytics.

    Errors:
    - 404 if user not found on GitHub.
    """
    try:
        payload, _rate_info = await get_profile_insights(session=session, username=username)
        return SearchResponse(**payload)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="GitHub user not found") from e
        raise HTTPException(status_code=502, detail="GitHub API error") from e


@app.get(
    "/api/admin/history",
    tags=["Admin"],
    summary="Admin: search history",
    response_model=List[AdminHistoryRow],
)
async def admin_history(session: AsyncSession = Depends(get_session)) -> List[AdminHistoryRow]:
    """
    Return recent search history (latest first).

    Note: This is scaffolded for the admin table UI; filtering/pagination can be added later.
    """
    res = await session.execute(
        select(ActivityLog).order_by(ActivityLog.searched_at.desc()).limit(50)
    )
    rows = res.scalars().all()
    return [
        AdminHistoryRow(
            username_searched=r.username_searched,
            searched_at=r.searched_at.isoformat(),
            request_latency_ms=r.request_latency_ms,
        )
        for r in rows
    ]


@app.get(
    "/api/admin/stats",
    tags=["Admin"],
    summary="Admin: system stats",
    response_model=AdminStatsResponse,
)
async def admin_stats(session: AsyncSession = Depends(get_session)) -> AdminStatsResponse:
    """
    Return admin stats.

    - rate_limit_remaining is returned as a placeholder (full propagation will be added by storing last GitHub headers).
    - top_languages is a placeholder for future aggregation query across cached profiles.
    """
    # Simple heartbeat query to ensure DB connectivity
    await session.execute(select(func.count(ActivityLog.id)))

    return AdminStatsResponse(rate_limit_remaining=None, top_languages=[])
