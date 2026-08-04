"""流量分析模块 — DataForSEO + pytrends + python-whois（无 Caravo 依赖）"""
import asyncio
import os
import httpx
from datetime import datetime
from typing import Optional


async def fetch_seoreviewtools(domain: str) -> dict:
    """Public API: fetch SEO Review Tools data for a domain.
    Called from app.py Phase 1 alongside DataForSEO.
    """
    return await _fetch_seoreviewtools(domain)


def merge_seo_data(dataforseo: dict, srt: dict) -> dict:
    """Public API: merge DataForSEO + SEO Review Tools data.
    Called from app.py after Phase 1 completes.
    """
    return _merge_seo_data(dataforseo, srt)


async def analyze_traffic(domain: str) -> dict:
    """综合流量分析：DataForSEO + SEO Review Tools + Google Trends + WHOIS"""

    brand = (
        domain
        .replace("www.", "")
        .replace(".com", "").replace(".io", "").replace(".dev", "")
        .replace(".ai", "").replace(".co", "").replace(".app", "")
        .split(".")[0]
    )

    # 并发执行所有数据源
    seo_task     = asyncio.create_task(_fetch_dataforseo_metrics(domain))
    srt_task     = asyncio.create_task(_fetch_seoreviewtools(domain))
    trends_task  = asyncio.create_task(_fetch_trends(brand))
    whois_task   = asyncio.create_task(_fetch_whois(domain))

    seo_data    = await seo_task
    srt_data    = await srt_task
    trends_data = await trends_task
    whois_data  = await whois_task

    # Merge: DataForSEO is primary, SEO Review Tools fills gaps + adds DA/Spam Score
    merged_seo = _merge_seo_data(seo_data, srt_data)

    return {
        "seo_metrics":    merged_seo,
        "google_trends":  trends_data,
        "whois":          whois_data,
        "growth_analysis": _build_growth_analysis(merged_seo, trends_data, whois_data),
    }


# ---------------------------------------------------------------------------
# DataForSEO — 有机流量 & 反链指标
# ---------------------------------------------------------------------------

async def _fetch_dataforseo_metrics(domain: str) -> dict:
    from .provider_alerts import is_provider_blocked
    if is_provider_blocked("DataForSEO"):
        return {"error": "DataForSEO temporarily unavailable", "domain": domain}
    b64 = os.environ.get("DATAFORSEO_B64", "").strip()
    if not b64:
        return {"error": "DataForSEO credentials not found"}

    headers = {
        "Authorization": f"Basic {b64}",
        "Content-Type": "application/json",
    }
    payload = [{"target": domain, "location_code": 2840, "language_code": "en"}]

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            rank_resp, bl_resp = await asyncio.gather(
                client.post(
                    "https://api.dataforseo.com/v3/dataforseo_labs/google/domain_rank_overview/live",
                    headers=headers, json=payload,
                ),
                client.post(
                    "https://api.dataforseo.com/v3/backlinks/summary/live",
                    headers=headers,
                    json=[{"target": domain, "limit": 1}],
                ),
                return_exceptions=True,
            )

        result = {}

        # Organic rank metrics
        if not isinstance(rank_resp, Exception) and rank_resp.status_code == 200:
            task = rank_resp.json().get("tasks", [{}])[0]
            item = (task.get("result") or [{}])[0]
            metrics = item.get("metrics", {}).get("organic", {})
            result["organic_traffic_estimate"] = metrics.get("etv", 0)
            result["ranked_keywords"]          = metrics.get("count", 0)
            result["top3_keywords"]            = (
                metrics.get("pos_1", 0) + metrics.get("pos_2_3", 0)
            )

        # Backlink metrics
        if not isinstance(bl_resp, Exception) and bl_resp.status_code == 200:
            task = bl_resp.json().get("tasks", [{}])[0]
            item = (task.get("result") or [{}])[0]
            result["backlinks"]       = item.get("backlinks", 0)
            result["referring_domains"] = item.get("referring_domains", 0)
            result["domain_rank"]     = item.get("rank", 0)

        result["domain"] = domain
        return result

    except Exception as e:
        return {"error": str(e)[:200], "domain": domain}


