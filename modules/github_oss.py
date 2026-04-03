"""GitHub OSS 分析模块 — Stars 增长历史、贡献者、发版、里程碑"""
import asyncio
import math
import os
import re
import httpx

_GH_API = "https://api.github.com"
_GH_STAR_LIMIT = 400   # GitHub API only returns up to page 400 for stargazers
_SAMPLE_PAGES  = 10    # pages to sample in parallel


def _gh_headers(star_json: bool = False) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    accept = "application/vnd.github.star+json" if star_json else "application/vnd.github+json"
    h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def analyze_github_oss(domain: str, product_name: str,
                              website_social_links: dict = None) -> dict:
    """分析开源产品 GitHub 数据：Stars 增长曲线、贡献者、发版历史"""

    # ── Step 1: Find repo (Brave Search → website hint → domain guess) ──
    owner, repo = await _resolve_repo(domain, product_name, website_social_links or {})
    if not (owner and repo):
        return {"found": False, "note": "未找到 GitHub 仓库，可能不是开源项目"}

    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        # ── Step 2: Fetch core stats + star history + contributors in parallel ──
        repo_task  = _fetch_repo_info(client, owner, repo)
        rel_task   = _fetch_latest_release(client, owner, repo)
        stats_results = await asyncio.gather(repo_task, rel_task, return_exceptions=True)

        repo_info      = stats_results[0] if isinstance(stats_results[0], dict) else {}
        latest_release = stats_results[1] if isinstance(stats_results[1], dict) else None

        if not repo_info.get("stars"):
            return {"found": False, "note": f"GitHub 仓库 {owner}/{repo} 无法访问"}

        stars = repo_info["stars"]

        # ── Step 3: Star history via parallel page sampling ──
        star_history = await _sample_star_history(client, owner, repo, stars)

    milestones = _calc_milestones(star_history, stars)
    insights   = _gen_insights(repo_info, star_history, milestones)

    return {
        "found":          True,
        "repo_url":       f"https://github.com/{owner}/{repo}",
        "owner":          owner,
        "repo":           repo,
        "description":    repo_info.get("description", ""),
        "stars":          stars,
        "forks":          repo_info.get("forks", 0),
        "open_issues":    repo_info.get("open_issues", 0),
        "contributors":   repo_info.get("contributors", 0),
        "created_at":     repo_info.get("created_at", ""),
        "pushed_at":      repo_info.get("pushed_at", ""),
        "language":       repo_info.get("language", ""),
        "license":        repo_info.get("license", ""),
        "topics":         repo_info.get("topics", []),
        "latest_release": latest_release,
        "star_history":   star_history,
        "milestones":     milestones,
        "insights":       insights,
        "data_note":      f"Stars history covers first {_GH_STAR_LIMIT * 100:,} / {stars:,} stars" if stars > _GH_STAR_LIMIT * 100 else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Repo discovery
# ─────────────────────────────────────────────────────────────────────────────

async def _resolve_repo(domain: str, product_name: str, hints: dict) -> tuple:
    """Return (owner, repo) or (None, None)."""
    brand = re.sub(r'\.[a-z]{2,6}$', '', domain.lower().replace("www.", ""))

    # 1. Website hint (github social link) — most reliable
    gh_hint = hints.get("github", {}).get("url", "")
    if gh_hint:
        owner, repo = _parse_gh_url(gh_hint)
        if owner and repo:
            # Validate: skip obvious non-main repos (awesome-lists, docs, etc.)
            low = repo.lower()
            if not any(skip in low for skip in ("awesome", "docs", "wiki", "example", "template", "demo")):
                return owner, repo
            # Might be secondary repo → still try top-starred under same org
        if owner:
            repo = await _find_top_repo(owner)
            if repo:
                return owner, repo

    # 2. Brave Search
    try:
        from .web_search import brave_search
    except ImportError:
        try:
            from web_search import brave_search
        except ImportError:
            brave_search = None

    if brave_search:
        candidates = []  # list of (owner, repo) to validate
        for query in [
            f'"{domain}" site:github.com',
            f'"{product_name}" site:github.com',
            f'"{brand}" open source github repository',
        ]:
            results = await brave_search(query, count=5)
            for r in results:
                o, rep = _parse_gh_url(r.get("url", ""))
                skip_orgs = {"topics", "orgs", "sponsors", "trending", "marketplace"}
                if o and rep and o.lower() not in skip_orgs:
                    low_rep = rep.lower()
                    # Deprioritize obvious secondary repos
                    if any(skip in low_rep for skip in ("awesome", "docs", "wiki", "example", "template")):
                        candidates.append((o, rep, "secondary"))
                    else:
                        candidates.append((o, rep, "primary"))

        # Try primary candidates first (max 3 to avoid timeout), then secondary
        seen = set()
        for priority in ("primary", "secondary"):
            checked = 0
            for o, rep, prio in candidates:
                if prio != priority or (o, rep) in seen:
                    continue
                if checked >= 3:  # Limit star-validation calls to avoid timeout
                    break
                seen.add((o, rep))
                checked += 1
                # Quick star check: reject if < 200 stars (likely wrong repo)
                stars = await _get_repo_stars(o, rep)
                if stars is None or stars >= 200:
                    # If low stars but we have an owner, try top repo under that org
                    if stars is not None and stars < 200:
                        top = await _find_top_repo(o)
                        if top:
                            return o, top
                    return o, rep

    # 3. GitHub Search API — reliable fallback when Brave Search misses
    result = await _github_search_api(product_name, brand)
    if result[0]:
        return result

    return None, None


async def _github_search_api(product_name: str, brand: str) -> tuple:
    """Search GitHub repositories API as final fallback. Returns (owner, repo) or (None, None)."""
    queries = list(dict.fromkeys([product_name, brand]))  # deduplicate, product_name first
    skip_repos = {"awesome", "docs", "wiki", "example", "template", "demo", "website", "landing"}

    try:
        async with httpx.AsyncClient(timeout=8) as c:
            for q in queries:
                resp = await c.get(
                    f"{_GH_API}/search/repositories",
                    headers=_gh_headers(),
                    params={"q": q, "sort": "stars", "order": "desc", "per_page": 5},
                )
                if resp.status_code != 200:
                    continue
                items = resp.json().get("items", [])
                for item in items:
                    full_name = item.get("full_name", "")
                    stars = item.get("stargazers_count", 0)
                    if "/" not in full_name or stars < 100:
                        continue
                    owner, repo = full_name.split("/", 1)
                    # Skip obvious non-product repos
                    if any(s in repo.lower() for s in skip_repos):
                        continue
                    # Relevance check: repo or description should mention brand/product
                    desc = (item.get("description") or "").lower()
                    repo_lower = repo.lower()
                    brand_lower = brand.lower()
                    name_lower = product_name.lower()
                    if (brand_lower in repo_lower or name_lower in repo_lower
                            or brand_lower in desc or name_lower in desc):
                        return owner, repo
    except Exception:
        pass
    return None, None


async def _get_repo_stars(owner: str, repo: str) -> int | None:
    """Quick check: fetch star count for a repo. Returns None on error."""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.get(
                f"{_GH_API}/repos/{owner}/{repo}",
                headers=_gh_headers(),
            )
            if resp.status_code == 200:
                return resp.json().get("stargazers_count", 0)
    except Exception:
        pass
    return None


def _parse_gh_url(url: str) -> tuple:
    """Parse github.com/{owner}/{repo} → (owner, repo) or (owner, None)."""
    m = re.match(r'(?:https?://)?github\.com/([A-Za-z0-9_.-]+)(?:/([A-Za-z0-9_.-]+))?', url or "")
    if not m:
        return None, None
    owner = m.group(1)
    repo  = m.group(2)
    if repo:
        repo = repo.rstrip('/')
        if repo.lower() in {"issues", "pulls", "wiki", "releases", "actions", "discussions",
                            "blob", "tree", "commit", "compare", "stargazers", "network"}:
            repo = None
    return owner, repo


async def _find_top_repo(org: str) -> str | None:
    """Return the most starred repo name under an org."""
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            resp = await c.get(
                f"{_GH_API}/orgs/{org}/repos",
                headers=_gh_headers(),
                params={"sort": "stargazers", "direction": "desc", "per_page": 1},
            )
            if resp.status_code == 200:
                items = resp.json()
                if items:
                    return items[0].get("name")
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Data fetchers
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_repo_info(client: httpx.AsyncClient, owner: str, repo: str) -> dict:
    resp = await client.get(f"{_GH_API}/repos/{owner}/{repo}", headers=_gh_headers())
    if resp.status_code != 200:
        return {}
    d = resp.json()

    # Contributor count via Link header (1 request)
    contributors = 0
    try:
        cr = await client.get(
            f"{_GH_API}/repos/{owner}/{repo}/contributors",
            headers=_gh_headers(),
            params={"per_page": 1, "anon": "true"},
        )
        link = cr.headers.get("Link", "")
        m = re.search(r'page=(\d+)>; rel="last"', link)
        contributors = int(m.group(1)) if m else (1 if cr.status_code == 200 else 0)
    except Exception:
        pass

    return {
        "stars":       d.get("stargazers_count", 0),
        "forks":       d.get("forks_count", 0),
        "open_issues": d.get("open_issues_count", 0),
        "contributors": contributors,
        "created_at":  d.get("created_at", "")[:10],
        "pushed_at":   d.get("pushed_at", "")[:10],
        "language":    d.get("language", ""),
        "topics":      d.get("topics", []),
        "license":     (d.get("license") or {}).get("spdx_id") or (d.get("license") or {}).get("name", ""),
        "description": (d.get("description") or "")[:200],
    }


async def _fetch_latest_release(client: httpx.AsyncClient, owner: str, repo: str) -> dict | None:
    try:
        resp = await client.get(
            f"{_GH_API}/repos/{owner}/{repo}/releases/latest",
            headers=_gh_headers(),
        )
        if resp.status_code == 200:
            r = resp.json()
            return {
                "tag":  r.get("tag_name", ""),
                "name": r.get("name", ""),
                "date": r.get("published_at", "")[:10],
                "url":  r.get("html_url", ""),
            }
    except Exception:
        pass
    return None


async def _sample_star_history(client: httpx.AsyncClient, owner: str,
                                repo: str, total_stars: int) -> list:
    """Parallel-sample stargazers to build monthly growth curve (< 3s)."""
    if total_stars == 0:
        return []

    per_page = 100
    accessible_pages = min(math.ceil(total_stars / per_page), _GH_STAR_LIMIT)

    # Choose sample pages: always include first and last accessible
    if accessible_pages <= _SAMPLE_PAGES:
        pages = list(range(1, accessible_pages + 1))
    else:
        step = accessible_pages / (_SAMPLE_PAGES - 1)
        pages = sorted(set(
            [1] + [int(round(i * step)) for i in range(1, _SAMPLE_PAGES - 1)] + [accessible_pages]
        ))

    star_h = _gh_headers(star_json=True)

    async def _fetch_page(page: int) -> list:
        try:
            r = await client.get(
                f"{_GH_API}/repos/{owner}/{repo}/stargazers",
                headers=star_h,
                params={"per_page": per_page, "page": page},
            )
            if r.status_code == 200:
                items = r.json()
                return [
                    {
                        "cumulative": (page - 1) * per_page + i + 1,
                        "month":      item.get("starred_at", "")[:7],
                    }
                    for i, item in enumerate(items)
                    if item.get("starred_at")
                ]
        except Exception:
            pass
        return []

    results = await asyncio.gather(*[_fetch_page(p) for p in pages], return_exceptions=True)
    events  = sorted(
        [e for r in results if isinstance(r, list) for e in r],
        key=lambda x: x["cumulative"],
    )
    if not events:
        return []

    # Aggregate to monthly using linear interpolation between sample points
    monthly = _interpolate_monthly(events, total_stars)
    return monthly


def _interpolate_monthly(events: list, total_stars: int) -> list:
    """Convert sampled (cumulative, month) points to monthly breakdown."""
    if not events:
        return []

    # Build a dict: month → latest cumulative seen at that month
    month_to_cum: dict = {}
    for e in events:
        m, c = e["month"], e["cumulative"]
        if m and m > month_to_cum.get(m, {}).get("c", -1) if isinstance(month_to_cum.get(m), dict) else True:
            month_to_cum[m] = c

    # Sort months
    months = sorted(month_to_cum.keys())
    if not months:
        return []

    # Fill gaps between sampled months via linear interpolation
    from datetime import date, timedelta

    def _month_iter(start: str, end: str):
        y, mo = int(start[:4]), int(start[5:7])
        ey, emo = int(end[:4]), int(end[5:7])
        while (y, mo) <= (ey, emo):
            yield f"{y:04d}-{mo:02d}"
            mo += 1
            if mo > 12:
                mo = 1; y += 1

    all_months = list(_month_iter(months[0], months[-1]))
    sampled = {m: month_to_cum[m] for m in months}
    sm_keys = sorted(sampled.keys())

    result = []
    prev_cum = 0
    for month in all_months:
        if month in sampled:
            cum = sampled[month]
        else:
            # Linear interpolation between nearest sampled points
            before = [k for k in sm_keys if k < month]
            after  = [k for k in sm_keys if k > month]
            if before and after:
                b_m, b_c = before[-1], sampled[before[-1]]
                a_m, a_c = after[0],  sampled[after[0]]
                # months between
                def _mdiff(m1, m2):
                    y1, mo1 = int(m1[:4]), int(m1[5:7])
                    y2, mo2 = int(m2[:4]), int(m2[5:7])
                    return (y2 - y1) * 12 + (mo2 - mo1)
                total_gap = _mdiff(b_m, a_m)
                partial   = _mdiff(b_m, month)
                t = partial / total_gap if total_gap else 0
                cum = int(b_c + t * (a_c - b_c))
            elif before:
                cum = sampled[before[-1]]
            else:
                cum = sampled[after[0]]

        gain = max(0, cum - prev_cum)
        result.append({"month": month, "cumulative": min(cum, total_stars), "gain": gain})
        prev_cum = cum

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Milestones & insights
# ─────────────────────────────────────────────────────────────────────────────

_MILESTONE_STARS = [100, 500, 1_000, 5_000, 10_000, 20_000, 50_000, 100_000]

def _calc_milestones(history: list, total_stars: int) -> list:
    milestones = []
    for target in _MILESTONE_STARS:
        if target > total_stars * 1.05:
            break
        hit = next((h for h in history if h["cumulative"] >= target), None)
        if hit:
            milestones.append({"stars": target, "month": hit["month"],
                                "label": _fmt_stars(target)})
    return milestones


def _fmt_stars(n: int) -> str:
    if n >= 1_000:
        return f"{n // 1_000}K"
    return str(n)


def _gen_insights(repo_info: dict, star_history: list, milestones: list) -> list:
    insights = []
    stars     = repo_info.get("stars", 0)
    forks     = repo_info.get("forks", 0)
    issues    = repo_info.get("open_issues", 0)
    created   = repo_info.get("created_at", "")
    license_  = repo_info.get("license", "")

    if stars >= 50_000:
        insights.append(f"⭐ {stars:,} GitHub Stars — 顶级开源项目，开发者社区影响力极高")
    elif stars >= 10_000:
        insights.append(f"⭐ {stars:,} GitHub Stars — 已进入开源主流视野")
    elif stars >= 1_000:
        insights.append(f"⭐ {stars:,} GitHub Stars — 有稳定开发者受众")

    if forks and stars:
        fork_ratio = forks / stars
        if fork_ratio > 0.1:
            insights.append(f"🍴 Fork 率 {fork_ratio:.0%}（{forks:,} forks），二次开发活跃，ecosystem 潜力强")

    if star_history:
        gains = [h["gain"] for h in star_history if h.get("gain", 0) > 0]
        if gains:
            peak_gain = max(gains)
            peak_month = next(h["month"] for h in star_history if h.get("gain") == peak_gain)
            if peak_gain >= 1000:
                insights.append(f"🚀 增长峰值：{peak_month} 单月新增 {peak_gain:,} stars（对应重大发布事件）")

    if milestones:
        first_k = next((m for m in milestones if m["stars"] >= 1_000), None)
        if first_k and created:
            from datetime import datetime
            try:
                created_dt = datetime.strptime(created[:7], "%Y-%m")
                hit_dt     = datetime.strptime(first_k["month"], "%Y-%m")
                months = (hit_dt.year - created_dt.year) * 12 + (hit_dt.month - created_dt.month)
                if months <= 3:
                    insights.append(f"⚡ {months} 个月内突破 1K Stars（爆发式冷启动）")
                elif months <= 12:
                    insights.append(f"📈 {months} 个月达到 1K Stars（健康增长曲线）")
            except Exception:
                pass

    if license_:
        if "MIT" in license_ or "Apache" in license_:
            insights.append(f"📄 {license_} 协议 — 商业友好，有利于企业采用")
        elif "GPL" in license_ or "AGPL" in license_:
            insights.append(f"📄 {license_} 协议 — Copyleft，SaaS 场景需要商业授权")

    return insights
