"""API key balance / health checker.

Queries each third-party provider's balance or auth endpoint and returns
a normalized {provider: {status, balance_usd, balance_native, limit, note}}
dict. Used by /api/admin/api-balances so Iris can see who needs topping up
in one place.

Conservative timeouts (8s each) and parallel via asyncio.gather so the
whole report comes back in under 10s even if half the providers are slow.

Providers covered:
  - DeepSeek (chat LLM) — has /user/balance endpoint
  - OpenRouter (LLM fallback) — /auth/key returns balance + limit
  - DataForSEO (SEO data) — /v3/appendix/user_data shows balance
  - Apify (web scraping) — /v2/users/me with current plan + usage
  - Brave Search — no public balance, returns "check dashboard"
  - TinyFish (web fetch) — no public balance, returns "check dashboard"
  - Resend (email) — no balance API, returns "free tier 3000/mo, check dashboard"
  - ProductHunt — GraphQL, no balance API
  - Polar — usage-based, no balance
  - GitHub — rate limit endpoint
  - SerpAPI — /account?api_key= returns plan + remaining
  - Caravo — TBD
"""
import asyncio
import logging
import os
from base64 import b64encode
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 8.0


def _key(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _missing(provider: str) -> dict:
    return {
        "provider": provider,
        "status":   "missing",
        "note":     "Env var not set",
    }


# ─── Per-provider checkers ───────────────────────────────────────────────────


async def _deepseek(c: httpx.AsyncClient) -> dict:
    key = _key("DEEPSEEK_API_KEY")
    if not key:
        return _missing("DeepSeek")
    try:
        r = await c.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        )
        if r.status_code != 200:
            return {"provider": "DeepSeek", "status": "error", "note": f"HTTP {r.status_code}: {r.text[:120]}"}
        data = r.json()
        # Response: {is_available: bool, balance_infos:[{currency, total_balance, granted_balance, topped_up_balance}]}
        infos = data.get("balance_infos") or []
        usd_info = next((i for i in infos if i.get("currency") == "USD"), infos[0] if infos else {})
        total = float(usd_info.get("total_balance") or 0)
        return {
            "provider":      "DeepSeek",
            "status":        "ok" if data.get("is_available") else "low",
            "balance_usd":   total,
            "currency":      usd_info.get("currency", "USD"),
            "note":          f"granted={usd_info.get('granted_balance')} topped_up={usd_info.get('topped_up_balance')}",
        }
    except Exception as e:
        return {"provider": "DeepSeek", "status": "error", "note": str(e)[:120]}


async def _openrouter(c: httpx.AsyncClient) -> dict:
    key = _key("OPENROUTER_API_KEY")
    if not key:
        return _missing("OpenRouter")
    try:
        r = await c.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {key}"},
        )
        if r.status_code != 200:
            return {"provider": "OpenRouter", "status": "error", "note": f"HTTP {r.status_code}: {r.text[:120]}"}
        data = (r.json() or {}).get("data") or {}
        usage = float(data.get("usage") or 0)
        limit = data.get("limit")
        balance = (float(limit) - usage) if limit is not None else None
        return {
            "provider":     "OpenRouter",
            "status":       "ok",
            "balance_usd":  balance,
            "usage_usd":    usage,
            "limit_usd":    limit,
            "note":         data.get("label") or "",
        }
    except Exception as e:
        return {"provider": "OpenRouter", "status": "error", "note": str(e)[:120]}


async def _dataforseo(c: httpx.AsyncClient) -> dict:
    b64 = _key("DATAFORSEO_B64")
    if not b64:
        return _missing("DataForSEO")
    try:
        r = await c.get(
            "https://api.dataforseo.com/v3/appendix/user_data",
            headers={"Authorization": f"Basic {b64}", "Accept": "application/json"},
        )
        if r.status_code != 200:
            return {"provider": "DataForSEO", "status": "error", "note": f"HTTP {r.status_code}: {r.text[:120]}"}
        data = r.json() or {}
        tasks = (data.get("tasks") or [{}])[0]
        result = (tasks.get("result") or [{}])[0]
        money = result.get("money") or {}
        return {
            "provider":     "DataForSEO",
            "status":       "ok" if (money.get("balance") or 0) > 5 else "low",
            "balance_usd":  money.get("balance"),
            "currency":     money.get("currency", "USD"),
            "note":         f"login={result.get('login')} rates={list((result.get('rates') or {}).keys())[:3]}",
        }
    except Exception as e:
        return {"provider": "DataForSEO", "status": "error", "note": str(e)[:120]}


