"""TTL cache for expensive audit fetchers.

Usage:

    from modules.audit_cache import cached_fetch, TTL

    async def fetch_with_cache(domain):
        return await cached_fetch(
            source="dataforseo",
            cache_key=domain.lower(),
            ttl_seconds=TTL.DATAFORSEO,
            fetch_fn=lambda: _actual_expensive_fetch(domain),
        )

Why this module exists:
- DataForSEO calls cost real money and take 30+ seconds. Rerun-on-same-URL
  within 24h should hit cache, not re-bill us.
- Wayback Machine rate-limits aggressively and historical snapshots
  rarely change. 7-day cache is a no-brainer.
- For Autopilot weekly diffs, the FIRST fetch is fresh; subsequent fetches
  for the same competitor (the user's tracked products) within the TTL
  window return instantly.

Failure mode: if Supabase is unavailable, every cached_fetch() reverts
to calling fetch_fn() directly. We NEVER block an audit on a cache lookup.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)


class TTL:
    """Per-source default TTL in seconds. Picked from each source's real-
    world freshness profile, not arbitrary numbers."""
    WAYBACK     = 7  * 24 * 3600   # snapshots are historical — rarely change
    DATAFORSEO  = 24 * 3600        # daily refresh on traffic + keywords
    SEMRUSH     = 24 * 3600        # same shape as DataForSEO
    PRODUCTHUNT = 3  * 24 * 3600   # PH launches don't backfill, only forward
    GITHUB      = 6  * 3600        # stars/forks creep slowly
    BRAVE       = 12 * 3600        # web search results drift slowly
    TINYFISH    = 1  * 3600        # homepage / pricing can change anytime
    HOMEPAGE    = 1  * 3600        # alias for TINYFISH semantics
    SOCIAL      = 4  * 3600        # follower counts drift slowly
    DEFAULT     = 6  * 3600        # fallback if a source isn't explicitly mapped


def _sb():
    """Lazy supabase client. Returns None if unavailable — caller MUST
    handle this by falling back to a direct fetch."""
    try:
        from .supabase_client import get_supabase
        return get_supabase()
    except Exception as e:
        log.debug("Cache disabled — supabase client unavailable: %s", e)
        return None


async def cached_fetch(
    source: str,
    cache_key: str,
    ttl_seconds: int,
    fetch_fn: Callable[[], Awaitable[Any]],
    *,
    force_refresh: bool = False,
) -> Any:
    """Return cached value if fresh, else call fetch_fn() and cache result.

    Args:
        source:       data source label ('dataforseo', 'wayback', 'github', etc.).
                      Used as the partition key + for observability.
        cache_key:    unique key within the source. Usually a normalized URL
                      or domain. Caller should normalize (lowercase, strip
                      trailing slash, etc.) before calling.
        ttl_seconds:  how long to cache. Use TTL.* constants for consistency.
        fetch_fn:     async callable returning the value to cache. Called
                      with no arguments on cache miss / expiry.
        force_refresh: bypass the read; always fetch + write. For manual
                      cache invalidation.

    Returns: whatever fetch_fn returns. Values that aren't JSON-serializable
             are returned uncached (and a warning logged).
    """
    sb = _sb()

    # ── Read path ──────────────────────────────────────────────────────────
    if sb and not force_refresh:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            row = sb.table("audit_cache").select(
                "value, expires_at, hit_count"
            ).eq("source", source).eq("cache_key", cache_key).execute()
            data = (row.data or [])
            if data:
                hit = data[0]
                # Defensive: Supabase returns TZ-aware ISO; PG already
                # filtered, but double-check we didn't race expiry.
                if hit.get("expires_at") and hit["expires_at"] > now_iso:
                    log.info("Cache HIT  %s/%s (ttl_remaining=%s)",
                             source, cache_key[:60],
                             hit.get("expires_at"))
                    # Best-effort hit-count increment (non-blocking on failure).
                    try:
                        sb.table("audit_cache").update({
                            "hit_count": (hit.get("hit_count") or 0) + 1
                        }).eq("source", source).eq("cache_key", cache_key).execute()
                    except Exception:
                        pass
                    return hit["value"]
                else:
                    log.info("Cache EXPIRED %s/%s — refetching", source, cache_key[:60])
        except Exception as e:
            log.warning("Cache read error (%s/%s): %s", source, cache_key[:60], e)
            # Fall through to fetch

    # ── Miss / expired / disabled → live fetch ────────────────────────────
    value = await fetch_fn()

    # ── Write path ────────────────────────────────────────────────────────
    if sb and value is not None:
        try:
            # JSONB column wants a JSON-serializable Python object.
            # We attempt round-trip — if it fails, return uncached.
            json.dumps(value, default=str)
        except (TypeError, ValueError) as e:
            log.warning("Skipping cache write for %s/%s — value not JSON: %s",
                        source, cache_key[:60], e)
            return value

        try:
            expires = (datetime.now(timezone.utc)
                       + timedelta(seconds=ttl_seconds)).isoformat()
            sb.table("audit_cache").upsert({
                "source":      source,
                "cache_key":   cache_key,
                "value":       value,
                "expires_at":  expires,
                "ttl_seconds": ttl_seconds,
                "fetched_at":  datetime.now(timezone.utc).isoformat(),
                "hit_count":   0,
            }, on_conflict="source,cache_key").execute()
            log.info("Cache WRITE %s/%s (ttl=%ds)",
                     source, cache_key[:60], ttl_seconds)
        except Exception as e:
            log.warning("Cache write error (%s/%s): %s", source, cache_key[:60], e)
            # Don't block on cache failure — the fetched value is still
            # what the caller wants.
    return value


async def invalidate(source: str, cache_key: Optional[str] = None) -> int:
    """Delete cached entries. Returns count deleted.

    - invalidate("dataforseo")       — drop EVERY dataforseo row
    - invalidate("dataforseo", "x")   — drop one specific entry
    """
    sb = _sb()
    if not sb:
        return 0
    try:
        q = sb.table("audit_cache").delete().eq("source", source)
        if cache_key is not None:
            q = q.eq("cache_key", cache_key)
        result = q.execute()
        deleted = len(result.data or [])
        log.info("Cache invalidate %s/%s → %d rows", source, cache_key, deleted)
        return deleted
    except Exception as e:
        log.warning("Cache invalidate failed: %s", e)
        return 0


async def stats() -> dict:
    """Quick cache stats for /api/health / admin dashboard. Returns:
        {"sources": {"dataforseo": {"count": 12, "hits": 28}, ...}}
    """
    sb = _sb()
    if not sb:
        return {"sources": {}, "supabase_available": False}
    try:
        rows = sb.table("audit_cache").select(
            "source, hit_count"
        ).execute().data or []
        agg: dict = {}
        for r in rows:
            s = r["source"]
            agg.setdefault(s, {"count": 0, "hits": 0})
            agg[s]["count"] += 1
            agg[s]["hits"] += r.get("hit_count") or 0
        return {"sources": agg, "supabase_available": True}
    except Exception as e:
        return {"sources": {}, "error": str(e)[:200]}
