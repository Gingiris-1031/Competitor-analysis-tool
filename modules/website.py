"""官网深度分析模块 — Wayback Machine 多快照抓取 + 结构对比"""
import httpx
import json as _json
import os
import time
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import asyncio
import re

# ---------------------------------------------------------------------------
# Wayback cache — disk (fast) + Supabase (persistent across Railway restarts)
# ---------------------------------------------------------------------------
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")
_WAYBACK_CACHE_TTL = 30 * 24 * 3600  # 30 days (snapshots don't change)


def _cache_key(domain: str) -> str:
    return os.path.join(_CACHE_DIR, f"wayback_{domain.replace('/', '_')}.json")


def _read_cache(domain: str) -> dict | None:
    """Read from disk first (fast), then Supabase (persistent)."""
    # Disk cache
    path = _cache_key(domain)
    try:
        if os.path.exists(path):
            with open(path) as f:
                data = _json.load(f)
            if time.time() - data.get("_ts", 0) < _WAYBACK_CACHE_TTL:
                return data.get("result")
    except Exception:
        pass

    # Supabase cache (survives Railway restarts)
    try:
        from .supabase_client import get_supabase
        sb = get_supabase()
        if sb:
            resp = sb.table("wayback_cache").select("data,created_at").eq("domain", domain.lower()).limit(1).execute()
            rows = resp.data if resp else []
            if rows:
                row = rows[0]
                # Check TTL
                from datetime import datetime as _dt
                created = _dt.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                age_seconds = (datetime.now(_dt.now().astimezone().tzinfo) - created).total_seconds()
                if age_seconds < _WAYBACK_CACHE_TTL:
                    result = _json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
                    # Warm disk cache
                    _write_disk_cache(domain, result)
                    return result
    except Exception:
        pass

    return None


def _write_disk_cache(domain: str, result: dict):
    """Write to local disk."""
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_cache_key(domain), "w") as f:
            _json.dump({"_ts": time.time(), "result": result}, f)
    except Exception:
        pass


def _write_cache(domain: str, result: dict):
    """Write to both disk and Supabase."""
    _write_disk_cache(domain, result)

    # Supabase upsert (persistent)
    try:
        from .supabase_client import get_supabase
        sb = get_supabase()
        if sb:
            sb.table("wayback_cache").upsert({
                "domain": domain.lower(),
                "data": _json.dumps(result),
                "created_at": datetime.now().isoformat(),
            }, on_conflict="domain").execute()
    except Exception:
        pass


async def analyze_website(url: str) -> dict:
    """深度分析目标官网：历史演变对比 + 当前结构"""
    if not url.startswith("http"):
        url = f"https://{url}"
    domain = urlparse(url).netloc
    if not domain:
        domain = url.replace("https://", "").replace("http://", "").split("/")[0]

    # Check disk cache first — Wayback data doesn't change, cache for 7 days
    cached = _read_cache(domain)
    if cached:
        # Always re-fetch current site (it changes), keep cached historical data
        current = await _analyze_current_site(url)
        cached["current_site"] = current
        return cached

    # Step 0: Follow redirects to find the REAL domain (quick check, 5s max)
    real_domain = domain
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            resp = await client.head(url, headers={"User-Agent": "Mozilla/5.0"})
            redirected = urlparse(str(resp.url)).netloc
            if redirected and redirected != domain:
                real_domain = redirected
    except Exception:
        pass

    # Step 1: Get Wayback timeline — try top 3 domain variants IN PARALLEL for speed
    domains_to_try = list(dict.fromkeys([real_domain, domain,
        real_domain.replace("www.", ""), domain.replace("www.", "")]))
    domains_to_try = [d for d in domains_to_try if d][:3]

    async def _try_domain(d: str):
        meta = await _fetch_wayback_timeline(d)
        return d, meta

    variant_results = await asyncio.gather(*[_try_domain(d) for d in domains_to_try], return_exceptions=True)

    wayback_meta = {"all_timestamps": [], "total_count": 0}
    for vr in variant_results:
        if isinstance(vr, tuple) and vr[1].get("all_timestamps"):
            domain, wayback_meta = vr[0], vr[1]
            break
    
    # Step 2: Select key snapshots (6-8 spread across project lifetime)
    key_timestamps = _select_key_snapshots(wayback_meta.get("all_timestamps", []))
    
    # Step 3: Fetch and analyze each snapshot + current site IN PARALLEL (capped at 20s)
    snapshot_tasks = [_analyze_snapshot(domain, ts) for ts in key_timestamps]
    current_task = _analyze_current_site(url)

    all_tasks = snapshot_tasks + [current_task]
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*all_tasks, return_exceptions=True),
            timeout=20,
        )
    except asyncio.TimeoutError:
        results = [{"error": "snapshot fetch timeout"}] * len(all_tasks)

    snapshots = []
    for i, r in enumerate(results[:-1]):
        if isinstance(r, Exception):
            snapshots.append({"timestamp": key_timestamps[i], "error": str(r)[:100]})
        elif isinstance(r, dict):
            snapshots.append(r)
        else:
            snapshots.append({"timestamp": key_timestamps[i], "error": "unexpected result"})

    current = results[-1] if (isinstance(results[-1], dict) and "error" not in results[-1]) else (
        results[-1] if isinstance(results[-1], dict) else {"error": str(results[-1])}
    )
    
    # Step 4: Mark and filter parked domain snapshots
    for snap in snapshots:
        snap["is_parked"] = _is_parked_page(snap)

    # Only include real-content snapshots in the timeline
    real_snapshots = [s for s in snapshots if not s.get("is_parked")]

    # Step 5: Detect changes between real snapshots only
    changes = _detect_changes(real_snapshots, current)

    # Refine first_seen: skip domain registrar / parked pages
    raw_first_seen = wayback_meta.get("first_seen", "N/A")
    first_seen = _refine_first_seen(raw_first_seen, snapshots)

    result = {
        "domain": domain,
        "first_seen": first_seen,
        "first_seen_raw": raw_first_seen,
        "total_snapshots": wayback_meta.get("total_count", 0),
        "deep_timeline": real_snapshots,
        "current_site": current,
        "key_changes": changes,
    }

    # Cache to disk if we got meaningful data (not just current site)
    if real_snapshots:
        _write_cache(domain, result)

    return result


