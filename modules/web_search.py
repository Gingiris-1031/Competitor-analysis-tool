"""联网搜索模块 — DataForSEO SERP API + Brave Search API + 网页抓取"""
import httpx
import os
import re
from bs4 import BeautifulSoup

_TWITTER_RE = re.compile(r'(?:twitter\.com|x\.com)/@?([\w]{1,30})(?:[/?]|$)', re.I)
_PH_PRODUCT_RE = re.compile(r'producthunt\.com/products/([\w-]+)', re.I)
_PH_POST_RE = re.compile(r'producthunt\.com/posts/([\w-]+)', re.I)
_SOCIAL_PLATFORM_RE = {
    "youtube": re.compile(r'youtube\.com/(?:@|channel/|c/)?([\w-]{2,40})(?:[/?]|$)', re.I),
    "instagram": re.compile(r'instagram\.com/@?([\w.]{1,30})(?:[/?]|$)', re.I),
    "linkedin": re.compile(r'linkedin\.com/company/([\w-]{2,50})(?:[/?]|$)', re.I),
}


async def brave_search(query: str, count: int = 5) -> list:
    """Brave Search API — returns list of {title, url, description}.
    Includes retry with exponential backoff for 429/5xx errors."""
    import asyncio as _aio
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        return []
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                    params={"q": query, "count": count},
                )
            if resp.status_code == 200:
                results = resp.json().get("web", {}).get("results", [])
                return [{"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")} for r in results]
            if resp.status_code in (429, 500, 502, 503) and attempt < 2:
                await _aio.sleep(2 ** attempt)
                continue
            return []
        except Exception:
            if attempt < 2:
                await _aio.sleep(1)
                continue
            return []
    return []


async def brave_find_twitter(brand: str, product_name: str, domain: str = "") -> str | None:
    """Use Brave Search to find the official Twitter/X handle for a product."""
    _skip = {"intent", "search", "home", "share", "hashtag", "explore", "i", "compose", "messages"}
    # Build queries from most specific to least — use domain as anchor when available
    queries = []
    if domain:
        queries.append(f'"{domain}" site:x.com OR site:twitter.com')
        queries.append(f'site:twitter.com "{domain}"')
    queries.append(f'"{brand}" official twitter OR x.com')
    for query in queries:
        results = await brave_search(query, count=5)
        found = []
        for r in results:
            for url_field in [r.get("url", ""), r.get("description", ""), r.get("title", "")]:
                m = _TWITTER_RE.search(url_field)
                if m and m.group(1).lower() not in _skip:
                    found.append(m.group(1))
        if found:
            from collections import Counter
            return Counter(found).most_common(1)[0][0]
    return None


async def brave_find_ph_slugs(brand: str, product_name: str, domain: str = "", limit: int = 5) -> list:
    """Use Brave Search to find multiple Product Hunt slug candidates (fuzzy).

    Returns up to `limit` unique slugs ordered by appearance across queries.
    Broader than `brave_find_ph_slug` — good for fuzzy fallback when the
    canonical slug differs from brand/domain (e.g. "ChatGPT" → "chatgpt-4").
    """
    _skip_slugs = {"coming-soon", "login", "posts", "leaderboard", "upcoming", "newsletter", "launch"}
    queries = []
    if domain:
        queries.append(f'"{domain}" site:producthunt.com')
    queries.append(f'"{brand}" site:producthunt.com/products')
    queries.append(f'"{product_name}" site:producthunt.com/products')
    queries.append(f'"{brand}" producthunt launch')
    # Fuzzy: also search brand+common suffix patterns
    queries.append(f'{brand} producthunt ai')
    found: list = []
    seen: set = set()
    for query in queries:
        if len(found) >= limit:
            break
        try:
            results = await brave_search(query, count=5)
        except Exception:
            continue
        for r in results:
            url = r.get("url", "")
            for regex in (_PH_PRODUCT_RE, _PH_POST_RE):
                m = regex.search(url)
                if m:
                    slug = m.group(1)
                    if slug and slug not in _skip_slugs and slug not in seen:
                        seen.add(slug)
                        found.append(slug)
                        if len(found) >= limit:
                            return found
    return found