# ---------------------------------------------------------------------------
# SEO Review Tools — Domain Authority + Traffic + Backlinks (fallback/complement)
# ---------------------------------------------------------------------------

async def _fetch_seoreviewtools(domain: str) -> dict:
    """Fetch traffic + backlink data from SEO Review Tools API.

    Free/cheap alternative to DataForSEO. Provides:
    - Global organic traffic estimate
    - Backlink count, referring domains, TLD distribution
    - Moz Domain Authority (DA) + Spam Score (unique, DataForSEO doesn't have)
    """
    from .provider_alerts import is_provider_blocked
    if is_provider_blocked("SEOReviewTools"):
        return {"_source": "seoreviewtools", "error": "SEOReviewTools temporarily unavailable"}
    api_key = os.environ.get("SEOREVIEWTOOLS_KEY", "").strip()
    if not api_key:
        return {}

    result = {}
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            # Traffic + Backlinks in parallel
            traffic_resp, backlink_resp = await asyncio.gather(
                client.get(f"https://api.seoreviewtools.com/v5/website-traffic/?key={api_key}&url={domain}"),
                client.get(f"https://api.seoreviewtools.com/v5/backlink-overview/?key={api_key}&url={domain}"),
                return_exceptions=True,
            )

            # Parse traffic
            if not isinstance(traffic_resp, Exception) and traffic_resp.status_code == 200:
                data = traffic_resp.json()
                if data.get("status") == "ok":
                    items = data.get("data", {}).get("data", [])
                    if items:
                        result["srt_organic_traffic"] = items[0].get("organic traffic", 0)
                        result["srt_paid_traffic"] = items[0].get("paid traffic", 0)

            # Parse backlinks
            if not isinstance(backlink_resp, Exception) and backlink_resp.status_code == 200:
                data = backlink_resp.json()
                if data.get("status") == "ok":
                    items = data.get("data", {}).get("data", [])
                    if items:
                        bl = items[0]
                        result["domain_authority"] = bl.get("Domain Authority", 0)
                        result["spam_score"] = bl.get("Spam Score", 0)
                        result["srt_backlinks"] = bl.get("Backlinks total", 0)
                        result["srt_referring_domains"] = bl.get("Unique domains", 0)
                        result["srt_indexed_pages"] = bl.get("Indexed pages", 0)
                        # TLD distribution (top 5)
                        tld = bl.get("TLD distribution", {})
                        if isinstance(tld, dict):
                            top_tlds = sorted(tld.items(), key=lambda x: x[1], reverse=True)[:5]
                            result["tld_distribution"] = {k: v for k, v in top_tlds}

    except Exception:
        pass

    result["_source"] = "seoreviewtools"
    return result


def _merge_seo_data(dataforseo: dict, srt: dict) -> dict:
    """Merge DataForSEO (primary) with SEO Review Tools (complement/fallback).

    DataForSEO is more detailed but costs more. SRT adds:
    - domain_authority (Moz DA, 0-100) — DataForSEO has its own 'rank' but not Moz DA
    - spam_score — unique to SRT
    - Fallback traffic/backlink numbers when DataForSEO fails
    """
    merged = dict(dataforseo) if dataforseo else {}

    if not srt:
        return merged

    # Always add DA + Spam Score (unique to SRT, not in DataForSEO)
    if srt.get("domain_authority"):
        merged["domain_authority"] = srt["domain_authority"]
    if srt.get("spam_score") is not None:
        merged["spam_score"] = srt["spam_score"]
    if srt.get("tld_distribution"):
        merged["tld_distribution"] = srt["tld_distribution"]
    if srt.get("srt_indexed_pages"):
        merged["indexed_pages"] = srt["srt_indexed_pages"]

    # Fallback: use SRT data when DataForSEO failed or returned empty
    if merged.get("error") or not merged.get("organic_traffic_estimate"):
        if srt.get("srt_organic_traffic"):
            merged["organic_traffic_estimate"] = srt["srt_organic_traffic"]
            merged["_traffic_source"] = "seoreviewtools"
            merged.pop("error", None)
    if not merged.get("backlinks") and srt.get("srt_backlinks"):
        merged["backlinks"] = srt["srt_backlinks"]
        merged["referring_domains"] = srt.get("srt_referring_domains", 0)
        merged["_backlinks_source"] = "seoreviewtools"

    return merged


