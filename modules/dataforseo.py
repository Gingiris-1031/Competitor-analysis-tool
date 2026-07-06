"""DataForSEO API 集成模块 — 域名分析、关键词、反链、历史排名"""
import httpx
import os
import base64
import asyncio
import logging

logger = logging.getLogger(__name__)

API_BASE = "https://api.dataforseo.com/v3"
MAX_RETRIES = 3
RETRYABLE_STATUS = {402, 429, 500, 502, 503, 504}


def _get_auth_header() -> str:
    b64 = os.environ.get("DATAFORSEO_B64", "").strip()
    if not b64:
        try:
            b64 = open(os.path.expanduser("~/.cola/secrets/dataforseo_b64")).read().strip()
        except FileNotFoundError:
            pass
    return f"Basic {b64}" if b64 else ""


async def _post_with_retry(client, url: str, headers: dict, json_body, max_retries: int = MAX_RETRIES):
    """POST with exponential backoff for retryable errors (402/429/5xx/timeout)."""
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = await client.post(url, headers=headers, json=json_body)
            if resp.status_code == 200:
                return resp
            if resp.status_code in RETRYABLE_STATUS and attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(f"DataForSEO {resp.status_code} on {url}, retry {attempt+1}/{max_retries} in {wait}s")
                await asyncio.sleep(wait)
                continue
            return resp  # Non-retryable error, return as-is
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(f"DataForSEO timeout/connect error, retry {attempt+1}/{max_retries} in {wait}s: {e}")
                await asyncio.sleep(wait)
            else:
                raise
    raise last_error


async def _resolve_canonical_domain(domain: str) -> tuple:
    """Follow HTTP redirects to find the domain that actually ranks.

    Iris 2026-07-06 accuracy audit: a user analyzing notion.so got
    organic=152K / 1,143 keywords, while the REAL marketing domain
    notion.com holds 1.23M organic / 86K keywords (8× more). Notion
    migrated domains in 2024 and https://notion.so now chains through
    redirects to www.notion.com — but we were querying DataForSEO with
    the raw user-typed domain.

    Returns (resolved_domain, note). note is "" when nothing changed.
    Falls back to the input on any network error — never blocks the audit.
    """
    raw = (domain or "").strip().lower().rstrip("/")
    bare = raw[4:] if raw.startswith("www.") else raw
    try:
        async with httpx.AsyncClient(
            timeout=8, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; analook/1.0)"},
        ) as c:
            r = await c.get(f"https://{raw}")
            final_host = (r.url.host or "").lower()
            if final_host.startswith("www."):
                final_host = final_host[4:]
            if final_host and final_host != bare:
                return final_host, (
                    f"Input domain {bare} redirects to {final_host}; "
                    f"SEO metrics reflect {final_host} (the domain that actually ranks)."
                )
    except Exception:
        pass
    return bare, ""


async def analyze_domain(domain: str) -> dict:
    """综合域名分析：排名概览 + 反链 + 历史趋势 + Top 关键词

    Wrapped with the audit_cache TTL helper (24h default). DataForSEO calls
    are the slowest single hop in the audit (~30s + paid API quota), so
    cache hits make a HUGE difference for rerunning the same domain
    within a day (Autopilot weekly diffs benefit on every other run).
    """
    domain_key = (domain or "").strip().lower().rstrip("/")
    if not domain_key:
        return {"error": "empty domain"}

    # Resolve redirects BEFORE cache lookup so notion.so and notion.com
    # share one cache entry keyed on the domain that actually ranks.
    resolved, redirect_note = await _resolve_canonical_domain(domain_key)

    async def _fetch_and_annotate():
        res = await _analyze_domain_uncached(resolved)
        if redirect_note and isinstance(res, dict):
            res["queried_domain"] = resolved
            res["redirect_note"] = redirect_note
        return res

    try:
        from .audit_cache import cached_fetch, TTL
        return await cached_fetch(
            source="dataforseo",
            cache_key=resolved,
            ttl_seconds=TTL.DATAFORSEO,
            fetch_fn=_fetch_and_annotate,
        )
    except Exception:
        # Defensive — cache layer failures must never block the audit.
        return await _fetch_and_annotate()