async def brave_find_ph_slug(brand: str, product_name: str, domain: str = "") -> str | None:
    """Backward-compatible wrapper — returns first slug from brave_find_ph_slugs."""
    slugs = await brave_find_ph_slugs(brand, product_name, domain=domain, limit=1)
    return slugs[0] if slugs else None


async def brave_find_social(brand: str, product_name: str, domain: str = "") -> dict:
    """Use Brave Search to find official social media handles for multiple platforms."""
    import asyncio

    async def _find_platform(p: str, rx) -> str | None:
        _skip_yt = {"watch", "results", "channel", "user", "playlist", "shorts", "feed"}
        q = f'"{domain}" site:{p}.com' if domain else f'"{brand}" site:{p}.com'
        results = await brave_search(q, count=3)
        for r in results:
            m = rx.search(r.get("url", ""))
            if m:
                h = m.group(1)
                if p == "youtube" and h.lower() in _skip_yt:
                    continue
                return h
        return None

    # Run Twitter + other platforms concurrently
    twitter_coro = brave_find_twitter(brand, product_name, domain)
    platform_coros = {p: _find_platform(p, rx) for p, rx in _SOCIAL_PLATFORM_RE.items()}
    all_coros = [twitter_coro] + list(platform_coros.values())
    results_all = await asyncio.gather(*all_coros, return_exceptions=True)

    handles = {}
    twitter_handle = results_all[0] if not isinstance(results_all[0], Exception) else None
    if twitter_handle:
        handles["twitter"] = {"handle": twitter_handle, "url": f"https://x.com/{twitter_handle}", "source": "brave"}

    for i, (platform, _) in enumerate(platform_coros.items()):
        h = results_all[i + 1]
        if h and not isinstance(h, Exception):
            handles[platform] = {"handle": h, "url": f"https://{platform}.com/{h}", "source": "brave"}

    return handles


async def search_and_summarize(query: str, num_results: int = 8) -> dict:
    """Google 搜索 + 抓取 Top 结果内容"""
    # Step 1: Google search via DataForSEO
    results = await _google_search(query, num_results)
    if not results.get("items"):
        return {"success": False, "error": "搜索无结果", "query": query}

    # Step 2: Fetch top 3 result pages for content
    pages = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for item in results["items"][:4]:
            url = item.get("url", "")
            if not url or any(skip in url for skip in ["youtube.com/watch", ".pdf", ".png", ".jpg"]):
                continue
            try:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # Remove nav, footer, scripts
                    for tag in soup.find_all(["nav", "footer", "script", "style", "header"]):
                        tag.decompose()
                    text = soup.get_text(" ", strip=True)[:3000]
                    pages.append({
                        "title": item.get("title", ""),
                        "url": url,
                        "snippet": item.get("description", ""),
                        "content": text,
                    })
            except Exception:
                pages.append({
                    "title": item.get("title", ""),
                    "url": url,
                    "snippet": item.get("description", ""),
                    "content": "",
                })
            if len(pages) >= 3:
                break

    return {
        "success": True,
        "query": query,
        "total_results": results.get("total", 0),
        "search_results": results["items"][:8],
        "fetched_pages": pages,
    }


async def _google_search(query: str, limit: int = 8) -> dict:
    """DataForSEO SERP API"""
    b64 = os.environ.get("DATAFORSEO_B64", "").strip()
    if not b64:
        try:
            b64 = open(os.path.expanduser("~/.cola/secrets/dataforseo_b64")).read().strip()
        except FileNotFoundError:
            pass
    if not b64:
        return {"items": [], "error": "No DataForSEO credentials"}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.dataforseo.com/v3/serp/google/organic/live/regular",
            headers={"Authorization": f"Basic {b64}", "Content-Type": "application/json"},
            json=[{"keyword": query, "location_code": 2840, "language_code": "en", "depth": limit}],
        )
    
    data = resp.json()
    task = data.get("tasks", [{}])[0]
    items = []
    if task.get("result"):
        for r in task["result"][0].get("items", []):
            if r.get("type") == "organic":
                items.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "description": r.get("description", ""),
                    "position": r.get("rank_absolute", 0),
                })
    
    return {
        "items": items,
        "total": task.get("result", [{}])[0].get("se_results_count", 0) if task.get("result") else 0,
        "cost": data.get("cost", 0),
    }
