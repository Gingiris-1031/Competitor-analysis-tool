"""DataForSEO API 集成模块 — 域名分析、关键词、反链、历史排名"""
import httpx
import os
import base64


API_BASE = "https://api.dataforseo.com/v3"


def _get_auth_header() -> str:
    b64 = os.environ.get("DATAFORSEO_B64", "").strip()
    if not b64:
        try:
            b64 = open(os.path.expanduser("~/.cola/secrets/dataforseo_b64")).read().strip()
        except FileNotFoundError:
            pass
    return f"Basic {b64}" if b64 else ""


async def analyze_domain(domain: str) -> dict:
    """综合域名分析：排名概览 + 反链 + 历史趋势 + Top 关键词"""
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
    resp = await client.post(
        f"{API_BASE}/dataforseo_labs/google/domain_rank_overview/live",
        headers=headers,
        json=[{"target": domain, "language_code": "en", "location_code": 2840}],
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
    resp = await client.post(
        f"{API_BASE}/backlinks/summary/live",
        headers=headers,
        json=[{"target": domain}],
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
    resp = await client.post(
        f"{API_BASE}/dataforseo_labs/google/ranked_keywords/live",
        headers=headers,
        json=[{
            "target": domain,
            "language_code": "en",
            "location_code": 2840,
            "limit": 50,
            "order_by": ["ranked_serp_element.serp_item.rank_absolute,asc"],
            "filters": ["ranked_serp_element.serp_item.rank_absolute","<",21],
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
    # Add common misspellings / partial matches
    if len(brand_clean) > 3:
        brand_variants.add(brand_clean[:4])

    def _is_branded(kw: str) -> bool:
        kw_lower = kw.lower()
        return any(v in kw_lower for v in brand_variants if len(v) > 2)

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

    # Sort non-branded by search_volume desc for "top exposure" keywords
    non_branded_by_volume = sorted(non_branded, key=lambda x: x.get("search_volume", 0), reverse=True)

    return {
        "cost": cost,
        "keywords": all_keywords[:10],  # Legacy: top 10 overall
        "branded_keywords": branded[:10],
        "non_branded_keywords": non_branded_by_volume[:10],
        "total": task.get("result", [{}])[0].get("total_count", 0) if task.get("result") else 0,
        "branded_count": len(branded),
        "non_branded_count": len(non_branded),
    }


async def _historical_rank(client, headers, domain) -> dict:
    """历史排名趋势"""
    resp = await client.post(
        f"{API_BASE}/dataforseo_labs/google/historical_rank_overview/live",
        headers=headers,
        json=[{"target": domain, "language_code": "en", "location_code": 2840}],
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