_REGISTRAR_PATTERNS = [
    "registrado en", "dondominio", "godaddy", "namecheap", "domain for sale",
    "parked domain", "coming soon", "under construction", "domain is registered",
    "buy this domain", "this domain", "domain parking", "sedo.com",
    "hugedomains", "dan.com", "afternic", "flippa",
]


def _is_parked_page(snap: dict) -> bool:
    """Detect domain registrar / parked-page snapshots."""
    if snap.get("error"):
        return True
    title = (snap.get("title") or "").lower()
    slogan = (snap.get("slogan") or "").lower()
    combined = title + " " + slogan
    if any(p in combined for p in _REGISTRAR_PATTERNS):
        return True
    # Very short/empty title = likely parked or error page
    if not title or len(title) <= 5:
        return True
    return False


def _refine_first_seen(raw_first_seen: str, snapshots: list) -> str:
    """Return the date of the first snapshot with real product content."""
    for snap in sorted(snapshots, key=lambda s: s.get("date", "") or ""):
        date = snap.get("date", "")
        if date and not _is_parked_page(snap):
            return date[:10] if len(date) >= 10 else date
    return raw_first_seen


async def _fetch_wayback_timeline(domain: str) -> dict:
    """获取快照时间线：CDX + Memento 并行尝试，任一成功即返回"""

    # Run CDX and Memento in parallel — don't wait for one to fail before trying the other
    cdx_task = _try_cdx(domain)
    memento_task = _try_memento(domain)

    results = await asyncio.gather(cdx_task, memento_task, return_exceptions=True)

    # Prefer CDX (deduped, cleaner data)
    for r in results:
        if isinstance(r, dict) and r.get("all_timestamps"):
            return r

    # Fallback to timemap (sequential, only if parallel failed)
    result = await _try_timemap(domain)
    if result.get("all_timestamps"):
        return result

    return {"all_timestamps": [], "error": "Wayback Machine API 暂不可用，历史快照分析跳过"}


async def _try_memento(domain: str) -> dict:
    """Memento Time Travel API — 聚合多个存档源（Wayback、Archive.today 等）"""
    url = f"https://timetravel.mementoweb.org/timemap/json/https://{domain}/"
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return {"all_timestamps": []}
            data = resp.json()
    except Exception:
        return {"all_timestamps": []}

    # Memento JSON timemap: {"mementos": {"list": [{"datetime": "...", "uri": [...]}, ...]}}
    mementos = []
    try:
        raw_list = data.get("mementos", {}).get("list", [])
        for m in raw_list:
            dt = m.get("datetime", "")
            # Convert ISO datetime "2014-03-01T12:34:56Z" → "20140301123456"
            if dt:
                ts = re.sub(r"[-:TZ]", "", dt)[:14].ljust(14, "0")
                mementos.append(ts)
    except Exception:
        return {"all_timestamps": []}

    if not mementos:
        return {"all_timestamps": []}

    mementos.sort()
    return {
        "all_timestamps": mementos,
        "total_count": len(mementos),
        "first_seen": f"{mementos[0][:4]}-{mementos[0][4:6]}-{mementos[0][6:8]}" if mementos else "N/A",
        "source": "memento",
    }


