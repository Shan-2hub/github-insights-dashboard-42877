from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ActivityLog, Profile
from src.github.client import fetch_user_and_repos


CACHE_TTL = timedelta(hours=24)


def _compute_total_stars(repos: list[dict]) -> int:
    return int(sum((r.get("stargazers_count") or 0) for r in repos))


def _compute_top_languages(repos: list[dict]) -> Dict[str, int]:
    # Basic language count across repos (placeholder for deeper per-language bytes aggregation).
    c: Counter[str] = Counter()
    for r in repos:
        lang = r.get("language")
        if lang:
            c[lang] += 1
    return dict(c.most_common(12))


# PUBLIC_INTERFACE
async def get_profile_insights(
    session: AsyncSession, username: str
) -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """
    Get insights for a username.

    Behavior:
      - If cached profile exists and last_updated < 24h old, return cached payload.
      - Otherwise fetch from GitHub (async), compute fields, upsert DB record.
      - Always write an ActivityLog row.

    Returns:
      (payload, rate_limit_info)
    """
    started = datetime.utcnow()
    normalized = username.strip().lower()

    cached: Optional[Profile] = None
    res = await session.execute(select(Profile).where(Profile.username == normalized))
    cached = res.scalar_one_or_none()

    if cached and (datetime.utcnow() - cached.last_updated) < CACHE_TTL:
        latency = int((datetime.utcnow() - started).total_seconds() * 1000)
        session.add(ActivityLog(username_searched=normalized, request_latency_ms=latency))
        await session.commit()
        return (
            {
                "source": "cache",
                "profile": cached.model_dump(),
            },
            {"x-ratelimit-remaining": None, "x-ratelimit-limit": None, "x-ratelimit-reset": None},
        )

    try:
        user_json, repos_json, rate_info = await fetch_user_and_repos(normalized)
    except httpx.HTTPStatusError:
        latency = int((datetime.utcnow() - started).total_seconds() * 1000)
        session.add(ActivityLog(username_searched=normalized, request_latency_ms=latency))
        await session.commit()
        raise

    total_stars = _compute_total_stars(repos_json)
    top_languages = _compute_top_languages(repos_json)

    if cached is None:
        cached = Profile(username=normalized)

    cached.full_name = user_json.get("name")
    cached.bio = user_json.get("bio")
    cached.avatar_url = user_json.get("avatar_url")
    cached.followers = int(user_json.get("followers") or 0)
    cached.following = int(user_json.get("following") or 0)
    cached.public_repos = int(user_json.get("public_repos") or 0)
    cached.total_stars = int(total_stars)
    cached.top_languages = top_languages
    cached.last_updated = datetime.utcnow()

    session.add(cached)

    latency = int((datetime.utcnow() - started).total_seconds() * 1000)
    session.add(ActivityLog(username_searched=normalized, request_latency_ms=latency))
    await session.commit()

    return (
        {
            "source": "github",
            "profile": cached.model_dump(),
            "repos_count": len(repos_json),
        },
        rate_info,
    )