async def _analyze_domain_uncached(domain: str) -> dict:
    """The actual DataForSEO call. Kept separate so the cached wrapper
    above can call this on miss / fallback."""
    auth = _get_auth_header()
    if not auth:
        return {"error": "DataForSEO credentials not found"}

    results = {}
    headers = {"Authorization": auth, "Content-Type": "application/json"}

    # Force IPv4 to avoid IPv6 whitelist issues with DataForSEO
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    async with httpx.AsyncClient(timeout=25, transport=transport) as client:
        # All requests in parallel
        import asyncio
        rank_task = _domain_rank(client, headers, domain)
        backlinks_task = _backlinks_summary(client, headers, domain)
        keywords_task = _top_keywords(client, headers, domain)
        # Historical is expensive ($0.1), only call if needed
        history_task = _historical_rank(client, headers, domain)

        rank, backlinks, keywords, history = await asyncio.gather(
            rank_task, backlinks_task, keywords_task, history_task,
            return_exceptions=True
        )

        results["domain_rank"] = rank if not isinstance(rank, Exception) else {"error": str(rank)[:100]}
        results["backlinks"] = backlinks if not isinstance(backlinks, Exception) else {"error": str(backlinks)[:100]}
        results["top_keywords"] = keywords if not isinstance(keywords, Exception) else {"error": str(keywords)[:100]}
        results["historical"] = history if not isinstance(history, Exception) else {"error": str(history)[:100]}

    # Generate growth analysis from historical data
    results["growth_analysis"] = _analyze_growth(results)
    results["total_cost"] = sum(r.get("cost", 0) for r in results.values() if isinstance(r, dict))

    return results


async def _domain_rank(client, headers, domain) -> dict:
    """域名排名概览"""
    resp = await _post_with_retry(
        client, f"{API_BASE}/dataforseo_labs/google/domain_rank_overview/live",
        headers, [{"target": domain, "language_code": "en", "location_code": 2840}],
    )
    data = resp.json()
    cost = data.get("cost", 0)
    task = data.get("tasks", [{}])[0]
    if task.get("result") and task["result"][0].get("items"):
        metrics = task["result"][0]["items"][0].get("metrics", {})
        org = metrics.get("organic", {})
        return {
            "cost": cost,
            "organic_traffic": round(org.get("etv", 0)),
            "total_keywords": org.get("count", 0),
            "keywords_top1": org.get("pos_1", 0),
            "keywords_top3": org.get("pos_1", 0) + org.get("pos_2_3", 0),
            "keywords_top10": org.get("pos_1", 0) + org.get("pos_2_3", 0) + org.get("pos_4_10", 0),
            "new_keywords": org.get("is_new", 0),
            "lost_keywords": org.get("is_lost", 0),
            "estimated_paid_cost": round(org.get("estimated_paid_traffic_cost", 0)),
        }
    return {"cost": cost, "error": task.get("status_message", "No data")}


async def _backlinks_summary(client, headers, domain) -> dict:
    """反链概览"""
    resp = await _post_with_retry(
        client, f"{API_BASE}/backlinks/summary/live",
        headers, [{"target": domain}],
    )
    data = resp.json()
    cost = data.get("cost", 0)
    task = data.get("tasks", [{}])[0]
    if task.get("result"):
        r = task["result"][0]
        return {
            "cost": cost,
            "backlinks": r.get("backlinks", 0),
            "referring_domains": r.get("referring_domains", 0),
            "domain_rank": r.get("rank", 0),
            "referring_ips": r.get("referring_ips", 0),
            "broken_backlinks": r.get("broken_backlinks", 0),
        }
    return {"cost": cost, "error": "No data"}