async def _try_cdx(domain: str) -> dict:
    """CDX API — 按半年去重"""
    api_url = (
        f"https://web.archive.org/cdx/search/cdx"
        f"?url={domain}&output=json&fl=timestamp,statuscode"
        f"&filter=statuscode:200&collapse=timestamp:6&limit=30"
    )
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                return {"all_timestamps": []}
            data = resp.json()
    except Exception:
        return {"all_timestamps": []}

    if not data or len(data) < 2:
        return {"all_timestamps": []}

    rows = data[1:] if isinstance(data[0], list) and data[0][0] == "timestamp" else data
    timestamps = [str(row[0]) for row in rows if len(row) >= 2]
    
    return {
        "all_timestamps": timestamps,
        "total_count": len(timestamps),
        "first_seen": f"{timestamps[0][:4]}-{timestamps[0][4:6]}-{timestamps[0][6:8]}" if timestamps else "N/A",
    }


async def _try_timemap(domain: str) -> dict:
    """Timemap API — fallback，更稳定但不去重"""
    api_url = f"https://web.archive.org/web/timemap/json?url={domain}&fl=timestamp,original&limit=50&output=json"
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                return {"all_timestamps": []}
            data = resp.json()
    except Exception:
        return {"all_timestamps": []}

    if not data or len(data) < 2:
        return {"all_timestamps": []}

    rows = data[1:] if isinstance(data[0], list) and data[0][0] == "timestamp" else data
    timestamps = [str(row[0]) for row in rows]
    
    return {
        "all_timestamps": timestamps,
        "total_count": len(timestamps),
        "first_seen": f"{timestamps[0][:4]}-{timestamps[0][4:6]}-{timestamps[0][6:8]}" if timestamps else "N/A",
    }


def _select_key_snapshots(timestamps: list, max_count: int = 5) -> list:
    """选择关键快照时间点：首个 + 均匀分布 + 最近"""
    if not timestamps:
        return []
    if len(timestamps) <= max_count:
        return timestamps
    
    selected = [timestamps[0]]  # First ever
    step = len(timestamps) // (max_count - 1)
    for i in range(1, max_count - 1):
        idx = min(i * step, len(timestamps) - 1)
        selected.append(timestamps[idx])
    selected.append(timestamps[-1])  # Latest
    
    # Deduplicate while preserving order
    seen = set()
    result = []
    for ts in selected:
        if ts not in seen:
            seen.add(ts)
            result.append(ts)
    return result


async def _fetch_archive_today(url: str) -> dict:
    """从 Archive.today 获取最新存档快照内容（Wayback 失败时的 fallback）"""
    target = f"https://archive.ph/newest/{url}"
    try:
        async with httpx.AsyncClient(timeout=6, follow_redirects=True) as client:
            resp = await client.get(target, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
        if resp.status_code != 200:
            return {"success": False, "error": f"HTTP {resp.status_code}"}
        # Archive.today wraps the archived page; extract the real timestamp from the URL
        final_url = str(resp.url)
        # URL pattern: https://archive.ph/XXXXX  (alphanumeric slug)
        ts_match = re.search(r"archive\.ph/(\d{14})", final_url)
        if not ts_match:
            # Try to extract from page <title> or canonical link
            soup = BeautifulSoup(resp.text, "html.parser")
            ts_match = re.search(r"(\d{4})[/-](\d{2})[/-](\d{2})", final_url + resp.text[:500])
        # Use current timestamp as fallback
        from datetime import datetime
        if ts_match:
            raw_ts = ts_match.group(0).replace("-", "").replace("/", "")[:8]
            timestamp = raw_ts.ljust(14, "0")
        else:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return {"success": True, "html": resp.text, "timestamp": timestamp, "source": "archive.today", "archive_url": final_url}
    except Exception as e:
        return {"success": False, "error": str(e)[:100]}


async def _analyze_snapshot(domain: str, timestamp: str) -> dict:
    """抓取并分析单个 Wayback 快照（使用 id_ 获取干净原始 HTML）；失败时 fallback 到 Archive.today"""
    # id_ suffix = raw content without Wayback toolbar injection
    archive_url = f"https://web.archive.org/web/{timestamp}id_/https://{domain}/"
    display_url = f"https://web.archive.org/web/{timestamp}/https://{domain}/"
    
    html = None
    source_url = display_url
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            resp = await client.get(archive_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            })
        if resp.status_code == 200 and len(resp.text) > 500:
            html = resp.text
    except Exception:
        pass

    # Fallback to Archive.today if Wayback returned nothing useful
    if not html:
        at_result = await _fetch_archive_today(f"https://{domain}/")
        if at_result.get("success") and at_result.get("html"):
            html = at_result["html"]
            source_url = at_result.get("archive_url", display_url)
            timestamp = at_result.get("timestamp", timestamp)

    if not html:
        return {
            "timestamp": timestamp,
            "date": f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}",
            "error": "Wayback + Archive.today 均无法获取快照",
        }

    result = _extract_page_structure(html, timestamp, source_url)
    return result


