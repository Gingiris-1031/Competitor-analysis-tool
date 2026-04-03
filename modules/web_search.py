"""联网搜索模块 — DataForSEO SERP API + 网页抓取"""
import httpx
import os
from bs4 import BeautifulSoup


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
