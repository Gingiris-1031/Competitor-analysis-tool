"""Evidence-backed OSS growth channel and content attribution."""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from urllib.parse import urlparse

from .i18n import _T


_CHANNEL_DOMAINS = {
    "reddit": ("reddit.com",),
    "hacker_news": ("news.ycombinator.com",),
    "product_hunt": ("producthunt.com",),
    "x": ("x.com", "twitter.com"),
    "instagram": ("instagram.com",),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "linkedin": ("linkedin.com",),
    "developer_media": ("medium.com", "dev.to", "daily.dev", "qiita.com", "zenn.dev"),
    "github": ("github.com",),
}

_SEARCH_PLANS = (
    ("community", 'site:reddit.com OR site:news.ycombinator.com "{project}"'),
    ("launch", 'site:producthunt.com "{project}"'),
    ("social", 'site:x.com OR site:linkedin.com "{project}"'),
    ("short_video", 'site:instagram.com OR site:tiktok.com "{project}"'),
    ("video", 'site:youtube.com/watch "{project}"'),
    ("editorial", '"{project}" tutorial OR install OR review'),
    ("trending", '"{project}" "GitHub Trending" OR stars'),
    ("localized", '"{project}" Japanese OR Chinese OR Spanish'),
)

_DATE_RE = re.compile(r"\b(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _classify_channel(url: str) -> str:
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    for channel, domains in _CHANNEL_DOMAINS.items():
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            return channel
    return "editorial"


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    return url.split("#", 1)[0].split("?tl=", 1)[0]


def _published_date(text: str) -> str:
    match = _DATE_RE.search(text or "")
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _content_format(channel: str, url: str, text: str) -> str:
    low = f"{url} {text}".lower()
    if channel in {"instagram", "tiktok"} or "/shorts/" in low or "/reel/" in low:
        return "short_video"
    if channel == "youtube":
        return "tutorial" if any(k in low for k in ("tutorial", "install", "guide", "review")) else "video"
    if channel in {"reddit", "hacker_news"}:
        return "discussion"
    if channel == "product_hunt":
        return "launch"
    if channel == "github":
        return "repo_event"
    return "article"


def _hook(text: str) -> str:
    low = (text or "").lower()
    if any(k in low for k in ("free", "$0", "open source", "open-source")):
        return _T("Free/open-source alternative", "免费/开源替代")
    if any(k in low for k in ("install", "setup", "tutorial", "guide", "how to")):
        return _T("Installation and reproducible workflow", "安装与可复现工作流")
    if any(k in low for k in ("trending", "stars", "#1")):
        return _T("GitHub momentum and social proof", "GitHub 热度与社会证明")
    if any(k in low for k in ("vs ", "compare", "comparison", "alternative")):
        return _T("Comparison and category positioning", "对比与品类定位")
    return _T("Product capability and outcome demo", "产品能力与结果演示")


def _evidence_score(item: dict, project: str) -> int:
    text = f"{item.get('title', '')} {item.get('description', '')}"
    score = 0
    if item.get("channel") in _CHANNEL_DOMAINS:
        score += 2
    if _normalized(project) in _normalized(text):
        score += 2
    if item.get("channel") in {"reddit", "hacker_news", "youtube", "developer_media", "github"}:
        score += 1
    if item.get("url"):
        score += 1
    if item.get("published_at"):
        score += 1
    return min(score, 8)


def _normalize_result(
    result: dict,
    project: str,
    query_family: str,
    canonical_owner: str = "",
    canonical_repo: str = "",
) -> dict | None:
    title = (result.get("title") or "").strip()
    description = (result.get("description") or "").strip()
    url = _canonical_url((result.get("url") or "").strip())
    if not title or not url:
        return None
    combined = f"{title} {description} {url}"
    if _normalized(project) not in _normalized(combined):
        return None
    channel = _classify_channel(url)
    if channel == "github" and canonical_owner and canonical_repo:
        path_parts = [part for part in urlparse(url).path.split("/") if part]
        if len(path_parts) < 2 or (
            path_parts[0].lower(), path_parts[1].removesuffix(".git").lower()
        ) != (canonical_owner.lower(), canonical_repo.lower()):
            return None
    item = {
        "channel": channel,
        "title": title[:180],
        "url": url,
        "published_at": _published_date(combined),
        "format": _content_format(channel, url, combined),
        "hook": _hook(combined),
        "description": description[:300],
        "query_family": query_family,
        "source_type": "original_post" if channel != "editorial" else "independent",
    }
    score = _evidence_score(item, project)
    item["evidence_score"] = score
    item["confidence"] = "high" if score >= 6 else "medium" if score >= 3 else "low"
    return item


def _stage_summary(github_oss: dict, evidence: list[dict]) -> list[dict]:
    history = github_oss.get("star_history") or []
    stages = []
    created = github_oss.get("created_at") or ""
    if created:
        stages.append({
            "stage": "preparation",
            "period": created,
            "label": _T("Repository preparation", "发布准备"),
            "signal": _T("Repository created; conversion assets and launch readiness should be checked in early commits.",
                         "仓库创建；需结合早期提交检查首屏、Demo 与分享卡片等转化资产。"),
            "confidence": "high",
        })
    if history:
        peak = max(history, key=lambda row: row.get("gain", 0))
        stages.append({
            "stage": "breakout",
            "period": peak.get("month", ""),
            "label": _T("Peak growth window", "爆发增长窗口"),
            "signal": _T(f"Largest sampled monthly gain: {peak.get('gain', 0):,} stars.",
                         f"采样曲线最大单月新增：{peak.get('gain', 0):,} stars。"),
            "confidence": "medium",
        })
    localized = [item for item in evidence if item.get("query_family") == "localized"]
    if localized:
        stages.append({
            "stage": "localization_seo",
            "period": _T("After breakout", "爆发后"),
            "label": _T("Localization and search capture", "本地化与搜索承接"),
            "signal": _T(f"Found {len(localized)} localized or regional content signals.",
                         f"发现 {len(localized)} 条本地化或区域内容信号。"),
            "confidence": "medium",
        })
    return stages


async def analyze_oss_growth_attribution(product_name: str, github_oss: dict) -> dict:
    """Discover representative channel content and align it to GitHub growth stages."""
    if not isinstance(github_oss, dict) or not github_oss.get("found"):
        return {"available": False, "note": _T("No canonical GitHub repository found.", "未找到可验证的 GitHub 主仓库。")}

    owner = github_oss.get("owner", "")
    repo = github_oss.get("repo", "")
    project = product_name or repo
    # Lazy import keeps the deterministic normalization helpers testable without
    # loading the application's HTTP stack.
    from .web_search import brave_search

    async def _search(family: str, template: str):
        query = template.format(project=project, owner=owner, repo=repo)
        try:
            return family, await brave_search(query, count=5)
        except Exception:
            return family, []

    results = await asyncio.gather(*[_search(family, query) for family, query in _SEARCH_PLANS])
    evidence = []
    seen = set()
    for family, rows in results:
        for row in rows:
            item = _normalize_result(row, project, family, owner, repo)
            if not item or item["url"] in seen or item["evidence_score"] < 3:
                continue
            seen.add(item["url"])
            evidence.append(item)

    evidence.sort(key=lambda item: (-item["evidence_score"], item["channel"], item["title"]))
    evidence = evidence[:24]
    counts = Counter(item["channel"] for item in evidence)
    searched_channels = list(_CHANNEL_DOMAINS.keys())
    unsupported = [channel for channel in searched_channels if not counts.get(channel)]

    return {
        "available": True,
        "method": "public_evidence_temporal_attribution",
        "attribution_type": "directional",
        "uncertainty": "±10–15 percentage points without first-party traffic, UTM, or referral logs",
        "channel_counts": dict(counts),
        "key_content": evidence,
        "stages": _stage_summary(github_oss, evidence),
        "unsupported_channels": unsupported,
        "source_note": _T(
            "Links and public facts are observed; channel impact is inferred. Search snippets are discovery evidence, not referral analytics.",
            "链接与公开事实为观察值；渠道影响属于推断。搜索摘要用于发现内容，不等同于 referral analytics。",
        ),
    }
