"""PR & 媒体曝光分析模块 — HackerNews + Google News + Brave Press Search"""
import httpx
import os
import re
import asyncio


def _extract_brand(domain: str) -> str:
    brand = re.sub(r'^www\.', '', domain.lower().strip())
    return re.sub(r'\.[a-z]{2,6}$', '', brand)


async def analyze_pr_news(domain: str, product_name: str) -> dict:
    """分析产品在 HackerNews、Google News、主流科技媒体的曝光记录"""
    brand = _extract_brand(domain)

    hn_task    = _fetch_hn(product_name, brand)
    news_task  = _fetch_google_news(product_name)
    brave_task = _fetch_brave_press(product_name, brand, domain)

    results = await asyncio.gather(hn_task, news_task, brave_task, return_exceptions=True)

    hn_posts       = results[0] if isinstance(results[0], list) else []
    news_articles  = results[1] if isinstance(results[1], list) else []
    press_mentions = results[2] if isinstance(results[2], list) else []

    all_mentions = _merge_mentions(hn_posts, news_articles, press_mentions)
    insights     = _gen_insights(hn_posts, news_articles, press_mentions)

    return {
        "found":          bool(all_mentions),
        "total_mentions": len(all_mentions),
        "hn_posts":       hn_posts[:6],
        "news_articles":  news_articles[:6],
        "press_mentions": press_mentions[:6],
        "top_mentions":   all_mentions[:10],
        "insights":       insights,
    }


async def _fetch_hn(product_name: str, brand: str) -> list:
    """HackerNews Algolia API — 免费无需 API key"""
    results = []
    seen_ids = set()
    queries = list(dict.fromkeys([product_name, brand]))  # deduplicate

    async with httpx.AsyncClient(timeout=8) as client:
        for query in queries:
            try:
                resp = await client.get(
                    "https://hn.algolia.com/api/v1/search",
                    params={"query": query, "tags": "story", "hitsPerPage": 15},
                )
                if resp.status_code != 200:
                    continue
                hits = resp.json().get("hits", [])
                for h in hits:
                    obj_id = h.get("objectID", "")
                    if obj_id in seen_ids:
                        continue
                    title = (h.get("title") or "").lower()
                    article_url = (h.get("url") or "").lower()
                    date_str = (h.get("created_at") or "")[:10]
                    year = int(date_str[:4]) if len(date_str) >= 4 else 9999

                    # Must mention brand or product name in title
                    if brand.lower() not in title and product_name.lower() not in title:
                        continue

                    # Filter out academic/math/science domains — common false positive
                    # for brands that are also common words (e.g. "affine", "arc", "linear")
                    _bad_domains = {
                        "math.stackexchange.com", "mathworld.wolfram.com", "arxiv.org",
                        "en.wikipedia.org", "researchgate.net", "academia.edu",
                        "semanticscholar.org", "sciencedirect.com", "springer.com",
                        "mathoverflow.net", "math.stackexchange.com",
                    }
                    if any(d in article_url for d in _bad_domains):
                        continue

                    # Skip very old posts unless URL explicitly matches the product domain
                    if year < 2019 and brand.lower() not in article_url:
                        continue

                    # For short/common-word brands, require tech product context in title
                    _common_words = {"affine", "linear", "notion", "arc", "base", "flow",
                                     "core", "loop", "mesh", "wave", "plane", "shift"}
                    if brand.lower() in _common_words:
                        _tech_words = {"launch", "open source", "funding", "startup", "tool",
                                       "app", "product", "github", "release", "saas", "api",
                                       "software", "update", "raises", "announce", "show hn"}
                        has_context = any(w in title for w in _tech_words) or brand.lower() in article_url
                        if not has_context:
                            continue

                    seen_ids.add(obj_id)
                    hn_url = f"https://news.ycombinator.com/item?id={obj_id}"
                    results.append({
                        "source":   "HackerNews",
                        "title":    h.get("title", ""),
                        "url":      h.get("url") or hn_url,
                        "hn_url":   hn_url,
                        "points":   h.get("points", 0) or 0,
                        "comments": h.get("num_comments", 0) or 0,
                        "date":     (h.get("created_at") or "")[:10],
                    })
            except Exception:
                continue

    return sorted(results, key=lambda x: x.get("points", 0), reverse=True)


