"""UnifAPI client — unified public-data API (api.unifapi.com).

Iris 2026-06-23: we picked up UnifAPI to (a) replace the SerpAPI-scraped
Reddit path which has produced two None-handling crashes in 24 hours,
and (b) give the social-media discoverer a vendor-independent fallback
when TwitterAPI.io or Apify is degraded.

The catalog covers Reddit, X, YouTube, Instagram, TikTok, LinkedIn,
Threads, plus SEO/GEO (paid premium). Pricing is per-record at
$0.001/credit (standard) — at analook's current scale (~100 audits/mo,
~3 Reddit lookups + ~3 social lookups per audit) total spend is well
under $1/month, much cheaper than the Apify $29 + TwitterAPI.io flat
contracts when accessed sporadically.

Key things to know:
- One bearer key, header `Authorization: Bearer <key>`
- Every endpoint returns {request_id, data, billing} envelope
- billing.balance_remaining is exposed so callers can monitor health
- GEO mentions endpoints are 500 credits/call → caller MUST gate by plan
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

_BASE = "https://api.unifapi.com"
_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=8.0, pool=8.0)


def _key() -> str:
    return (os.environ.get("UNIFAPI_KEY") or os.environ.get("UNIF_API_KEY") or "").strip()


def _has_key() -> bool:
    return bool(_key())


async def _get(path: str, params: Optional[dict] = None) -> dict:
    """Run a GET; return parsed JSON or {"_error": "..."} on failure.

    Never raises — every caller wants to fall back gracefully when
    UnifAPI is missing/billed-out/down.
    """
    key = _key()
    if not key:
        return {"_error": "no_key"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.get(
                _BASE + path,
                params=params or {},
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
            if r.status_code == 200:
                return r.json() or {}
            if r.status_code == 402:
                log.warning("UnifAPI 402 (insufficient credits) on %s", path)
                return {"_error": "insufficient_credits", "_status": 402}
            if r.status_code in (401, 403):
                log.warning("UnifAPI auth fail %s on %s", r.status_code, path)
                return {"_error": "auth_fail", "_status": r.status_code}
            if r.status_code == 404:
                # 404 is normal — e.g. sub/user doesn't exist. Not an error.
                return {"_error": "not_found", "_status": 404}
            log.warning("UnifAPI HTTP %s on %s: %s", r.status_code, path, r.text[:160])
            return {"_error": f"http_{r.status_code}", "_status": r.status_code}
    except Exception as e:
        log.warning("UnifAPI exception on %s: %s", path, str(e)[:160])
        return {"_error": "exception", "_message": str(e)[:200]}


# ─── Reddit ──────────────────────────────────────────────────────────────────


async def get_subreddit(name: str) -> dict:
    """GET /reddit/subreddits/{name} — clean structured subreddit data.

    Returns the inner `data` dict on success, or {} on miss/error. The
    typical schema:
        {
          "id": "saas",
          "name": "SaaS",
          "prefixed_name": "r/SaaS",
          "title": "...",
          "description": "...",   # always present, may be empty string
          "subscribers_count": 731275,   # always int, never None
          "active_count": 0,             # always int
          "is_nsfw": false
        }
    """
    if not name:
        return {}
    resp = await _get(f"/reddit/subreddits/{name}")
    if resp.get("_error"):
        return {}
    return resp.get("data") or {}


async def get_reddit_post(post_id: str) -> dict:
    """GET /reddit/posts/{id} — fetch one Reddit post by id (the 6-char base36)."""
    if not post_id:
        return {}
    resp = await _get(f"/reddit/posts/{post_id}")
    if resp.get("_error"):
        return {}
    return resp.get("data") or {}


async def get_reddit_user(username: str) -> dict:
    """GET /reddit/users/{username} — Reddit profile (karma, account age)."""
    if not username:
        return {}
    resp = await _get(f"/reddit/users/{username}")
    if resp.get("_error"):
        return {}
    return resp.get("data") or {}


# ─── X / Twitter ─────────────────────────────────────────────────────────────


async def get_x_user_by_username(username: str) -> dict:
    """GET /x/users/by/username/{username} — full X profile by handle.

    Returns the typical schema:
        {
          "id": "3396007690",
          "name": "...",
          "username": "...",
          "description": "...",
          "location": "...",
          "url": "...",
          # follower/following counts under public_metrics depending on endpoint
        }
    """
    if not username:
        return {}
    handle = username.lstrip("@")
    resp = await _get(f"/x/users/by/username/{handle}")
    if resp.get("_error"):
        return {}
    return resp.get("data") or {}


async def search_x_recent_tweets(query: str, max_results: int = 10) -> list:
    """GET /x/tweets/search/recent — search recent tweets matching query."""
    if not query:
        return []
    resp = await _get(
        "/x/tweets/search/recent",
        params={"q": query, "max_results": max_results},
    )
    if resp.get("_error"):
        return []
    data = resp.get("data") or {}
    # API returns either a list or a {"tweets": [...]} envelope
    if isinstance(data, list):
        return data
    return data.get("tweets") or data.get("results") or []


# ─── YouTube ─────────────────────────────────────────────────────────────────


async def get_youtube_channel(channel_id: str) -> dict:
    """GET /youtube/channels/{channel_id}. channel_id is the UC… string."""
    if not channel_id:
        return {}
    resp = await _get(f"/youtube/channels/{channel_id}")
    if resp.get("_error"):
        return {}
    return resp.get("data") or {}


# ─── LinkedIn / Instagram / TikTok (uniform pattern) ─────────────────────────


async def get_linkedin_profile(slug: str) -> dict:
    """GET /linkedin/people/{slug} — fall back to /linkedin/profiles/{slug}
    on a 404; UnifAPI's path naming has varied across versions.
    """
    if not slug:
        return {}
    for path in (f"/linkedin/people/{slug}", f"/linkedin/profiles/{slug}"):
        resp = await _get(path)
        if not resp.get("_error"):
            return resp.get("data") or {}
        if resp.get("_status") == 404:
            continue
        # Auth fail / billing → stop trying alternative paths
        return {}
    return {}


async def get_instagram_profile(username: str) -> dict:
    if not username:
        return {}
    handle = username.lstrip("@")
    resp = await _get(f"/instagram/users/{handle}")
    if resp.get("_error"):
        return {}
    return resp.get("data") or {}


async def get_tiktok_profile(username: str) -> dict:
    if not username:
        return {}
    handle = username.lstrip("@")
    resp = await _get(f"/tiktok/users/{handle}")
    if resp.get("_error"):
        return {}
    return resp.get("data") or {}


# ─── Health / balance probe (used by /api/admin/api-balances) ────────────────


async def probe_balance() -> dict:
    """Return {status, balance_remaining, note} by making the cheapest
    possible call (the trending searches endpoint costs 1 credit, but
    we can also just call a known sub for the same price).

    Used by api_balances.check_all() — same shape as other providers.
    """
    if not _has_key():
        return {"provider": "UnifAPI", "status": "missing", "note": "UNIFAPI_KEY env not set"}
    resp = await _get("/reddit/subreddits/python")
    if resp.get("_error") == "auth_fail":
        return {"provider": "UnifAPI", "status": "error", "note": "Key invalid (401/403)"}
    if resp.get("_error") == "insufficient_credits":
        return {"provider": "UnifAPI", "status": "exhausted", "note": "0 credits left — top up at unifapi.com"}
    if resp.get("_error"):
        return {"provider": "UnifAPI", "status": "unknown",
                "note": f"Probe call failed: {resp.get('_error')}"}
    billing = resp.get("billing") or {}
    bal_credits = billing.get("balance_remaining")
    bal_usd = (bal_credits * 0.001) if isinstance(bal_credits, (int, float)) else None
    return {
        "provider": "UnifAPI",
        "status":   "ok",
        "balance_usd": bal_usd,
        "credits_remaining": bal_credits,
        "note": f"{bal_credits} credits remaining (1 credit = \\$0.001)",
    }
