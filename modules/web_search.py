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
    """Brave Search API — returns list of {title, url, description}"""
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                params={"q": query, "count": count},
            )
        if resp.status_code != 200:
            return []
        results = resp.json().get("web", {}).get("results", [])
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")} for r in results]
    except Exception:
        return []


async def brave_find_twitter(brand: str, product_name: str) -> str | None:
    """Use Brave Search to find the official Twitter/X handle for a product."""
    _skip = {"intent", "search", "home", "share", "hashtag", "explore", "i", "compose", "messages"}
    for query in [f'"{product_name}" site:x.com OR site:twitter.com', f'"{brand}" official twitter account']:
        results = await brave_search(query, count=5)
        found = []
        for r in results:
            for url_field in [r.get("url", ""), r.get("description", "")]:
                m = _TWITTER_RE.search(url_field)
                if m and m.group(1).lower() not in _skip:
                    found.append(m.group(1))
        if found:
            from collections import Counter
            return Counter(found).most_common(1)[0][0]
    return None


async def brave_find_ph_slug(brand: str, product_name: str) -> str | None:
    """Use Brave Search to find the Product Hunt product slug."""
    for query in [f'"{product_name}" site:producthunt.com', f'"{brand}" producthunt.com/products']:
        results = await brave_search(query, count=5)
        for r in results:
            url = r.get("url", "")
            m = _PH_PRODUCT_RE.search(url)
            if m:
                slug = m.group(1)
                if slug not in {"coming-soon", "login", "posts", "leaderboard"}:
                    return slug
            m2 = _PH_POST_RE.search(url)
            if m2:
                return m2.group(1)
    return None


async def brave_find_social(brand: str, product_name: str) -> dict:
    """Use Brave Search to find official social media handles for multiple platforms."""
    handles = {}
    tasks = []
    import asyncio
    # Twitter
    twitter_task = asyncio.create_task(brave_find_twitter(brand, product_name))
    # Platform-specific searches
    platform_tasks = {}
    for platform, regex in _SOCIAL_PLATFORM_RE.items():
        async def _find(p=platform, rx=regex):
            results = await brave_search(f'"{product_name}" site:{p}.com', count=3)
            _skip_yt = {"watch", "results", "channel", "user", "playlist", "shorts"}
            for r in results:
                m = rx.search(r.get("url", ""))
                if m:
                    h = m.group(1)
                    if p == "youtube" and h.lower() in _skip_yt:
                        continue
                    return h
            return None
        platform_tasks[platform] = asyncio.create_task(_find())

    twitter_handle = await twitter_task
    if twitter_handle:
        handles["twitter"] = {"handle": twitter_handle, "url": f"https://x.com/{twitter_handle}", "source": "brave"}

    for platform, task in platform_tasks.items():
        h = await task
        if h:
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