async def _top_keywords(client, headers, domain) -> dict:
    """Top 排名关键词 — 分品牌词 vs 非品牌词"""
    # Fetch more keywords to ensure enough non-branded ones
    resp = await _post_with_retry(
        client, f"{API_BASE}/dataforseo_labs/google/ranked_keywords/live",
        headers, [{
            "target": domain,
            "language_code": "en",
            "location_code": 2840,
            "limit": 200,
            "order_by": ["keyword_data.keyword_info.search_volume,desc"],
            "filters": ["ranked_serp_element.serp_item.rank_absolute","<",51],
        }],
    )
    data = resp.json()
    cost = data.get("cost", 0)
    task = data.get("tasks", [{}])[0]

    # Extract brand variants for classification
    brand = domain.lower().replace("www.", "")
    import re
    brand_clean = re.sub(r'\.[a-z]{2,6}$', '', brand)
    brand_variants = {brand_clean, brand_clean.replace("-", ""), brand_clean.replace("-", " ")}
    # Also add domain without TLD dot-separated variants (e.g. "affine pro" for affine.pro)
    domain_no_www = re.sub(r'^www\.', '', domain.lower())
    if '.' in domain_no_www:
        parts = domain_no_www.rsplit('.', 1)
        if parts[1] not in ('com', 'org', 'net', 'io', 'dev', 'ai', 'co', 'app'):
            # For non-standard TLDs like .pro, add "brand tld" as branded variant
            brand_variants.add(f"{parts[0]} {parts[1]}")
            brand_variants.add(f"{parts[0]}.{parts[1]}")

    def _is_branded(kw: str) -> bool:
        kw_lower = kw.lower()
        # Each variant must appear as a whole word (or word prefix) in the keyword,
        # not just as a substring of an unrelated word
        for v in brand_variants:
            if len(v) <= 2:
                continue
            if v not in kw_lower:
                continue
            # Verify it's a word boundary match to avoid false positives
            # e.g. "affi" in "affiliate" should NOT match for brand "affine"
            pattern = r'(?:^|[\s\-_])' + re.escape(v) + r'(?:[\s\-_.,!?]|$)'
            if re.search(pattern, kw_lower):
                return True
            # Also match if the variant IS the full keyword or starts the keyword
            if kw_lower == v or kw_lower.startswith(v + ' ') or kw_lower.startswith(v + '-'):
                return True
        return False

    all_keywords = []
    if task.get("result") and task["result"][0].get("items"):
        for item in task["result"][0]["items"]:
            kd = item.get("keyword_data", {})
            ki = kd.get("keyword_info", {})
            serp = item.get("ranked_serp_element", {}).get("serp_item", {})
            kw_text = kd.get("keyword", "")
            all_keywords.append({
                "keyword": kw_text,
                "position": serp.get("rank_absolute", 0),
                "search_volume": ki.get("search_volume", 0),
                "cpc": ki.get("cpc", 0),
                "competition": ki.get("competition_level", ""),
                "is_branded": _is_branded(kw_text),
            })

    branded = [k for k in all_keywords if k["is_branded"]]
    non_branded = [k for k in all_keywords if not k["is_branded"]]

    # Tag non-branded keywords: product-related vs. pure content-SEO (unrelated to core product)
    _TECH_WORDS = {
        "software", "app", "tool", "alternative", "open", "source", "ai", "api",
        "saas", "cloud", "platform", "productivity", "workspace", "collaboration",
        "whiteboard", "editor", "docs", "markdown", "code", "developer", "github",
        "startup", "integrate", "plugin", "automation", "workflow", "template",
        "dashboard", "analytics", "crm", "project", "management", "team", "sync",
        "database", "privacy", "enterprise", "free", "pricing", "review", "vs",
        "compare", "best", "top", "online", "web", "desktop", "mobile", "note",
        "wiki", "kanban", "document", "spreadsheet", "diagram", "chart", "design",
    }
    _TECH_PHRASES = ["open source", " vs ", "alternative to", "for teams", "vs "]

    def _is_product_related(kw: str) -> bool:
        kw_lower = kw.lower()
        words = set(re.split(r'[\s\-_/]', kw_lower))
        if words & _TECH_WORDS:
            return True
        return any(p in kw_lower for p in _TECH_PHRASES)

    for k in non_branded:
        k["is_content_only"] = not _is_product_related(k["keyword"])

    # Sort: first-page rankings (pos ≤ 10) first, then by search_volume desc within each group
    non_branded_by_volume = sorted(
        non_branded,
        key=lambda x: (0 if x.get("position", 99) <= 10 else 1, -x.get("search_volume", 0)),
    )

    # Separate product-related vs content-only non-branded
    product_non_branded = [k for k in non_branded_by_volume if not k.get("is_content_only")]
    content_non_branded = [k for k in non_branded_by_volume if k.get("is_content_only")]

    # Keyword gap: low-competition but decent-volume non-branded keywords
    # These are opportunities a competitor can realistically target
    gap_keywords = sorted(
        [k for k in non_branded if not k.get("is_content_only") and k.get("search_volume", 0) >= 500],
        key=lambda x: (
            # Score: high volume + low competition + NOT already top-3 for incumbent
            x.get("search_volume", 0) * (1.5 if x.get("competition") in ("LOW", "") else 0.8 if x.get("competition") == "MEDIUM" else 0.4)
            * (1.0 if x.get("position", 1) > 3 else 0.3)
        ),
        reverse=True,
    )

    return {
        "cost": cost,
        "keywords": all_keywords[:10],  # Legacy: top 10 overall
        "branded_keywords": branded[:30],
        "non_branded_keywords": non_branded_by_volume[:30],
        "product_keywords": product_non_branded[:20],    # Non-branded but product-adjacent
        "content_keywords": content_non_branded[:10],    # Unrelated content-SEO pages
        "gap_keywords": gap_keywords[:15],               # Keyword gap opportunities
        "total": task.get("result", [{}])[0].get("total_count", 0) if task.get("result") else 0,
        "branded_count": len(branded),
        "non_branded_count": len(non_branded),
        "product_keyword_count": len(product_non_branded),
        "content_keyword_count": len(content_non_branded),
        "gap_keyword_count": len(gap_keywords),
    }


