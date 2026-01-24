import asyncio
import os
from typing import Any, Dict, List, Tuple

import httpx


GITHUB_API = "https://api.github.com"


# PUBLIC_INTERFACE
async def fetch_user_and_repos(username: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Fetch GitHub user profile + repos asynchronously.

    Returns:
      (user_json, repos_json_list, rate_limit_info)

    Security:
      - Uses GITHUB_TOKEN from environment for Authorization header.
      - Never expose this token to the frontend.
    """
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-insights-dashboard",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
        user_req = client.get(f"{GITHUB_API}/users/{username}")
        repos_req = client.get(
            f"{GITHUB_API}/users/{username}/repos",
            params={"per_page": 100, "sort": "updated"},
        )
        user_res, repos_res = await asyncio.gather(user_req, repos_req)

        # Rate limit headers are present even on many errors
        rate_info = {
            "x-ratelimit-remaining": user_res.headers.get("x-ratelimit-remaining")
            or repos_res.headers.get("x-ratelimit-remaining"),
            "x-ratelimit-limit": user_res.headers.get("x-ratelimit-limit")
            or repos_res.headers.get("x-ratelimit-limit"),
            "x-ratelimit-reset": user_res.headers.get("x-ratelimit-reset")
            or repos_res.headers.get("x-ratelimit-reset"),
        }

        if user_res.status_code == 404:
            raise httpx.HTTPStatusError("User not found", request=user_res.request, response=user_res)
        user_res.raise_for_status()
        repos_res.raise_for_status()

        return user_res.json(), repos_res.json(), rate_info