# ---------------------------------------------------------------------------
# pytrends — Google Trends
# ---------------------------------------------------------------------------

async def _fetch_trends(brand: str) -> Optional[dict]:
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_trends_sync, brand),
            timeout=35,
        )
    except Exception:
        return None


def _fetch_trends_sync(brand: str) -> Optional[dict]:
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)
        pt.build_payload([brand], cat=0, timeframe="today 12-m", geo="", gprop="")
        df = pt.interest_over_time()
        if df is None or df.empty:
            return None
        if "isPartial" in df.columns:
            df = df.drop(columns=["isPartial"])

        timeline = []
        for date, row in df.iterrows():
            val = int(row[brand]) if brand in row else 0
            timeline.append({
                "date":  date.strftime("%Y-%m-%d"),
                "value": val,
            })

        if not timeline:
            return None

        peak    = max(timeline, key=lambda x: x["value"])
        avg_val = sum(t["value"] for t in timeline) / len(timeline)

        return {
            "query":        brand,
            "timeline":     timeline,
            "peak_date":    peak["date"],
            "peak_value":   peak["value"],
            "avg_interest": round(avg_val, 1),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# python-whois — 域名注册信息
# ---------------------------------------------------------------------------

async def _fetch_whois(domain: str) -> Optional[dict]:
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_whois_sync, domain),
            timeout=15,
        )
    except Exception:
        return None


def _fetch_whois_sync(domain: str) -> Optional[dict]:
    try:
        import whois
        w = whois.whois(domain)

        def _first(v):
            return v[0] if isinstance(v, list) else v

        created = _first(w.creation_date)
        updated = _first(w.updated_date)
        expires = _first(w.expiration_date)

        age_years = None
        if created:
            age_days  = (datetime.now() - created).days
            age_years = round(age_days / 365, 1)

        return {
            "registrar":  w.registrar,
            "created":    created.strftime("%Y-%m-%d") if created else None,
            "updated":    updated.strftime("%Y-%m-%d") if updated else None,
            "expires":    expires.strftime("%Y-%m-%d") if expires else None,
            "age_years":  age_years,
            "country":    _first(w.country) if w.country else None,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Growth analysis summary
# ---------------------------------------------------------------------------

def _build_growth_analysis(seo: dict, trends: Optional[dict], whois: Optional[dict]) -> dict:
    insights   = []
    milestones = []

    if seo and not seo.get("error"):
        etv = seo.get("organic_traffic_estimate", 0)
        kw  = seo.get("ranked_keywords", 0)
        bl  = seo.get("backlinks", 0)
        if etv:
            insights.append(f"预估月有机流量价值：${etv:,.0f}")
        if kw:
            insights.append(f"Google 排名关键词数：{kw:,}")
        if bl:
            insights.append(f"反向链接数：{bl:,}")

    if trends:
        insights.append(
            f"Google 搜索热度峰值：{trends.get('peak_value')} "
            f"（均值 {trends.get('avg_interest')}）"
        )
        milestones.append(f"品牌搜索峰值：{trends.get('peak_date')}")

    if whois:
        if whois.get("created"):
            milestones.append(f"域名注册：{whois['created']}")
        if whois.get("age_years"):
            insights.append(f"域名年龄：{whois['age_years']} 年")

    return {"insights": insights, "milestones": milestones}