async def _fetch_google_news(product_name: str) -> list:
    """DataForSEO Google News API — 多查询变体"""
    b64 = os.environ.get("DATAFORSEO_B64", "").strip()
    if not b64:
        try:
            b64 = open(os.path.expanduser("~/.cola/secrets/dataforseo_b64")).read().strip()
        except FileNotFoundError:
            pass
    if not b64:
        return []

    # Try multiple query variations to maximize news coverage
    queries = [
        product_name,
        f"{product_name} open source",
        f"{product_name} funding",
    ]
    seen_urls = set()
    all_items = []

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            payload = [
                {"keyword": q, "location_code": 2840, "language_code": "en", "depth": 10}
                for q in queries
            ]
            resp = await client.post(
                "https://api.dataforseo.com/v3/serp/google/news/live/advanced",
                headers={"Authorization": f"Basic {b64}", "Content-Type": "application/json"},
                json=payload,
            )
        data = resp.json()
        for task in (data.get("tasks") or []):
            if not task.get("result"):
                continue
            for r in (task["result"][0] or {}).get("items", []):
                if r.get("type") != "news":
                    continue
                url = r.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                all_items.append({
                    "source":  r.get("source", ""),
                    "title":   r.get("title", ""),
                    "url":     url,
                    "snippet": (r.get("snippet") or "")[:200],
                    "date":    (r.get("timestamp") or "")[:10],
                })
        return all_items
    except Exception:
        return []


async def _fetch_brave_press(product_name: str, brand: str, domain: str) -> list:
    """Brave Search for press mentions from major tech media"""
    try:
        from .web_search import brave_search
    except ImportError:
        try:
            from web_search import brave_search
        except ImportError:
            return []

    results = []
    seen_urls = set()
    queries = [
        f'"{product_name}" (site:techcrunch.com OR site:theverge.com OR site:wired.com OR site:venturebeat.com OR site:prnewswire.com OR site:businesswire.com)',
        f'"{product_name}" (site:producthunt.com OR site:indiehackers.com OR site:dev.to OR site:medium.com)',
        f'"{brand}" funding OR raises OR launch OR "open source" -site:{domain}',
    ]
    for q in queries:
        try:
            hits = await brave_search(q, count=5)
            for h in hits:
                url = h.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                results.append({
                    "source":  _extract_source(url),
                    "title":   h.get("title", ""),
                    "url":     url,
                    "snippet": (h.get("description") or "")[:200],
                    "date":    "",
                })
        except Exception:
            continue

    return results


def _extract_source(url: str) -> str:
    m = re.search(r'https?://(?:www\.)?([^/]+)', url)
    if not m:
        return ""
    host = m.group(1)
    # Map to short readable names
    mapping = {
        "techcrunch.com": "TechCrunch",
        "theverge.com": "The Verge",
        "wired.com": "Wired",
        "venturebeat.com": "VentureBeat",
        "producthunt.com": "Product Hunt",
        "indiehackers.com": "Indie Hackers",
        "news.ycombinator.com": "HackerNews",
    }
    return mapping.get(host, host)


def _merge_mentions(hn: list, news: list, press: list) -> list:
    seen = set()
    merged = []
    for item in hn:
        key = item.get("hn_url") or item.get("url", "")
        if key and key not in seen:
            seen.add(key)
            merged.append({**item, "_type": "hn"})
    for item in news + press:
        key = item.get("url", "")
        if key and key not in seen:
            seen.add(key)
            merged.append({**item, "_type": "news"})
    return merged


def _gen_insights(hn: list, news: list, press: list) -> list:
    insights = []
    if hn:
        top = hn[0]
        pts = top.get("points", 0)
        cmt = top.get("comments", 0)
        if pts >= 200:
            insights.append(f"🔥 HN 爆款：「{top['title'][:55]}」{pts} points / {cmt} comments")
        elif pts >= 50:
            insights.append(f"📡 HN 热帖：「{top['title'][:55]}」{pts} points")
        insights.append(f"💬 HackerNews 共 {len(hn)} 条相关讨论")
    if news:
        insights.append(f"📰 Google News 收录 {len(news)} 篇媒体报道")
    if press:
        sources = list(dict.fromkeys(p.get("source", "") for p in press if p.get("source")))[:4]
        if sources:
            insights.append(f"🗞 主要媒体来源：{', '.join(sources)}")
    if not hn and not news and not press:
        insights.append("⚠️ 未找到主流媒体曝光记录（可能处于早期或低调运营阶段）")
    return insights
