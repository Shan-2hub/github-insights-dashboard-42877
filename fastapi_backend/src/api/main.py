from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.routes import require_admin, router as auth_router
from src.db.database import get_session, init_db
from src.db.models import ActivityLog, Profile
from src.services.insights import get_profile_insights

openapi_tags = [
    {"name": "Health", "description": "Service health endpoints."},
    {"name": "Auth", "description": "JWT-based authentication."},
    {"name": "Search", "description": "Public GitHub profile search & insights."},
    {"name": "Admin", "description": "Protected admin endpoints for global stats and history."},
]

app = FastAPI(
    title="Elite Explorer API",
    description=(
        "Backend API for the GitHub Elite Explorer dashboard. "
        "All GitHub requests happen server-side with secure token usage and DB caching."
    ),
    version="0.2.0",
    openapi_tags=openapi_tags,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


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
    rate_limit_limit: Optional[str] = Field(None, description="GitHub x-ratelimit-limit header (if available).")
    rate_limit_reset: Optional[str] = Field(None, description="GitHub x-ratelimit-reset header (if available).")
    rate_limit_used: Optional[str] = Field(None, description="GitHub x-ratelimit-used header (if available).")
    top_languages: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Aggregated top languages across cached profiles (from JSONB counts).",
    )
    total_cached_profiles: int = Field(0, description="Number of cached profiles stored in DB.")
    total_searches: int = Field(0, description="Number of searches logged in ActivityLog.")


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
    - Otherwise fetches from GitHub using async httpx (backend-only token) and saves to DB.
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
    dependencies=[Depends(require_admin)],
)
async def admin_history(session: AsyncSession = Depends(get_session)) -> List[AdminHistoryRow]:
    """
    Return recent search history (latest first).

    Protected:
    - Requires JWT with is_admin=true.
    """
    res = await session.execute(select(ActivityLog).order_by(ActivityLog.searched_at.desc()).limit(50))
    rows = res.scalars().all()
    return [
        AdminHistoryRow(
            username_searched=r.username_searched,
            searched_at=r.searched_at.isoformat(),
            request_latency_ms=r.request_latency_ms,
        )
        for r in rows
    ]


async def _aggregate_top_languages(session: AsyncSession) -> List[Dict[str, Any]]:
    """
    Aggregate top languages from cached profiles.

    Note:
    - We store top_languages as JSONB dicts (lang -> count).
    - This aggregation is done in Python for simplicity; could be optimized with SQL jsonb_each_text later.
    """
    res = await session.execute(select(Profile.top_languages))
    rows = res.all()

    bucket: Dict[str, int] = {}
    for (langs,) in rows:
        if not isinstance(langs, dict):
            continue
        for k, v in langs.items():
            if isinstance(v, int):
                bucket[k] = bucket.get(k, 0) + v

    return [{"name": k, "value": v} for k, v in sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)[:10]]


@app.get(
    "/api/admin/stats",
    tags=["Admin"],
    summary="Admin: global stats & system health",
    response_model=AdminStatsResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_stats(session: AsyncSession = Depends(get_session)) -> AdminStatsResponse:
    """
    Return admin stats.

    Protected:
    - Requires JWT with is_admin=true.

    Includes:
    - DB health via simple queries
    - Global cached language aggregates from Profile.top_languages
    - Search counts
    """
    total_searches = int((await session.execute(select(func.count(ActivityLog.id)))).scalar_one())
    total_profiles = int((await session.execute(select(func.count(Profile.id)))).scalar_one())
    top_languages = await _aggregate_top_languages(session)

    # Rate limit: not persisted yet; returned as nulls (frontend tolerates).
    return AdminStatsResponse(
        rate_limit_remaining=None,
        rate_limit_limit=None,
        rate_limit_reset=None,
        rate_limit_used=None,
        top_languages=top_languages,
        total_cached_profiles=total_profiles,
        total_searches=total_searches,
    )


@app.get(
    "/api/stats",
    tags=["Admin"],
    summary="Protected stats endpoint (alias for admin stats)",
    response_model=AdminStatsResponse,
    dependencies=[Depends(require_admin)],
)
async def protected_stats(session: AsyncSession = Depends(get_session)) -> AdminStatsResponse:
    """Alias to match spec: GET /api/stats (Protected)."""
    return await admin_stats(session=session)
