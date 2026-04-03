"""流量分析模块 — DataForSEO + pytrends + python-whois（无 Caravo 依赖）"""
import asyncio
import os
import httpx
from datetime import datetime
from typing import Optional


async def analyze_traffic(domain: str) -> dict:
    """综合流量分析：DataForSEO SEO 指标 + Google Trends + WHOIS"""

    brand = (
        domain
        .replace("www.", "")
        .replace(".com", "").replace(".io", "").replace(".dev", "")
        .replace(".ai", "").replace(".co", "").replace(".app", "")
        .split(".")[0]
    )

    # 并发执行三个数据源
    seo_task     = asyncio.create_task(_fetch_dataforseo_metrics(domain))
    trends_task  = asyncio.create_task(_fetch_trends(brand))
    whois_task   = asyncio.create_task(_fetch_whois(domain))

    seo_data    = await seo_task
    trends_data = await trends_task
    whois_data  = await whois_task

    return {
        "seo_metrics":    seo_data,
        "google_trends":  trends_data,
        "whois":          whois_data,
        "growth_analysis": _build_growth_analysis(seo_data, trends_data, whois_data),
    }


# ---------------------------------------------------------------------------
# DataForSEO — 有机流量 & 反链指标
# ---------------------------------------------------------------------------

async def _fetch_dataforseo_metrics(domain: str) -> dict:
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
