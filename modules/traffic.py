"""流量分析模块 — SimilarWeb + Semrush + Google Trends via Caravo"""
import subprocess
import json
import os
import asyncio


async def analyze_traffic(domain: str) -> dict:
    """综合流量分析：SimilarWeb + Semrush + Google Trends"""
    api_key = _get_api_key()
    if not api_key:
        return {"error": "Caravo API key not found", "note": "请配置 ~/.cola/secrets/caravo_api_key"}

    env = os.environ.copy()
    env["CARAVO_API_KEY"] = api_key

    brand = domain.replace(".com","").replace(".io","").replace(".dev","").replace(".ai","").replace(".co","")

    # Run all Caravo calls in parallel via threads
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    full_url = f"https://{domain}/" if not domain.startswith("http") else domain
    calls = {
        "similarweb": ("similarweb/traffic-analytics", {"domain": domain}),
        "semrush_traffic": ("semrush/website-traffic", {"website": full_url}),
        "semrush_keywords": ("semrush/keyword-insights", {"keyword": brand, "country": "us"}),
        "google_trends": ("google-data/trends", {"q": brand, "geo": "US"}),
        "whois": ("domain-whois/whois", {"domain": domain}),
    }
    
    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_call_caravo, env, tid, params): key for key, (tid, params) in calls.items()}
        for f in as_completed(futures):
            results[futures[f]] = f.result()

    # Analyze growth phases
    results["growth_analysis"] = _analyze_growth_phases(results)

    return results


def _get_api_key():
    path = os.path.expanduser("~/.cola/secrets/caravo_api_key")
    try:
        return open(path).read().strip()
    except FileNotFoundError:
        return None


def _call_caravo(env: dict, tool_id: str, params: dict) -> dict:
    """调用 Caravo CLI"""
    try:
        cmd = ["npx", "-y", "@caravo/cli@latest", "exec", tool_id, "-d", json.dumps(params)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                if data.get("success"):
                    return {"success": True, "data": data.get("output", {}), "cost": data.get("cost", 0)}
                return {"success": False, "error": data.get("error", "Unknown"), "raw": result.stdout[:300]}
            except json.JSONDecodeError:
                return {"success": False, "raw": result.stdout[:300]}
        else:
            stderr = result.stderr[:300]
            if "balance" in stderr.lower() or "$0" in stderr:
                return {"success": False, "error": "Caravo 余额不足", "need_topup": True}
            return {"success": False, "error": stderr[:200]}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "API 调用超时"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def _analyze_growth_phases(results: dict) -> dict:
    """分析增长阶段"""
    analysis = {
        "phases": [],
        "milestones": [],
        "insights": [],
    }
    
    # Extract SimilarWeb data if available
    sw = results.get("similarweb", {})
    if sw.get("success") and sw.get("data"):
        data = sw["data"]
        visits = data.get("estimated_monthly_visits") or data.get("monthly_visits") or data.get("visits")
        if visits:
            analysis["insights"].append(f"月均访问量: {visits}")
        
        bounce = data.get("bounce_rate")
        if bounce:
            analysis["insights"].append(f"跳出率: {bounce}")
        
        sources = data.get("traffic_sources") or data.get("sources")
        if sources:
            analysis["insights"].append(f"流量来源: {json.dumps(sources, ensure_ascii=False)[:200]}")
    
    # Extract Semrush data if available
    sem = results.get("semrush_traffic", {})
    if sem.get("success") and sem.get("data"):
        data = sem["data"]
        authority = data.get("authority_score")
        if authority:
            analysis["insights"].append(f"权威度评分: {authority}")
        
        organic = data.get("organic_traffic") or data.get("organic")
        if organic:
            analysis["insights"].append(f"有机流量: {organic}")
        
        backlinks = data.get("backlinks") or data.get("backlinks_count")
        if backlinks:
            analysis["insights"].append(f"反向链接: {backlinks}")
    
    # WHOIS data for timeline
    whois = results.get("whois", {})
    if whois.get("success") and whois.get("data"):
        data = whois["data"]
        created = data.get("creation_date") or data.get("created")
        if created:
            analysis["milestones"].append(f"域名注册: {str(created)[:10]}")
    
    # Google Trends for interest over time
    trends = results.get("google_trends", {})
    if trends.get("success") and trends.get("data"):
        analysis["insights"].append("Google Trends 数据可用")
    
    return analysis