async def _analyze_current_site(url: str) -> dict:
    """抓取并分析当前官网（带重试）"""
    from datetime import datetime

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
                })
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            result = _extract_page_structure(resp.text, ts, url)
            result["is_current"] = True
            # Verify we got real data
            if result.get("slogan") and result["slogan"] != "N/A":
                return result
            if result.get("title") and result["title"] != "N/A":
                return result
        except Exception:
            if attempt == 0:
                await asyncio.sleep(2)
                continue
    
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return {"timestamp": ts, "date": ts[:10], "is_current": True, "error": "Failed to fetch current site"}


def _extract_page_structure(html: str, timestamp: str, url: str) -> dict:
    """从 HTML 提取详细页面结构"""
    soup = BeautifulSoup(html, "html.parser")
    
    date_str = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}" if len(timestamp) >= 8 else timestamp[:10]
    
    # === Title / Slogan ===
    title = soup.title.string.strip() if soup.title and soup.title.string else "N/A"
    og_title = ""
    og_tag = soup.find("meta", property="og:title")
    if og_tag:
        og_title = og_tag.get("content", "")
    
    # H1 as slogan
    h1s = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)][:5]
    slogan = h1s[0] if h1s else og_title or title
    
    # Meta description
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag:
        meta_desc = meta_tag.get("content", "")[:200]
    
    # === Site Structure (H2 headings as sections) ===
    h2s = [h.get_text(strip=True) for h in soup.find_all("h2") if h.get_text(strip=True)][:15]
    
    # Nav links
    nav_links = []
    for nav in soup.find_all(["nav", "header"]):
        for a in nav.find_all("a"):
            text = a.get_text(strip=True)
            href = a.get("href", "")
            if text and len(text) < 30 and not href.startswith("#wm-") and not "web.archive.org" in href:
                nav_links.append(text)
    nav_links = list(dict.fromkeys(nav_links))[:15]  # Deduplicate
    
    # === Feature Detection ===
    all_links = []
    all_hrefs = []
    for a in soup.find_all("a"):
        href = a.get("href", "").lower()
        text = a.get_text(strip=True).lower()
        all_links.append(text)
        all_hrefs.append(href)
    
    link_text_combined = " ".join(all_links + all_hrefs)
    full_text = soup.get_text(" ", strip=True).lower()
    
    # Key page detection
    has_pricing = any(k in link_text_combined for k in ["pricing", "price", "plan", "定价"])
    has_blog = any(k in link_text_combined for k in ["blog", "news", "article", "博客"])
    has_docs = any(k in link_text_combined for k in ["docs", "documentation", "guide", "文档"])
    has_changelog = any(k in link_text_combined for k in ["changelog", "release", "what-s-new", "updates", "更新"])
    has_faq = any(k in link_text_combined for k in ["faq", "frequently", "常见问题"])
    has_trial = any(k in link_text_combined for k in ["free trial", "try free", "get started", "sign up", "start free", "免费试用"])
    has_demo = any(k in link_text_combined for k in ["demo", "request demo", "book demo", "预约演示"])
    
    # === Customer logos / testimonials ===
    has_logos = bool(re.search(r"trusted by|used by|customer|logo|client|企业|客户", full_text))
    has_testimonials = bool(re.search(r"testimonial|review|what .* say|用户评价|用户故事", full_text))
    has_case_study = any(k in link_text_combined for k in ["case study", "case studies", "案例", "showcase"])
    
    # === Privacy / Legal ===
    has_privacy = any(k in link_text_combined for k in ["privacy", "隐私"])
    has_terms = any(k in link_text_combined for k in ["terms", "条款"])
    
    # === Social Media Links ===
    social_links = {}
    social_patterns = {
        "twitter": [r"twitter\.com/(\w+)", r"x\.com/(\w+)"],
        "instagram": [r"instagram\.com/(\w+)"],
        "linkedin": [r"linkedin\.com/company/([\w-]+)"],
        "youtube": [r"youtube\.com/@?([\w-]+)", r"youtube\.com/channel/([\w-]+)"],
        "tiktok": [r"tiktok\.com/@([\w.-]+)"],
        "github": [r"github\.com/([\w-]+)"],
        "discord": [r"discord\.(gg|com)/([\w-]+)"],
    }
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for platform, patterns in social_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, href, re.I)
                if match:
                    social_links[platform] = {
                        "handle": match.group(1),
                        "url": href,
                    }
    
    # === Section count (approximate "screens") ===
    sections = soup.find_all(["section"])
    section_count = len(sections) if sections else len(h2s)
    
    # === Structure summary ===
    structure_parts = []
    if nav_links:
        structure_parts.append(f"导航栏: {' / '.join(nav_links[:8])}")
    if h1s:
        structure_parts.append(f"首屏: {h1s[0][:50]}")
    for h in h2s[:8]:
        structure_parts.append(h)
    if has_pricing:
        structure_parts.append("💰 定价页面")
    if has_faq:
        structure_parts.append("❓ FAQ")
    if has_logos:
        structure_parts.append("🏢 企业 Logo 墙")
    if has_testimonials or has_case_study:
        structure_parts.append("📝 用户案例/评价")
    
    # Construct Wayback iframe-safe preview URL from timestamp + original domain
    preview_url = ""
    if "web.archive.org" in url:
        # Extract original URL from archive URL: .../web/{ts}id_/https://domain/
        orig_match = re.search(r"/web/\d+(?:id_)?/(.+)$", url)
        if orig_match:
            original_url = orig_match.group(1)
            preview_url = f"https://web.archive.org/web/{timestamp}if_/{original_url}"

    return {
        "timestamp": timestamp,
        "date": date_str,
        "archive_url": url,
        "preview_url": preview_url,
        "slogan": slogan[:100],
        "title": title[:100],
        "meta_description": meta_desc,
        "nav_links": nav_links,
        "headings_h1": h1s,
        "headings_h2": h2s,
        "section_count": section_count,
        "structure_summary": structure_parts,
        "features": {
            "pricing": has_pricing,
            "blog": has_blog,
            "docs": has_docs,
            "changelog": has_changelog,
            "faq": has_faq,
            "trial": has_trial,
            "demo": has_demo,
            "logos": has_logos,
            "testimonials": has_testimonials,
            "case_study": has_case_study,
            "privacy": has_privacy,
            "terms": has_terms,
        },
        "social_links": social_links,
    }