async def _historical_rank(client, headers, domain) -> dict:
    """历史排名趋势"""
    resp = await _post_with_retry(
        client, f"{API_BASE}/dataforseo_labs/google/historical_rank_overview/live",
        headers, [{"target": domain, "language_code": "en", "location_code": 2840}],
    )
    data = resp.json()
    cost = data.get("cost", 0)
    task = data.get("tasks", [{}])[0]
    history = []
    if task.get("result") and task["result"][0] and task["result"][0].get("items"):
        for item in task["result"][0]["items"]:
            org = item.get("metrics", {}).get("organic", {})
            history.append({
                "date": f"{item.get('year')}-{item.get('month', 0):02d}",
                "organic_traffic": round(org.get("etv", 0)),
                "keywords": org.get("count", 0),
                "top1": org.get("pos_1", 0),
                "top10": org.get("pos_1", 0) + org.get("pos_2_3", 0) + org.get("pos_4_10", 0),
                "new": org.get("is_new", 0),
                "lost": org.get("is_lost", 0),
            })
    # Sort by date
    history.sort(key=lambda x: x["date"])
    return {"cost": cost, "history": history}


def _analyze_growth(results: dict) -> dict:
    """基于历史数据分析增长阶段"""
    analysis = {"phases": [], "insights": [], "milestones": []}

    hist = results.get("historical", {}).get("history", [])
    if not hist:
        return analysis

    # Identify growth phases
    for i, h in enumerate(hist):
        if i == 0:
            continue
        prev = hist[i - 1]
        prev_etv = prev.get("organic_traffic", 0) or 1
        curr_etv = h.get("organic_traffic", 0)
        growth_pct = ((curr_etv - prev_etv) / prev_etv) * 100

        if growth_pct > 50:
            analysis["milestones"].append(f"🚀 {h['date']}: 流量暴涨 {growth_pct:.0f}%（{prev_etv:,} → {curr_etv:,}）")
        elif growth_pct < -30:
            analysis["milestones"].append(f"📉 {h['date']}: 流量下降 {growth_pct:.0f}%（{prev_etv:,} → {curr_etv:,}）")

    # Overall trend
    if len(hist) >= 2:
        first = hist[0].get("organic_traffic", 0) or 1
        last = hist[-1].get("organic_traffic", 0)
        total_growth = ((last - first) / first) * 100
        analysis["insights"].append(f"📊 总体增长: {first:,} → {last:,}（{total_growth:+.0f}%，{len(hist)} 个月）")

    # Current metrics
    rank = results.get("domain_rank", {})
    if rank.get("organic_traffic"):
        analysis["insights"].append(f"🔍 当前有机流量: {rank['organic_traffic']:,}/月")
        analysis["insights"].append(f"📝 排名关键词: {rank.get('total_keywords', 0):,} 个（Top 1: {rank.get('keywords_top1', 0)}，Top 10: {rank.get('keywords_top10', 0)}）")
        analysis["insights"].append(f"💰 等效付费流量成本: ${rank.get('estimated_paid_cost', 0):,}/月")

    bl = results.get("backlinks", {})
    if bl.get("backlinks"):
        analysis["insights"].append(f"🔗 反向链接: {bl['backlinks']:,}（{bl.get('referring_domains', 0):,} 引用域名）")
        analysis["insights"].append(f"📈 域名排名: {bl.get('domain_rank', 0)}")

    # Detect phases
    if hist:
        etv_values = [h.get("organic_traffic", 0) for h in hist]
        max_etv = max(etv_values)
        max_idx = etv_values.index(max_etv)

        # Find launch point (first significant traffic)
        launch_idx = next((i for i, v in enumerate(etv_values) if v > max_etv * 0.05), 0)
        if launch_idx > 0:
            analysis["phases"].append({
                "name": "🌱 探索与初步验证期",
                "period": f"{hist[0]['date']} — {hist[launch_idx]['date']}",
                "description": f"流量在 {etv_values[0]:,} — {etv_values[launch_idx]:,} 间波动",
            })

        # Find explosive growth (>50% MoM)
        explosive = [(i, h) for i, h in enumerate(hist[1:], 1)
                     if (hist[i-1].get("organic_traffic", 0) or 1) and
                     ((h.get("organic_traffic", 0) - (hist[i-1].get("organic_traffic", 0) or 1)) / (hist[i-1].get("organic_traffic", 0) or 1)) > 0.5]
        if explosive:
            start_idx = explosive[0][0] - 1
            end_idx = explosive[-1][0]
            analysis["phases"].append({
                "name": "🚀 爆发增长期",
                "period": f"{hist[start_idx]['date']} — {hist[min(end_idx+1, len(hist)-1)]['date']}",
                "description": f"流量从 {etv_values[start_idx]:,} 飙升至 {etv_values[min(end_idx+1, len(hist)-1)]:,}",
            })

    return analysis