async def _apify(c: httpx.AsyncClient) -> dict:
    tok = _key("APIFY_API_TOKEN")
    if not tok:
        return _missing("Apify")
    try:
        r = await c.get(
            f"https://api.apify.com/v2/users/me?token={tok}",
        )
        if r.status_code != 200:
            return {"provider": "Apify", "status": "error", "note": f"HTTP {r.status_code}"}
        data = (r.json() or {}).get("data") or {}
        plan = data.get("plan") or {}
        usage = data.get("usage") or {}
        return {
            "provider":     "Apify",
            "status":       "ok",
            "balance_usd":  plan.get("monthlyUsageCreditsUsd"),
            "note":         f"plan={plan.get('id')} mo_usage_usd={usage.get('monthlyUsageUsd')}",
        }
    except Exception as e:
        return {"provider": "Apify", "status": "error", "note": str(e)[:120]}


async def _brave(c: httpx.AsyncClient) -> dict:
    key = _key("BRAVE_SEARCH_API_KEY")
    if not key:
        return _missing("Brave Search")
    # No public balance endpoint. Test with a 1-result call to confirm key works.
    try:
        r = await c.get(
            "https://api.search.brave.com/res/v1/web/search?q=test&count=1",
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
        if r.status_code == 200:
            return {"provider": "Brave Search", "status": "ok", "note": "Key valid; balance not exposed via API. Check api.search.brave.com dashboard."}
        if r.status_code == 401:
            return {"provider": "Brave Search", "status": "error", "note": "Key invalid (401)"}
        if r.status_code == 429:
            return {"provider": "Brave Search", "status": "low", "note": "Rate limited or quota exhausted (429)"}
        return {"provider": "Brave Search", "status": "error", "note": f"HTTP {r.status_code}: {r.text[:120]}"}
    except Exception as e:
        return {"provider": "Brave Search", "status": "error", "note": str(e)[:120]}


async def _tinyfish(c: httpx.AsyncClient) -> dict:
    key = _key("TINYFISH_API_KEY")
    if not key:
        return _missing("TinyFish")
    # Try a tiny fetch to confirm liveness. TinyFish doesn't publish a balance
    # endpoint we know of; this just confirms the key still works.
    try:
        r = await c.get(
            "https://api.tinyfish.io/v1/health",
            headers={"Authorization": f"Bearer {key}"},
        )
        if r.status_code in (200, 204):
            return {"provider": "TinyFish", "status": "ok", "note": "Key valid. Balance not exposed via API; check tinyfish.io dashboard."}
        if r.status_code == 401:
            return {"provider": "TinyFish", "status": "error", "note": "Key invalid (401)"}
        if r.status_code == 402:
            return {"provider": "TinyFish", "status": "exhausted", "note": "Out of credits (402)"}
        return {"provider": "TinyFish", "status": "unknown", "note": f"HTTP {r.status_code}: {r.text[:120]}"}
    except Exception as e:
        return {"provider": "TinyFish", "status": "error", "note": str(e)[:120]}


async def _resend(c: httpx.AsyncClient) -> dict:
    key = _key("RESEND_API_KEY")
    if not key:
        return _missing("Resend")
    try:
        r = await c.get(
            "https://api.resend.com/api-keys",
            headers={"Authorization": f"Bearer {key}"},
        )
        if r.status_code == 200:
            return {"provider": "Resend", "status": "ok", "note": "Key valid. Free tier = 3000 emails/mo + 100/day. Usage at resend.com/emails."}
        return {"provider": "Resend", "status": "error", "note": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"provider": "Resend", "status": "error", "note": str(e)[:120]}


async def _serpapi(c: httpx.AsyncClient) -> dict:
    key = _key("SERPAPI_KEY")
    if not key:
        return _missing("SerpAPI")
    try:
        r = await c.get(f"https://serpapi.com/account?api_key={key}")
        if r.status_code != 200:
            return {"provider": "SerpAPI", "status": "error", "note": f"HTTP {r.status_code}"}
        data = r.json() or {}
        used = data.get("this_month_usage") or 0
        plan_limit = data.get("plan_searches_left")
        return {
            "provider":     "SerpAPI",
            "status":       "ok" if (plan_limit or 1) > 100 else "low",
            "searches_left":plan_limit,
            "used_month":   used,
            "note":         f"plan={data.get('plan_name')}",
        }
    except Exception as e:
        return {"provider": "SerpAPI", "status": "error", "note": str(e)[:120]}


async def _github(c: httpx.AsyncClient) -> dict:
    tok = _key("GITHUB_TOKEN")
    if not tok:
        return _missing("GitHub PAT")
    try:
        r = await c.get(
            "https://api.github.com/rate_limit",
            headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"},
        )
        if r.status_code != 200:
            return {"provider": "GitHub PAT", "status": "error", "note": f"HTTP {r.status_code}"}
        rate = (r.json() or {}).get("resources", {}).get("core", {})
        return {
            "provider":     "GitHub PAT",
            "status":       "ok",
            "rate_remain":  rate.get("remaining"),
            "rate_limit":   rate.get("limit"),
            "note":         "Free. Rate limit resets hourly.",
        }
    except Exception as e:
        return {"provider": "GitHub PAT", "status": "error", "note": str(e)[:120]}


async def _producthunt(c: httpx.AsyncClient) -> dict:
    tok = _key("PRODUCTHUNT_TOKEN")
    if not tok:
        return _missing("ProductHunt")
    try:
        # Minimal GraphQL viewer query.
        r = await c.post(
            "https://api.producthunt.com/v2/api/graphql",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={"query": "{ viewer { user { id name } } }"},
        )
        if r.status_code == 200 and not (r.json() or {}).get("errors"):
            return {"provider": "ProductHunt", "status": "ok", "note": "Free. Rate-limit 1000 calls/15min."}
        return {"provider": "ProductHunt", "status": "error", "note": f"HTTP {r.status_code}: {r.text[:120]}"}
    except Exception as e:
        return {"provider": "ProductHunt", "status": "error", "note": str(e)[:120]}


async def _twitterapi_io(c: httpx.AsyncClient) -> dict:
    key = _key("TWITTERAPI_IO_KEY") or _key("TWITTER_API_IO_KEY")
    if not key:
        return _missing("TwitterAPI.io")
    try:
        # Cheap liveness check: user info for the public @x account
        r = await c.get(
            "https://api.twitterapi.io/twitter/user/info",
            params={"userName": "x"},
            headers={"x-api-key": key},
        )
        if r.status_code == 200:
            return {
                "provider": "TwitterAPI.io",
                "status":   "ok",
                "note":     "Key valid. KOL discovery fallback. Check usage at twitterapi.io dashboard.",
            }
        if r.status_code in (401, 403):
            return {"provider": "TwitterAPI.io", "status": "error", "note": f"Auth fail HTTP {r.status_code}"}
        if r.status_code == 402:
            return {"provider": "TwitterAPI.io", "status": "exhausted", "note": "Credits depleted (402)"}
        return {"provider": "TwitterAPI.io", "status": "unknown", "note": f"HTTP {r.status_code}: {r.text[:120]}"}
    except Exception as e:
        return {"provider": "TwitterAPI.io", "status": "error", "note": str(e)[:120]}


async def _polar(c: httpx.AsyncClient) -> dict:
    tok = _key("POLAR_ACCESS_TOKEN")
    if not tok:
        return _missing("Polar")
    try:
        r = await c.get(
            "https://api.polar.sh/v1/users/me",
            headers={"Authorization": f"Bearer {tok}"},
        )
        if r.status_code == 200:
            return {"provider": "Polar", "status": "ok", "note": "Subscription-based revenue; no key balance. Check polar.sh/dashboard."}
        return {"provider": "Polar", "status": "error", "note": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"provider": "Polar", "status": "error", "note": str(e)[:120]}


# ─── Aggregator ──────────────────────────────────────────────────────────────


async def check_all() -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        results = await asyncio.gather(
            _deepseek(c),
            _openrouter(c),
            _dataforseo(c),
            _apify(c),
            _brave(c),
            _tinyfish(c),
            _resend(c),
            _serpapi(c),
            _github(c),
            _producthunt(c),
            _twitterapi_io(c),
            _polar(c),
            return_exceptions=True,
        )
    out = []
    for r in results:
        if isinstance(r, Exception):
            out.append({"provider": "?", "status": "exception", "note": str(r)[:200]})
        else:
            out.append(r)

    # Summary roll-up: which need action?
    needs_topup = [r["provider"] for r in out if r.get("status") in ("low", "exhausted")]
    missing     = [r["provider"] for r in out if r.get("status") == "missing"]
    errors      = [r["provider"] for r in out if r.get("status") == "error"]

    return {
        "checked_at":    None,  # caller stamps timestamp
        "providers":     out,
        "summary": {
            "needs_topup": needs_topup,
            "missing":     missing,
            "errors":      errors,
            "ok_count":    sum(1 for r in out if r.get("status") == "ok"),
            "total":       len(out),
        },
    }