def _detect_changes(snapshots: list, current: dict) -> list:
    """检测各时间点之间的关键变化"""
    all_points = [s for s in snapshots if "error" not in s] + ([current] if "error" not in current else [])
    if len(all_points) < 2:
        return []
    
    changes = []
    for i in range(1, len(all_points)):
        prev = all_points[i - 1]
        curr = all_points[i]
        change_items = []
        
        # Slogan change
        if prev.get("slogan", "") != curr.get("slogan", ""):
            change_items.append(f"Slogan 变更: \"{curr.get('slogan', '')[:50]}\"")
        
        # New features
        prev_features = prev.get("features", {})
        curr_features = curr.get("features", {})
        for key, label in [
            ("pricing", "定价页"), ("blog", "博客"), ("docs", "文档"),
            ("changelog", "Changelog"), ("faq", "FAQ"), ("trial", "免费试用"),
            ("demo", "Demo"), ("logos", "企业 Logo 墙"), ("case_study", "用户案例"),
        ]:
            if curr_features.get(key) and not prev_features.get(key):
                change_items.append(f"新增: {label}")
        
        # Social links change
        prev_social = set(prev.get("social_links", {}).keys())
        curr_social = set(curr.get("social_links", {}).keys())
        new_social = curr_social - prev_social
        if new_social:
            change_items.append(f"社媒外链新增: {', '.join(new_social)}")
        
        # Section count change
        prev_count = prev.get("section_count", 0)
        curr_count = curr.get("section_count", 0)
        if curr_count > prev_count + 2:
            change_items.append(f"页面板块增加: {prev_count} → {curr_count}")
        
        if change_items:
            changes.append({
                "from_date": prev.get("date", ""),
                "to_date": curr.get("date", ""),
                "changes": change_items,
            })
    
    return changes
