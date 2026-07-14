"""报告生成模块 — 整合所有数据源输出结构化报告"""
from datetime import datetime
import json


def _T(lang: str, en: str, zh: str) -> str:
    """Tiny lang switcher — returns English when lang starts with 'en',
    Chinese otherwise. Used by generate_report and its formatters so the
    UI section titles and the auto-generated findings list match the
    chosen report language (Iris 2026-06-25, TAAFT-style leakage audit).
    """
    return en if (lang or "").lower().startswith("en") else zh


def generate_report(product_name: str, url: str, website: dict, social: dict, traffic: dict, producthunt: dict = None, ai_summary: dict = None, growth_deep: dict = None, traffic_peaks: dict = None, propagation: dict = None, growth_strategy: dict = None, lang: str = "zh") -> dict:
    report = {
        "meta": {
            "product_name": product_name,
            "url": url,
            "generated_at": datetime.now().isoformat(),
            "version": "MVP v0.5",
            "lang": lang,
        },
        "sections": {
            "website_analysis": _format_website(website, lang=lang),
            "social_media": _format_social(social, lang=lang),
            "traffic_analysis": _format_traffic(traffic, lang=lang),
            "producthunt": producthunt or {},
            "ai_insights": ai_summary or {},
            "growth_analysis": growth_deep or {},
            "traffic_peaks": traffic_peaks or {},
            "propagation": propagation or {},
            "summary": _generate_summary(product_name, website, social, traffic, producthunt, lang=lang),
            "growth_strategy": growth_strategy or {},
        },
    }
    # Strategy Radar — computed from all sections
    report["sections"]["strategy_radar"] = _compute_strategy_radar(report["sections"], lang)

    # ── 总分总的「总（头条）」：公开增长成熟度分 + Thesis 核心论断 + 时间轴阶段总结 ──
    try:
        report["sections"]["growth_score"] = _compute_growth_score(website, traffic, social, producthunt, lang)
        report["sections"]["thesis"] = _build_thesis(product_name, report["sections"], lang)
        _ws_raw = website.get("website_analysis", website) if isinstance(website, dict) else {}
        from modules.timeline import summarize_evolution
        report["sections"]["evolution_summary"] = summarize_evolution(
            _ws_raw.get("deep_timeline") or website.get("deep_timeline") or [],
            first_seen=_ws_raw.get("first_seen") or website.get("first_seen") or "",
            lang=lang)
        report["sections"]["references"] = _build_references(
            report["sections"], report["meta"]["generated_at"], lang)
    except Exception as _e:
        pass

    return report


def reconcile_github_channel(sections: dict, github_oss: dict) -> None:
    """修 bug：开源分析（github_oss）找到了 GitHub repo，但「账号匹配」(social_media.channels.github)
    因精确匹配 handle 失败而标 detected=False，导致同一份报告里两处对 GitHub 判断不一致
    （AFFiNE report/53b9c7ca：开源分析匹配到 toeverything/affine，账号匹配却不显示 GitHub）。
    以 github_oss 的确凿结果为准，回填 github channel。原地修改 sections。"""
    if not isinstance(github_oss, dict) or not github_oss.get("found"):
        return
    soc = sections.get("social_media")
    if not isinstance(soc, dict):
        return
    ch = soc.get("channels")
    if not isinstance(ch, dict):
        return
    gh = ch.get("github")
    if not isinstance(gh, dict) or gh.get("detected"):
        return  # 已匹配到就不覆盖
    owner = github_oss.get("owner") or ""
    repo = github_oss.get("repo") or ""
    url = github_oss.get("repo_url") or (f"https://github.com/{owner}" if owner else None)
    if not url:
        return
    stars = github_oss.get("stars") or 0
    slug = f"{owner}/{repo}" if owner and repo else (repo or owner)
    gh.update({
        "detected": True,
        "url": url,
        "type": "org" if owner else "user",
        "handle": owner or repo,
        "stars_total": stars,
        "public_repos": gh.get("public_repos") or (1 if repo else 0),
        "followers": github_oss.get("contributors") or gh.get("followers") or 0,
        "note": f"经开源分析匹配到 {slug}",
        "top_repos": gh.get("top_repos") or ([{"name": slug, "stars": stars}] if slug else []),
        "reconciled_from": "github_oss",
    })


def _compute_growth_score(website: dict, traffic: dict, social: dict, producthunt: dict, lang: str = "zh") -> dict:
    """从竞品分析已抓的公开信号算「公开增长成熟度分」（Iris 批准口径）。"""
    from modules import benchmarks as _bm
    combined = dict(traffic or {})
    combined["seo_metrics"] = traffic or {}
    combined["website"] = website or {}
    combined["social"] = social or {}
    combined["producthunt"] = producthunt or {}
    signals = _bm.extract_public_signals(combined)
    return _bm.score_public(signals, lang)


def _build_references(sections: dict, gen_date: str, lang: str = "zh") -> list:
    """Manus 签名：把报告用到的数据源列成 References（来源 + 用途 + 抓取日期），
    提升可信度 + GEO（AI 搜索更爱引用有来源标注的内容）。按 sections 实际有数据的才列。"""
    en = (lang or "").startswith("en")
    date = (gen_date or "")[:10]
    refs = []

    def _has(key, *subkeys):
        v = sections.get(key)
        if not v or not isinstance(v, (dict, list)):
            return bool(v)
        if isinstance(v, list):
            return len(v) > 0
        if subkeys:
            return any(v.get(sk) for sk in subkeys)
        return bool(v)

    def _add(source, cn, en_txt):
        refs.append({"source": source, "used_for": en_txt if en else cn, "date": date})

    if _has("website_analysis", "deep_timeline", "total_snapshots"):
        _add("Wayback Machine CDX API", "官网历史快照与演变分析", "Website history snapshots & evolution")
    if _has("traffic_analysis", "seo_metrics", "domain_rank", "top_keywords"):
        _add("DataForSEO + SEO Review Tools", "流量估算、SEO 指标、关键词、外链", "Traffic estimate, SEO metrics, keywords, backlinks")
    if _has("social_media", "channels"):
        _add("TwitterAPI.io / Brave Search", "社媒矩阵与官方账号识别", "Social matrix & official handle discovery")
    if _has("propagation"):
        _add("Social propagation harvest", "传播链路与关键帖", "Propagation chain & key posts")
    if _has("producthunt", "found", "posts", "launched"):
        _add("Product Hunt API", "Product Hunt 发布记录", "Product Hunt launch history")
    if _has("github_oss", "stars", "star_count"):
        _add("GitHub API", "开源社区与 star 信号", "Open-source community & star signals")
    if _has("traffic_peaks"):
        _add("SerpAPI (Google Trends)", "流量峰值检测与拐点归因", "Traffic peak detection & inflection attribution")
    if _has("pricing"):
        _add("On-site pricing scrape", "定价结构", "Pricing structure")
    return refs


def _build_thesis(product_name: str, sections: dict, lang: str = "zh") -> dict:
    """核心论断 Thesis（判断先行）：综合成熟度分 + 最强/最该补维度 → 一句话判断。"""
    zh = not (lang or "").startswith("en")
    gs = sections.get("growth_score") or {}
    score = gs.get("overall_score", 0)
    dims = gs.get("dimensions") or []
    strong = max(dims, key=lambda d: d.get("subscore", 0), default=None) if dims else None
    weak = min(dims, key=lambda d: d.get("subscore", 0), default=None) if dims else None
    # 维度标签按语言本地化（key 语言中性；避免 EN thesis 混中文）
    _dim_label = {
        "traffic": ("流量体量", "Traffic"), "seo": ("SEO 强度", "SEO strength"),
        "commercialization": ("商业化成熟度", "Commercialization"),
        "distribution": ("分发/社媒矩阵", "Distribution"), "momentum": ("社区/势能", "Community & momentum"),
    }

    def _dl(d):
        if not d:
            return ""
        return _dim_label.get(d.get("key"), (d.get("label", ""), d.get("label", "")))[0 if zh else 1]

    if zh:
        band = ("强（护城河成型）" if score >= 80 else "健康（可持续）" if score >= 65
                else "成长中（有单点强项）" if score >= 45 else "早期/虚火（地基薄）")
        headline = f"{product_name} 公开增长成熟度 {score}/100（{band}）。"
        if strong and weak:
            headline += f"最强项：{_dl(strong)}；最该补的洞：{_dl(weak)}。"
        headline += "详见下文分维度诊断。"
    else:
        band = ("Strong (moat forming)" if score >= 80 else "Healthy (sustainable)" if score >= 65
                else "Growing (one strong lever)" if score >= 45 else "Early / fragile foundation")
        headline = f"{product_name} public growth maturity: {score}/100 ({band}). "
        if strong and weak:
            headline += f"Strongest: {_dl(strong)}; biggest gap: {_dl(weak)}. "
        headline += "See the dimensional diagnosis below."
    return {"score": score, "band": band, "headline": headline,
            "strongest": strong, "weakest": weak}


def _format_website(data: dict, lang: str = "zh") -> dict:
    current = data.get("current_site", {})
    return {
        "title": _T(lang, "Website Evolution Analysis", "官网演变分析"),
        "domain": data.get("domain", ""),
        "first_seen": data.get("first_seen", "N/A"),
        "total_snapshots": data.get("total_snapshots", 0),
        "deep_timeline": data.get("deep_timeline", []),
        "current": current,
        "key_changes": data.get("key_changes", []),
    }


def _format_social(data: dict, lang: str = "zh") -> dict:
    return {
        "title": _T(lang, "Social Media Channels", "社交媒体渠道分析"),
        "brand": data.get("brand", ""),
        "channels": data.get("channels", {}),
        "propagation_metrics": data.get("propagation_metrics", {}),
        "key_posts": data.get("key_posts", []),
    }


def _format_traffic(data: dict, lang: str = "zh") -> dict:
    # DataForSEO returns backlinks as a nested dict
    # ({cost, backlinks: N, referring_domains, domain_rank, referring_ips, ...}).
    # SRT / flat callers return it as a scalar int. seo_metrics must expose
    # scalars to the UI — otherwise the frontend fallback renders [object
    # Object]. Normalize here.
    _bl = data.get("backlinks")
    if isinstance(_bl, dict):
        _bl_count = _bl.get("backlinks")
        # Use explicit None check — a legitimate 0 from DataForSEO should not
        # be silently replaced by SRT's value.
        _rd_nested = _bl.get("referring_domains")
        _rd_count = _rd_nested if _rd_nested is not None else data.get("referring_domains")
    else:
        _bl_count = _bl
        _rd_count = data.get("referring_domains")

    seo_metrics: dict = {}
    for k in ("domain_authority", "spam_score", "indexed_pages", "tld_distribution",
              "organic_traffic_estimate"):
        if data.get(k) is not None:
            seo_metrics[k] = data[k]
    if _bl_count is not None:
        seo_metrics["backlinks"] = _bl_count
    if _rd_count is not None:
        seo_metrics["referring_domains"] = _rd_count

    result = {
        "title": _T(lang, "Traffic & SEO Analysis", "流量与 SEO 分析"),
        "source": "DataForSEO + SEO Review Tools",
        "domain_rank": data.get("domain_rank", {}),
        "backlinks": data.get("backlinks", {}),
        "top_keywords": data.get("top_keywords", {}),
        "historical": data.get("historical", {}),
        "growth_analysis": data.get("growth_analysis", {}),
        "total_cost": data.get("total_cost", 0),
        # Merged SEO metrics (DA, spam score, fallback traffic/backlinks).
        # IMPORTANT: all values are scalars so the UI can render them directly.
        "seo_metrics": seo_metrics,
    }
    # Pass through the canonical-domain annotation from dataforseo.analyze_domain
    # (e.g. "notion.so redirects to notion.com") so both the UI and the
    # markdown export can disclose which domain the SEO numbers describe.
    if data.get("redirect_note"):
        result["redirect_note"] = data["redirect_note"]
        result["queried_domain"] = data.get("queried_domain")
    return result


def _generate_summary(name: str, website: dict, social: dict, traffic: dict, producthunt: dict = None, lang: str = "zh") -> dict:
    findings = []
    cs = website.get("current_site", {})
    features = cs.get("features", {})

    if features.get("pricing"):
        findings.append(_T(lang,
            f"✅ {name} has a pricing page — product is monetized",
            f"✅ {name} 已有定价页面，产品已商业化"))
    if features.get("blog"):
        findings.append(_T(lang,
            "✅ Has a blog / content section — content marketing in motion",
            "✅ 有博客/内容板块，内容营销已启动"))
    if features.get("docs"):
        findings.append(_T(lang,
            "✅ Has a docs site — developer experience is taken seriously",
            "✅ 有文档站点，开发者体验完善"))
    if features.get("trial") or features.get("demo"):
        findings.append(_T(lang,
            "✅ Has a free trial / demo entry point",
            "✅ 有免费试用/Demo 入口"))
    if features.get("logos"):
        findings.append(_T(lang,
            "✅ Customer logo wall present — B2B trust signal",
            "✅ 有企业客户 Logo 墙，B2B 信任背书"))
    if not features.get("changelog"):
        findings.append(_T(lang,
            "⚠️ No changelog detected — keep an eye on shipping cadence",
            "⚠️ 未检测到 Changelog，建议关注产品迭代节奏"))

    # Social
    channels = social.get("channels", {})
    detected = [k for k, v in channels.items() if v.get("detected")]
    manual_check = [k for k, v in channels.items() if v.get("detected") is None]
    not_found = [k for k, v in channels.items() if v.get("detected") is False]

    if detected:
        findings.append(_T(lang,
            f"📱 Confirmed channels: {', '.join(detected)}",
            f"📱 已确认渠道: {', '.join(detected)}"))
    if not_found:
        findings.append(_T(lang,
            f"❌ Not detected: {', '.join(not_found)}",
            f"❌ 未检测到: {', '.join(not_found)}"))
    if manual_check:
        findings.append(_T(lang,
            f"🔍 Needs manual check: {', '.join(manual_check)}",
            f"🔍 需手动确认: {', '.join(manual_check)}"))

    # Key changes
    changes = website.get("key_changes", [])
    if changes:
        latest = changes[-1] if changes else None
        if latest:
            change_list = "; ".join(latest["changes"][:3])
            findings.append(_T(lang,
                f"📊 Recent change ({latest['from_date']} → {latest['to_date']}): {change_list}",
                f"📊 最近变化 ({latest['from_date']} → {latest['to_date']}): {change_list}"))

    # Product Hunt
    ph = producthunt or {}
    if ph.get("found"):
        findings.append(f"🏆 Product Hunt: {ph['launch_date']} launch, ⬆{ph['votes']} votes, 💬{ph['comments']} comments")
        if ph.get("reviews_rating"):
            findings.append(_T(lang,
                f"⭐ PH rating: {ph['reviews_rating']:.1f} ({ph.get('reviews_count', 0)} reviews)",
                f"⭐ PH 评分: {ph['reviews_rating']:.1f} ({ph.get('reviews_count', 0)} reviews)"))

    # Social links on website
    social_on_site = cs.get("social_links", {})
    if social_on_site:
        findings.append(_T(lang,
            f"🔗 Social links on site: {', '.join(social_on_site.keys())}",
            f"🔗 官网社媒链接: {', '.join(social_on_site.keys())}"))

    return {
        "title": _T(lang, "Overall Assessment", "综合评估"),
        "findings": findings,
    }


def _thesis_markdown(sections: dict, en: bool = False) -> str:
    """总分总的「总」——报告顶部的核心论断 + 公开分 + 商业化演变节奏（Markdown）。"""
    thesis = sections.get("thesis") or {}
    gs = sections.get("growth_score") or {}
    evo = sections.get("evolution_summary") or ""
    if not thesis.get("headline"):
        return ""
    dim_label = {
        "traffic": ("流量体量", "Traffic"), "seo": ("SEO 强度", "SEO strength"),
        "commercialization": ("商业化", "Commercialization"),
        "distribution": ("分发/社媒", "Distribution"), "momentum": ("社区/势能", "Community & momentum"),
    }
    dot = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    lights = " · ".join(
        f"{dot.get(d.get('grade'), '⚪')} {dim_label.get(d.get('key'), (d.get('label', ''), d.get('label', '')))[1 if en else 0]}"
        for d in gs.get("dimensions", []))
    out = []
    if en:
        out.append("## Verdict — Public Growth Maturity\n")
        out.append(f"**{thesis['headline']}**\n")
        if lights:
            out.append(lights + "\n")
        if evo:
            out.append(f"**Commercialization rhythm:** {evo}\n")
    else:
        out.append("## 核心论断 — 公开增长成熟度\n")
        out.append(f"**{thesis['headline']}**\n")
        if lights:
            out.append(lights + "\n")
        if evo:
            out.append(f"**商业化演变节奏：** {evo}\n")
    return "\n".join(out) + "\n"


def report_to_markdown(report: dict) -> str:
    """Render the structured report dict as Markdown.

    Iris 2026-06-25: localized end-to-end so the Export-MD output matches
    the user's chosen language. The lang is read from report["meta"]["lang"]
    (set by generate_report). Falls back to 'zh' when missing.
    """
    meta = report["meta"]
    s = report["sections"]
    lang = (meta.get("lang") or "zh").lower()

    if lang.startswith("en"):
        md = f"""# Competitor Research Report: {meta['product_name']}

> Generated at: {meta['generated_at'][:19]}
> Target URL: {meta['url']}
> Version: {meta['version']}

---

{_thesis_markdown(s, True)}## 1. Website Evolution Analysis 🔍

> 🔍 **Wayback Machine exclusive data** — deep evolution analysis across multi-year historical snapshots

"""
    else:
        md = f"""# 竞品调研报告：{meta['product_name']}

> 生成时间：{meta['generated_at'][:19]}
> 目标网址：{meta['url']}
> 版本：{meta['version']}

---

{_thesis_markdown(s, False)}## 1. 官网演变分析 🔍

> 🔍 **Wayback Machine 独家数据** — 基于多年历史快照的深度演变分析

"""
    ws = s["website_analysis"]
    md += _T(lang, f"**Domain**: {ws['domain']}  \n", f"**域名**：{ws['domain']}  \n")
    md += _T(lang, f"**First seen**: {ws['first_seen']}  \n", f"**首次出现**：{ws['first_seen']}  \n")
    md += _T(lang, f"**Total snapshots**: {ws['total_snapshots']}  \n\n", f"**历史快照数**：{ws['total_snapshots']}  \n\n")

    # Timeline table
    timeline = ws.get("deep_timeline", [])
    current = ws.get("current", {})
    if timeline or current:
        all_points = [t for t in timeline if not t.get("error") and t.get("date")] + ([current] if current and "error" not in current else [])
        if all_points:
            md += _T(lang, "### Website Evolution Timeline\n\n", "### 官网演变时间线\n\n")
            md += _T(lang, "| Dimension |", "| 维度 |")
            for p in all_points:
                label = _T(lang, "Current", "当前") if p.get("is_current") else p.get("date", "")
                md += f" {label} |"
            md += "\n|------|" + "------|" * len(all_points) + "\n"

            # Slogan row
            md += "| Slogan |"
            for p in all_points:
                md += f" {p.get('slogan', 'N/A')[:40]} |"
            md += "\n"

            # Structure row
            md += _T(lang, "| Site Structure |", "| 官网结构 |")
            for p in all_points:
                parts = p.get("structure_summary", [])[:5]
                md += f" {'; '.join(parts)[:60]} |"
            md += "\n"

            # Features row
            md += _T(lang, "| Detected Features |", "| 功能检测 |")
            for p in all_points:
                f = p.get("features", {})
                tags = [k for k, v in f.items() if v]
                md += f" {', '.join(tags)[:50]} |"
            md += "\n"

            # Social links row
            md += _T(lang, "| Social Outlinks |", "| 社媒外链 |")
            for p in all_points:
                sl = list(p.get("social_links", {}).keys())
                md += f" {', '.join(sl) if sl else _T(lang, 'none', '无')} |"
            md += "\n\n"

    # Key changes
    changes = ws.get("key_changes", [])
    if changes:
        md += _T(lang, "### Key Change Log\n\n", "### 关键变化记录\n\n")
        for c in changes:
            md += f"**{c['from_date']} → {c['to_date']}**\n"
            for item in c["changes"]:
                md += f"- {item}\n"
            md += "\n"

    # Social Media
    md += _T(lang,
        "## 2. Social Media Channel Analysis\n\n> Multi-platform channel detection and propagation metrics\n\n",
        "## 2. 社交媒体渠道分析\n\n> 多平台渠道检测与传播指标分析\n\n")
    sm = s["social_media"]
    channels = sm.get("channels", {})

    md += _T(lang, "### Channel Detection\n\n", "### 渠道检测\n\n")
    md += _T(lang,
        "| Platform | Status | Link | Details |\n|------|------|------|------|\n",
        "| 平台 | 状态 | 链接 | 详情 |\n|------|------|------|------|\n")
    for name, ch in channels.items():
        status = "✅" if ch.get("detected") else ("🔍" if ch.get("detected") is None else "❌")
        url = ch.get("url", "")
        details = []
        if ch.get("followers"): details.append(f"{ch['followers']} followers")
        if ch.get("subscribers"): details.append(f"{ch['subscribers']} subscribers")
        if ch.get("stars_total"): details.append(f"{ch['stars_total']} stars")
        if ch.get("subreddit_members"): details.append(f"{ch['subreddit_members']} members")
        md += f"| {ch.get('platform', name)} | {status} | {url} | {', '.join(details) or ch.get('note', '')} |\n"
    md += "\n"

    # Reddit top posts
    reddit = channels.get("reddit", {})
    if reddit.get("top_posts"):
        md += _T(lang, "### Hot Reddit Discussions\n\n", "### Reddit 热门讨论\n\n")
        md += _T(lang,
            "| Title | Subreddit | ⬆ | 💬 | Author |\n|------|-----------|---|---|------|\n",
            "| 标题 | Subreddit | ⬆ | 💬 | 作者 |\n|------|-----------|---|---|------|\n")
        for post in reddit["top_posts"][:8]:
            md += f"| {post['title'][:50]} | r/{post['subreddit']} | {post['upvotes']} | {post['comments']} | u/{post['author']} |\n"
        md += "\n"

    # Propagation metrics
    pm = sm.get("propagation_metrics", {})
    if pm:
        md += _T(lang, "### Propagation Metrics Overview\n\n", "### 传播指标总览\n\n")
        md += _T(lang,
            "| Metric | Value | Note |\n|------|------|------|\n",
            "| 指标 | 数值 | 备注 |\n|------|------|------|\n")
        md += _T(lang,
            f"| Total participants | {pm.get('total_participants', 0)} | Deduplicated across collected channels |\n",
            f"| 总参与人数 | {pm.get('total_participants', 0)} | 已采集渠道的去重统计 |\n")
        md += _T(lang,
            f"| Total engagement | {pm.get('total_engagement', 0)} | Upvotes + Comments + Stars |\n",
            f"| 总互动量 | {pm.get('total_engagement', 0)} | Upvotes + Comments + Stars |\n")
        md += _T(lang,
            f"| Data sources | {', '.join(pm.get('data_sources', []))} | |\n",
            f"| 数据来源 | {', '.join(pm.get('data_sources', []))} | |\n")
        if pm.get("note"):
            md += f"\n> {pm['note']}\n\n"

    # Traffic
    md += _T(lang, "## 3. Traffic & SEO Analysis\n\n", "## 3. 流量与 SEO 分析\n\n")
    tr = s["traffic_analysis"]
    if tr.get("need_topup"):
        md += _T(lang,
            "> ⚠️ Caravo balance insufficient. Top up at: https://www.caravo.ai/dashboard\n\n",
            "> ⚠️ Caravo 余额不足。充值: https://www.caravo.ai/dashboard\n\n")
    else:
        rank = tr.get("domain_rank", {})
        bl = tr.get("backlinks", {})
        kw = tr.get("top_keywords", {})
        hist = tr.get("historical", {})
        growth = tr.get("growth_analysis", {})

        has_data = rank.get("organic_traffic") or bl.get("backlinks")
        if has_data:
            # Scope disclosure — headline organic numbers aggregate the top 4
            # Google markets (US+UK+IN+DE); keyword tables remain US-only.
            scope = rank.get("market_scope") or "US"
            md += _T(lang,
                f"Data source: DataForSEO · organic metrics cover **{scope} search** (other markets excluded); keyword tables are US-only\n\n",
                f"数据来源: DataForSEO · 有机流量指标覆盖 **{scope} 搜索市场**（其他市场未计入）；关键词表为美国数据\n\n")
            # Surface the redirect note when the input domain isn't the one
            # that actually ranks (e.g. notion.so → notion.com).
            if tr.get("redirect_note"):
                md += f"> ℹ️ {tr['redirect_note']}\n\n"

            # Core metrics
            md += _T(lang, "### Core Metrics\n\n", "### 核心指标\n\n")
            md += _T(lang, "| Metric | Value |\n|------|------|\n", "| 指标 | 数值 |\n|------|------|\n")
            kw_cols = _T(lang,
                "| Keyword | Rank | Search Volume | CPC | Competition |\n|--------|------|----------|-----|--------|\n",
                "| 关键词 | 排名 | 月搜索量 | CPC | 竞争度 |\n|--------|------|----------|-----|--------|\n")
            if rank.get("organic_traffic") is not None:
                md += _T(lang,
                    f"| Organic traffic / month ({scope}) | {rank['organic_traffic']:,} |\n",
                    f"| 有机流量/月（{scope}） | {rank['organic_traffic']:,} |\n")
            # Per-market breakdown when multi-location data is present
            if rank.get("markets"):
                mk = " · ".join(
                    f"{label} {m['organic_traffic']:,}"
                    for label, m in rank["markets"].items()
                )
                md += _T(lang,
                    f"| — by market | {mk} |\n",
                    f"| — 分市场 | {mk} |\n")
            if rank.get("total_keywords") is not None:
                md += _T(lang,
                    f"| Ranked keywords | {rank['total_keywords']:,} |\n",
                    f"| 排名关键词 | {rank['total_keywords']:,} |\n")
            if rank.get("keywords_top10") is not None:
                md += _T(lang,
                    f"| Top 10 keywords | {rank['keywords_top10']:,} |\n",
                    f"| Top 10 关键词 | {rank['keywords_top10']:,} |\n")
            if rank.get("estimated_paid_cost") is not None:
                md += _T(lang,
                    f"| Equivalent paid cost | ${rank['estimated_paid_cost']:,}/month |\n",
                    f"| 等效付费成本 | ${rank['estimated_paid_cost']:,}/月 |\n")
            if bl.get("backlinks") is not None:
                md += _T(lang,
                    f"| Backlinks | {bl['backlinks']:,} |\n",
                    f"| 反向链接 | {bl['backlinks']:,} |\n")
            if bl.get("referring_domains") is not None:
                md += _T(lang,
                    f"| Referring domains | {bl['referring_domains']:,} |\n",
                    f"| 引用域名 | {bl['referring_domains']:,} |\n")
            if bl.get("domain_rank") is not None:
                md += _T(lang,
                    f"| Domain rank | {bl['domain_rank']} |\n",
                    f"| 域名排名 | {bl['domain_rank']} |\n")
            if bl.get("referring_ips") is not None:
                md += _T(lang,
                    f"| Referring IPs | {bl['referring_ips']:,} |\n",
                    f"| 引用 IP | {bl['referring_ips']:,} |\n")
            md += "\n"

            # Historical trend
            hist_data = hist.get("history", [])
            if hist_data:
                md += _T(lang, "### Organic Traffic Trend\n\n", "### 有机流量趋势\n\n")
                md += _T(lang,
                    "| Month | Organic Traffic | Keywords | Top10 | New | Lost |\n",
                    "| 月份 | 有机流量 | 关键词数 | Top10 | 新增 | 丢失 |\n")
                md += "|------|----------|----------|-------|------|------|\n"
                for h in hist_data:
                    md += f"| {h['date']} | {h.get('organic_traffic', 0):,} | {h.get('keywords', 0):,} | {h.get('top10', 0)} | +{h.get('new', 0):,} | -{h.get('lost', 0):,} |\n"
                md += "\n"

            # Growth phases
            if growth.get("phases"):
                md += _T(lang, "### Growth Phases\n\n", "### 增长阶段分析\n\n")
                for p in growth["phases"]:
                    md += f"**{p['name']}** ({p['period']})\n"
                    md += f"- {p['description']}\n\n"

            # Milestones
            if growth.get("milestones"):
                md += _T(lang, "### Key Milestones\n\n", "### 关键里程碑\n\n")
                for m in growth["milestones"]:
                    md += f"- {m}\n"
                md += "\n"

            # Growth insights
            if growth.get("insights"):
                md += _T(lang, "### Growth Insights\n\n", "### 增长洞察\n\n")
                for i in growth["insights"]:
                    md += f"- {i}\n"
                md += "\n"

            # Top keywords — branded
            branded_kw = kw.get("branded_keywords", [])
            non_branded_kw = kw.get("non_branded_keywords", [])
            legacy_kw = kw.get("keywords", [])

            if branded_kw:
                count = kw.get('branded_count', len(branded_kw))
                md += _T(lang,
                    f"### Branded Keyword Rankings ({count})\n\n",
                    f"### 品牌词排名（{count} 个）\n\n")
                md += kw_cols
                for k_item in branded_kw:
                    md += f"| {k_item.get('keyword', '—')} | #{k_item.get('position') or '—'} | {(k_item.get('search_volume') or 0):,} | ${(k_item.get('cpc') or 0):.2f} | {k_item.get('competition') or '—'} |\n"
                md += "\n"

            if non_branded_kw:
                count = kw.get('non_branded_count', len(non_branded_kw))
                md += _T(lang,
                    f"### Non-branded Keywords · High-exposure homepage ({count}, sorted by volume)\n\n",
                    f"### 非品牌词 · 首页高曝光（{count} 个，按搜索量排序）\n\n")
                md += kw_cols
                for k_item in non_branded_kw:
                    md += f"| {k_item.get('keyword', '—')} | #{k_item.get('position') or '—'} | {(k_item.get('search_volume') or 0):,} | ${(k_item.get('cpc') or 0):.2f} | {k_item.get('competition') or '—'} |\n"
                md += "\n"

            gap_kw = kw.get("gap_keywords", [])
            if gap_kw:
                count = kw.get('gap_keyword_count', len(gap_kw))
                md += _T(lang,
                    f"### Keyword Gap Opportunities (low-competition entries, {count} total)\n\n",
                    f"### 关键词缺口机会（竞争对手可切入的低竞争词，共 {count} 个）\n\n")
                md += _T(lang,
                    "| Keyword | Rank | Search Volume | Competition | Opportunity |\n|--------|----------|----------|--------|------------|\n",
                    "| 关键词 | 当前排名 | 月搜索量 | 竞争度 | 机会评级 |\n|--------|----------|----------|--------|------------|\n")
                for k_item in gap_kw:
                    pos = k_item.get('position') or 99
                    vol = k_item.get('search_volume') or 0
                    comp = k_item.get('competition') or ''
                    if pos > 10 and comp in ('LOW', ''):
                        opp = _T(lang, '🟢 High', '🟢 高')
                    elif pos > 5 or comp == 'MEDIUM':
                        opp = _T(lang, '🟡 Medium', '🟡 中')
                    else:
                        opp = _T(lang, '🔴 Low', '🔴 低')
                    md += f"| {k_item.get('keyword', '—')} | #{pos} | {vol:,} | {comp or '—'} | {opp} |\n"
                md += "\n"

            elif not branded_kw and legacy_kw:
                total = kw.get('total', 0)
                md += _T(lang,
                    f"### Top Ranked Keywords ({total:,} total)\n\n",
                    f"### Top 排名关键词（共 {total:,} 个）\n\n")
                md += kw_cols
                for k_item in legacy_kw:
                    md += f"| {k_item.get('keyword', '—')} | #{k_item.get('position') or '—'} | {(k_item.get('search_volume') or 0):,} | ${(k_item.get('cpc') or 0):.2f} | {k_item.get('competition') or '—'} |\n"
                md += "\n"

            # Error in rank data
            if rank.get("error") and not rank.get("organic_traffic"):
                md += f"> ⚠️ {rank['error']}\n\n"
        else:
            empty_note = _T(lang, "No traffic data available", "暂无流量数据")
            md += f"> {'⚠️ ' + tr.get('error', '') if tr.get('error') else empty_note}\n\n"

    # Growth Analysis
    ga = s.get("growth_analysis", {})
    if ga and not ga.get("error"):
        md += _T(lang,
            "## 4. Deep Growth Analysis\n\n> 📊 Cross-channel growth analysis — channel breakdown · 0→1 storyline · multi-wave launches\n\n",
            "## 4. 增长深度分析\n\n> 📊 多渠道交叉增长分析 — 渠道拆解 · 0→1 故事线 · 多波 Launch\n\n")

        # --- Channel Breakdown ---
        cb = ga.get("channel_breakdown", {})
        if cb:
            active = cb.get("active_channels", [])
            dominant = cb.get("dominant_channel", "")
            md += _T(lang, "### 4.1 Growth Channel Breakdown\n\n", "### 4.1 增长渠道拆解\n\n")
            if active:
                md += _T(lang, f"**Active channels**: {', '.join(active)}\n\n", f"**活跃渠道**：{', '.join(active)}\n\n")
            if dominant:
                dominant_label = cb.get("channel_metrics", {}).get(dominant, {}).get("platform", dominant)
                md += _T(lang, f"**Dominant channel**: {dominant_label}\n\n", f"**主导渠道**：{dominant_label}\n\n")

            # Channel metrics table
            cm = cb.get("channel_metrics", {})
            if cm:
                md += _T(lang, "#### Key Metrics by Channel\n\n", "#### 各渠道关键指标\n\n")
                md += _T(lang,
                    "| Channel | Metric | Value |\n|------|---------|------|\n",
                    "| 渠道 | 核心指标 | 数值 |\n|------|---------|------|\n")
                lbl_top_tweet  = _T(lang, "Top Tweet Likes", "Top 推文 Likes")
                lbl_avg_eng    = _T(lang, "Avg engagement", "平均互动")
                lbl_mentions   = _T(lang, "Mentions",  "提及次数")
                lbl_sub_mem    = _T(lang, "Subreddit members", "Subreddit 成员")
                lbl_mo_traffic = _T(lang, "Monthly traffic", "月均流量")
                lbl_ranked_kw  = _T(lang, "Ranked keywords", "排名关键词")
                for ch_key, ch_data in cm.items():
                    platform = ch_data.get("platform", ch_key)
                    metrics_pairs = []
                    if ch_data.get("followers"): metrics_pairs.append(("Followers", f"{ch_data['followers']:,}"))
                    if ch_data.get("total_tweets"): metrics_pairs.append(("Tweets", f"{ch_data['total_tweets']:,}"))
                    if ch_data.get("top_tweet_likes"): metrics_pairs.append((lbl_top_tweet, f"{ch_data['top_tweet_likes']:,}"))
                    if ch_data.get("avg_engagement"): metrics_pairs.append((lbl_avg_eng, f"{ch_data['avg_engagement']:,}"))
                    if ch_data.get("stars_total"): metrics_pairs.append(("Stars", f"{ch_data['stars_total']:,}"))
                    if ch_data.get("top_repo_stars"): metrics_pairs.append(("Top Repo Stars", f"{ch_data['top_repo_stars']:,}"))
                    if ch_data.get("total_mentions"): metrics_pairs.append((lbl_mentions, f"{ch_data['total_mentions']:,}"))
                    if ch_data.get("subreddit_members"): metrics_pairs.append((lbl_sub_mem, f"{ch_data['subreddit_members']:,}"))
                    if ch_data.get("monthly_traffic"): metrics_pairs.append((lbl_mo_traffic, f"{ch_data['monthly_traffic']:,}"))
                    if ch_data.get("total_keywords"): metrics_pairs.append((lbl_ranked_kw, f"{ch_data['total_keywords']:,}"))
                    for label, val in metrics_pairs[:2]:
                        md += f"| {platform} | {label} | {val} |\n"
                md += "\n"

            # Content category stats
            tw_metrics = cm.get("twitter", {})
            content_cats = tw_metrics.get("content_categories", {})
            if content_cats:
                md += _T(lang, "#### Twitter Content Categories\n\n", "#### Twitter 内容分类统计\n\n")
                md += _T(lang, "| Category | Tweets |\n|------|--------|\n", "| 类型 | 推文数 |\n|------|--------|\n")
                if lang.startswith("en"):
                    cat_labels = {"launch": "Launch / Release", "product_update": "Product Update",
                                  "community": "Community / Engagement", "tutorial": "Tutorial / How-to",
                                  "kol_collab": "KOL Collab", "other": "Other"}
                else:
                    cat_labels = {"launch": "发布/上线", "product_update": "产品更新", "community": "社区/互动",
                                  "tutorial": "教程/干货", "kol_collab": "KOL 合作", "other": "其他"}
                for cat, count in sorted(content_cats.items(), key=lambda x: x[1], reverse=True):
                    md += f"| {cat_labels.get(cat, cat)} | {count} |\n"
                md += "\n"

            # Top content
            top_content = cb.get("top_content", [])
            if top_content:
                md += _T(lang, "#### Top Cross-platform Content\n\n", "#### Top 内容表现（跨平台）\n\n")
                md += _T(lang,
                    "| Platform | Content excerpt | Likes/Upvotes | Other |\n|------|---------|--------------|----------|\n",
                    "| 平台 | 内容摘要 | Likes/Upvotes | 其他指标 |\n|------|---------|--------------|----------|\n")
                for c in top_content[:5]:
                    platform = c.get("platform", "")
                    text = c.get("text", "")[:60].replace("|", "｜")
                    likes = c.get("likes", 0)
                    other = ""
                    if c.get("retweets"): other = f"RT: {c['retweets']}"
                    elif c.get("comments"): other = f"💬 {c['comments']}"
                    elif c.get("subreddit"): other = f"r/{c['subreddit']}"
                    md += f"| {platform} | {text} | {likes:,} | {other} |\n"
                md += "\n"

        # --- 0→1 Story ---
        z2o = ga.get("zero_to_one_story", {})
        if z2o:
            md += _T(lang, "### 4.2 0→1 Growth Storyline\n\n", "### 4.2 0→1 成长故事线\n\n")
            first_seen = z2o.get("first_seen", "N/A")
            current_traffic = z2o.get("current_traffic", 0)
            growth_multiple = z2o.get("growth_multiple")
            md += _T(lang, f"**Domain first seen**: {first_seen}  \n", f"**域名首次出现**：{first_seen}  \n")
            if current_traffic:
                md += _T(lang,
                    f"**Current monthly organic traffic**: {current_traffic:,}  \n",
                    f"**当前月均有机流量**：{current_traffic:,}  \n")
            if growth_multiple:
                md += _T(lang,
                    f"**Traffic growth multiple**: {growth_multiple}x  \n",
                    f"**流量增长倍数**：{growth_multiple}x  \n")
            md += "\n"

            timeline = z2o.get("timeline", [])
            if timeline:
                md += _T(lang, "#### Key Event Timeline\n\n", "#### 关键事件时间线\n\n")
                md += _T(lang,
                    "| Date | Type | Event | Source |\n|------|------|------|------|\n",
                    "| 日期 | 类型 | 事件 | 来源 |\n|------|------|------|------|\n")
                if lang.startswith("en"):
                    type_labels = {"milestone": "🏁 Milestone", "launch": "🚀 Launch",
                                   "traffic_spike": "📈 Traffic Spike", "seo_milestone": "🔑 SEO Milestone",
                                   "website_change": "🔄 Site Change"}
                else:
                    type_labels = {"milestone": "🏁 里程碑", "launch": "🚀 发布",
                                   "traffic_spike": "📈 流量激增", "seo_milestone": "🔑 SEO 里程碑",
                                   "website_change": "🔄 官网变化"}
                for e in timeline:
                    date = e.get("date", "")[:10] if e.get("date") else "—"
                    etype = type_labels.get(e.get("type", ""), e.get("type", ""))
                    event_text = e.get("event", "")[:80].replace("|", "｜")
                    source = e.get("source", "")
                    md += f"| {date} | {etype} | {event_text} | {source} |\n"
                md += "\n"

            inflections = z2o.get("key_inflection_points", [])
            if inflections:
                md += _T(lang, "#### Key Inflection Points\n\n", "#### 关键拐点\n\n")
                for ip in inflections:
                    md += _T(lang,
                        f"- **{ip.get('date', '')}** traffic from {ip.get('traffic_before', 0):,} to {ip.get('traffic_after', 0):,} (+{ip.get('growth_pct', 0)}%)\n",
                        f"- **{ip.get('date', '')}** 流量从 {ip.get('traffic_before', 0):,} 增至 {ip.get('traffic_after', 0):,}（+{ip.get('growth_pct', 0)}%）\n")
                md += "\n"

        # --- Launch Waves ---
        lw = ga.get("launch_waves", {})
        if lw and lw.get("total_waves", 0) > 0:
            md += _T(lang, "### 4.3 Multi-wave Launch Analysis\n\n", "### 4.3 多波 Launch 分析\n\n")
            md += _T(lang,
                f"**Total launch waves**: {lw['total_waves']}  \n",
                f"**总 Launch 波次**：{lw['total_waves']}  \n")
            if lw.get("launch_cadence"):
                md += _T(lang,
                    f"**Launch cadence**: {lw['launch_cadence']}  \n",
                    f"**Launch 节奏**：{lw['launch_cadence']}  \n")
            md += "\n"

            for wave in lw.get("launches", []):
                md += f"#### Wave {wave['wave_number']}: {wave.get('date_range', '')}\n\n"
                md += _T(lang,
                    f"**Channels**: {', '.join(wave.get('channels', []))}  \n",
                    f"**渠道**：{', '.join(wave.get('channels', []))}  \n")
                impact = wave.get("total_impact", {})
                if impact.get("ph_votes"): md += f"**PH Votes**: {impact['ph_votes']:,}  \n"
                if impact.get("twitter_likes"): md += f"**Twitter Likes**: {impact['twitter_likes']:,}  \n"
                if impact.get("traffic_peak"):
                    md += _T(lang,
                        f"**Traffic peak**: {impact['traffic_peak']:,}/month  \n",
                        f"**流量峰值**：{impact['traffic_peak']:,}/月  \n")
                md += "\n"
                for ev in wave.get("events", []):
                    date = ev.get("date", "")[:10] if ev.get("date") else "—"
                    name = ev.get("name", "")[:60].replace("|", "｜")
                    channel = ev.get("channel", "")
                    md += f"- [{date}] **{channel}** — {name}\n"
                md += "\n"

    # Traffic Peaks
    tp = s.get("traffic_peaks", {})
    if tp and not tp.get("error") and tp.get("summary"):
        md += _T(lang,
            "## 5. Google Trends Peak Analysis\n\n> 📊 **Cross-source attribution analysis** — Google Trends interest × PH/HN/Twitter event attribution\n\n",
            "## 5. Google Trends 流量峰值分析\n\n> 📊 **多源交叉归因分析** — Google Trends 热度数据 × PH/HN/Twitter 事件归因\n\n")
        tps = tp["summary"]
        md += _T(lang, f"**Query**: {tps.get('primary_query', '')}  \n", f"**查询词**：{tps.get('primary_query', '')}  \n")
        md += _T(lang, f"**Weeks of data**: {tps.get('total_weeks', 0)}  \n", f"**数据周数**：{tps.get('total_weeks', 0)}  \n")
        md += _T(lang,
            f"**Peak search interest**: {tps.get('max_interest', 0)} ({tps.get('max_interest_date', '')})  \n",
            f"**峰值搜索热度**：{tps.get('max_interest', 0)}（{tps.get('max_interest_date', '')}）  \n")
        md += _T(lang, f"**Average interest**: {tps.get('avg_interest', 0)}  \n", f"**平均热度**：{tps.get('avg_interest', 0)}  \n")
        md += _T(lang, f"**Recent trend**: {tps.get('recent_trend', 'N/A')}  \n", f"**近期趋势**：{tps.get('recent_trend', 'N/A')}  \n")
        md += _T(lang, f"**Current phase**: {tps.get('current_phase', 'N/A')}  \n", f"**当前阶段**：{tps.get('current_phase', 'N/A')}  \n")
        md += _T(lang,
            f"**Peaks detected**: {tps.get('total_peaks_detected', 0)} ({tps.get('matched_peaks', 0)} attributed, {tps.get('unmatched_peaks', 0)} unmatched)  \n\n",
            f"**检测到峰值数**：{tps.get('total_peaks_detected', 0)}（已关联 {tps.get('matched_peaks', 0)} 个，未匹配 {tps.get('unmatched_peaks', 0)} 个）  \n\n")

        # Growth phases with insights
        phases = tp.get("growth_phases", [])
        if phases:
            md += _T(lang, "### Growth Phase Segmentation\n\n", "### 增长阶段划分\n\n")
            week_word = _T(lang, "wks", "周")
            avg_word = _T(lang, "avg", "均值")
            active_word = _T(lang, "Active channels", "活跃渠道")
            peak_word = _T(lang, "peak events", "峰值事件")
            for ph in phases:
                channels = ph.get("active_channels", [])
                ch_str = " · ".join(channels) if channels else "—"
                peak_count = ph.get("peak_count", 0)
                md += f"**{ph['phase']}** ({ph['start_date']} → {ph['end_date']}, {ph['week_count']}{week_word}, {avg_word} {ph['avg_value']})  \n"
                md += f"{active_word}: {ch_str}"
                if peak_count:
                    md += _T(lang, f" | {peak_word}: {peak_count}", f" | 峰值事件: {peak_count}个")
                md += "  \n"
                for insight in ph.get("insights", []):
                    md += f"- {insight}\n"
                md += "\n"

        # Detected peaks — with attribution
        peaks = tp.get("detected_peaks", [])
        if peaks:
            md += _T(lang, "### Detected Peak Events\n\n", "### 检测到的峰值事件\n\n")
            for i, pk in enumerate(peaks, 1):
                status = pk.get("status", "unmatched")
                attr = pk.get("attribution", {})

                # Status badge
                if status == "attributed":
                    conf_label = (_T(lang, "high confidence", "高可信度")
                                  if attr.get('confidence') == 'high'
                                  else _T(lang, "medium confidence", "中等可信度"))
                    status_badge = _T(lang,
                        f"**Attribution**: {attr.get('primary_channel', '?')} ({conf_label})",
                        f"**归因**: {attr.get('primary_channel', '?')}（{conf_label}）")
                elif status == "ph_matched":
                    status_badge = _T(lang, "**Attribution**: Product Hunt launch", "**归因**: Product Hunt 发布")
                else:
                    status_badge = _T(lang, "**Attribution**: no clear source found", "**归因**: 未找到明确来源")

                md += _T(lang,
                    f"### Peak Event #{i}: {pk.get('peak_date_label', '')} (interest: {pk.get('peak_value', 0)}/100)\n\n",
                    f"### 峰值事件 #{i}: {pk.get('peak_date_label', '')} （热度: {pk.get('peak_value', 0)}/100）\n\n")
                md += f"{status_badge}\n\n"

                # Show attribution sources
                if attr.get("attributed") and attr.get("all_sources"):
                    for src in attr["all_sources"]:
                        channel_icon = {
                            "Hacker News": "📰",
                            "Product Hunt": "🏆",
                            "Twitter/X": "🐦",
                            "Reddit": "💬",
                        }.get(src["channel"], "🔗")
                        md += _T(lang,
                            f"**{channel_icon} {src['channel']}** (impact score: {src['impact_score']})\n",
                            f"**{channel_icon} {src['channel']}**（impact score: {src['impact_score']}）\n")
                        for ev in src["events"][:3]:
                            title = ev.get("title", "")[:80]
                            if src["channel"] == "Hacker News":
                                pts = ev.get("points", 0)
                                comments = ev.get("comments", 0)
                                date = ev.get("date", "")
                                url = ev.get("url", "")
                                md += f"- 📰 [{title}]({url}) — {pts} pts, 💬{comments} ({date})\n"
                            elif src["channel"] == "Product Hunt":
                                votes = ev.get("votes", 0)
                                date = ev.get("date", "")
                                md += f"- 🏆 {title} — ⬆{votes} votes ({date})\n"
                            elif src["channel"] == "Twitter/X":
                                likes = ev.get("likes", 0)
                                rts = ev.get("retweets", 0)
                                date = ev.get("date", "")
                                md += f"- 🐦 {title} — ❤️{likes} 🔄{rts} ({date})\n"
                            elif src["channel"] == "Reddit":
                                upvotes = ev.get("upvotes", 0)
                                sub = ev.get("subreddit", "")
                                date = ev.get("date", "")
                                md += f"- 💬 {title} — ⬆{upvotes} r/{sub} ({date})\n"
                        md += "\n"
                    # Summary line
                    if attr.get("summary"):
                        md += f"> {attr['summary']}\n\n"
                elif status == "ph_matched":
                    launches = pk.get("matched_launches", [])
                    for m in launches:
                        delta = m.get("delta_days", 0)
                        if lang.startswith("en"):
                            delta_str = (f"peak {delta} days after launch" if delta >= 0
                                         else f"peak {abs(delta)} days before launch")
                        else:
                            delta_str = (f"峰值晚于 Launch {delta} 天" if delta >= 0
                                         else f"峰值早于 Launch {abs(delta)} 天")
                        md += f"- 🏆 {m.get('label', '')} ({delta_str})\n"
                    md += "\n"
                else:
                    fallback = _T(lang, "no clear source found", "未找到明确来源")
                    md += f"> {attr.get('summary', pk.get('hypothesis', fallback))}\n\n"

        # Unmatched peaks summary
        unmatched = tp.get("unmatched_peaks", [])
        if unmatched:
            md += _T(lang, "### Suspected Unrecorded Launch Events\n\n", "### 疑似未记录的 Launch 事件\n\n")
            for pk in unmatched:
                attr = pk.get("attribution", {})
                summary = attr.get("summary") or pk.get("hypothesis", "")
                md += _T(lang,
                    f"- **{pk.get('peak_date_label', '')}** interest peak {pk.get('peak_value', 0)}: {summary}\n",
                    f"- **{pk.get('peak_date_label', '')}** 热度峰值 {pk.get('peak_value', 0)}：{summary}\n")
            md += "\n"

    # Propagation Analysis
    prop = s.get("propagation", {})
    if prop and not prop.get("error") and prop.get("data_mode") not in (None, "empty"):
        md += _T(lang, "## 6. Propagation Deep Dive\n\n", "## 6. 传播深度分析\n\n")

        root = prop.get("root_post", {})
        if root.get("text"):
            md += _T(lang, f"**Launch post**: {root['text'][:150]}  \n", f"**Launch 帖**：{root['text'][:150]}  \n")
            md += _T(lang,
                f"**Engagement**: ❤️{root.get('likes',0):,} 🔄{root.get('retweets',0):,} 💬{root.get('replies',0):,} 👁{root.get('views',0):,}  \n\n",
                f"**互动数据**：❤️{root.get('likes',0):,} 🔄{root.get('retweets',0):,} 💬{root.get('replies',0):,} 👁{root.get('views',0):,}  \n\n")

        # Approximate analysis (降级模式)
        approx = prop.get("approximate_analysis")
        if approx:
            md += f"> {approx.get('note', '')}  \n\n"
            agg = approx.get("aggregate_metrics", {})
            if agg:
                md += _T(lang, "### Aggregate Metrics (approximate)\n\n", "### 聚合指标（近似）\n\n")
                md += _T(lang, f"- Total retweets: {agg.get('total_retweets', 0):,}\n", f"- 总 Retweets：{agg.get('total_retweets', 0):,}\n")
                md += _T(lang, f"- Total likes: {agg.get('total_likes', 0):,}\n", f"- 总 Likes：{agg.get('total_likes', 0):,}\n")
                md += _T(lang, f"- Total views: {agg.get('total_views', 0):,}\n", f"- 总 Views：{agg.get('total_views', 0):,}\n")
                md += _T(lang,
                    f"- Avg engagement / tweet: {agg.get('avg_engagement_per_tweet', 0)}\n\n",
                    f"- 平均互动/推文：{agg.get('avg_engagement_per_tweet', 0)}\n\n")
            est = approx.get("propagation_estimate", {})
            if est.get("estimated_reach"):
                md += _T(lang,
                    f"**Estimated reach**: {est['estimated_reach']:,}  \n",
                    f"**预估触达人数**：{est['estimated_reach']:,}  \n")
            if est.get("viral_coefficient"):
                md += _T(lang,
                    f"**Viral coefficient (RT/tweet)**: {est['viral_coefficient']}  \n\n",
                    f"**病毒系数（RT/推文）**：{est['viral_coefficient']}  \n\n")
        else:
            # Full mode: KOL + four-stage
            inf = prop.get("influencer_analysis", {})
            if inf.get("total_kols", 0) > 0:
                md += _T(lang,
                    f"**KOL participants (10K+ followers)**: {inf['total_kols']}  \n\n",
                    f"**KOL 参与数（10K+ 粉丝）**：{inf['total_kols']}  \n\n")

                top_inf = inf.get("top_influencers", [])
                if top_inf:
                    md += _T(lang, "### Top Influencers\n\n", "### Top 影响者\n\n")
                    md += _T(lang,
                        "| Handle | Followers | Type | Joined at |\n|------|------|------|----------|\n",
                        "| 账号 | 粉丝 | 类型 | 参与时间 |\n|------|------|------|----------|\n")
                    for u in top_inf[:8]:
                        hours = f"{u.get('hours_after_launch', '?')}h" if u.get('hours_after_launch') is not None else "N/A"
                        md += f"| @{u['screen_name']} | {u.get('followers',0):,} | {u.get('user_type','')} | {hours} |\n"
                    md += "\n"

            # Four stage
            stages = prop.get("four_stage_timeline", {})
            if stages:
                md += _T(lang, "### Four-stage Propagation Model\n\n", "### 四阶段传播模型\n\n")
                md += _T(lang,
                    "| Stage | Label | Participants |\n|------|------|----------|\n",
                    "| 阶段 | 标签 | 参与人数 |\n|------|------|----------|\n")
                for stage_key, stage_data in stages.items():
                    md += f"| {stage_key} | {stage_data.get('label','')} | {stage_data.get('count',0)} |\n"
                md += "\n"

            # Propagation rhythm
            rhythm = prop.get("propagation_rhythm", {})
            if rhythm:
                md += _T(lang, "### Propagation Rhythm\n\n", "### 传播节奏\n\n")
                md += _T(lang,
                    "| Time window | Participants | Follower reach |\n|----------|----------|----------|\n",
                    "| 时间窗口 | 参与人数 | 粉丝触达 |\n|----------|----------|----------|\n")
                for bk, bv in rhythm.items():
                    md += f"| {bv.get('label', bk)} | {bv.get('count', 0)} | {bv.get('total_followers_reached', 0):,} |\n"
                md += "\n"

    # Summary
    md += _T(lang, "## 7. Overall Assessment\n\n", "## 7. 综合评估\n\n")
    for f in s["summary"]["findings"]:
        md += f"- {f}\n"

    # Growth Strategy
    gs = s.get("growth_strategy", {})
    if gs and not gs.get("error") and gs.get("primary"):
        md += _T(lang,
            "\n## 8. Custom Growth Strategy (Gingiris Playbook recommendation)\n\n> 💡 **Gingiris Playbook exclusive recommendation** — auto-matched from the cross analysis of Wayback history + PH launches + social propagation\n\n",
            "\n## 8. 定制增长策略（Gingiris Playbook 推荐）\n\n> 💡 **Gingiris Playbook 独家推荐** — 基于 Wayback 历史 + PH Launch + 社交传播的交叉分析自动匹配\n\n")
        primary = gs["primary"]
        secondary = gs.get("secondary", [])
        gt = gs.get("growth_tools")

        md += _T(lang,
            f"### {primary.get('emoji', '📘')} Primary: {primary.get('label', '')}\n\n",
            f"### {primary.get('emoji', '📘')} 主推：{primary.get('label', '')}\n\n")
        md += f"> 👉 [{primary.get('label', '')}]({primary.get('url', '')})\n\n"
        md += f"{primary.get('description', '')}\n\n"

        reasons = primary.get("reasons", [])
        if reasons:
            md += _T(lang, "**Why it matches**\n\n", "**匹配原因**\n\n")
            for r in reasons:
                md += f"- ✓ {r}\n"
            md += "\n"

        tips = primary.get("custom_tips", [])
        if tips:
            md += _T(lang,
                "**🎯 Custom recommendations (based on the competitor data)**\n\n",
                "**🎯 定制建议（基于竞品数据）**\n\n")
            for i, tip in enumerate(tips, 1):
                md += f"{i}. {tip}\n"
            md += "\n"

        if secondary:
            md += _T(lang, "### Supporting Playbooks\n\n", "### 辅助 Playbook\n\n")
            for s_pb in secondary:
                md += f"- {s_pb.get('emoji', '')} **{s_pb.get('label', '')}**: {s_pb.get('url', '')}\n"
                if s_pb.get("reasons"):
                    md += f"  - {s_pb['reasons'][0]}\n"
                if s_pb.get("custom_tips"):
                    md += f"  - 💡 {s_pb['custom_tips'][0]}\n"
            md += "\n"

        if gt:
            md += _T(lang,
                f"### {gt.get('emoji', '🛠️')} Companion Toolkit\n\n",
                f"### {gt.get('emoji', '🛠️')} 配套工具库\n\n")
            md += f"> [{gt.get('label', '')}]({gt.get('url', '')})  \n"
            md += f"> {gt.get('description', '')}\n\n"

    # References（Manus 签名：数据点带来源）
    refs = s.get("references") or []
    if refs:
        md += _T(lang, "\n## References\n\n", "\n## 数据来源 References\n\n")
        for i, r in enumerate(refs, 1):
            md += f"[{i}] **{r.get('source', '')}** — {r.get('used_for', '')}"
            if r.get("date"):
                md += _T(lang, f" (fetched {r['date']})", f"（抓取日期 {r['date']}）")
            md += "\n"

    md += _T(lang,
        "\n---\n*Report auto-generated by the Analook competitor research tool; some data points need human verification.*\n",
        "\n---\n*报告由竞品调研工具自动生成，部分数据需手动验证。*\n")
    return md


import math as _math

def _compute_strategy_radar(sections: dict, lang: str = "zh") -> dict:
    """Compute 6-dimension strategy radar scores (0-100) from report data."""

    def _clamp(v): return max(0, min(100, int(v)))
    def _log_scale(v, base=10): return _math.log10(max(v, 1)) if v else 0

    # --- 1. Product Power (产品力) ---
    ph = sections.get("producthunt", {})
    pricing = sections.get("pricing", {})
    ph_votes = ph.get("votes", 0) or 0
    ph_reviews = ph.get("reviews_count", 0) or 0
    has_pricing = 1 if (pricing.get("found") or pricing.get("plans")) else 0
    product_score = _clamp(
        min(ph_votes / 50, 40) + has_pricing * 25 + min(ph_reviews * 5, 20) + 15
    )

    # --- 2. Social Influence (社交影响力) ---
    sm = sections.get("social_media", {})
    channels = sm.get("channels", {})
    tw = channels.get("twitter", {}) if isinstance(channels, dict) else {}
    tw_followers = tw.get("followers", 0) or 0
    yt = channels.get("youtube", {}) if isinstance(channels, dict) else {}
    yt_subs = yt.get("subscribers", 0) or 0
    social_score = _clamp(
        _log_scale(tw_followers) * 15 + _log_scale(yt_subs) * 10 + 10
    )

    # --- 3. SEO Authority (SEO 权威度) ---
    tr = sections.get("traffic_analysis", {})
    seo_m = tr.get("seo_metrics", {})
    da = seo_m.get("domain_authority", 0) or 0
    traffic = seo_m.get("organic_traffic_estimate", 0) or tr.get("domain_rank", {}).get("organic_traffic", 0) or 0
    seo_score = _clamp(
        da + _log_scale(traffic) * 8
    )

    # --- 4. Open Source / Community (开源/社区) ---
    gh = sections.get("github_oss", {})
    stars = gh.get("stars", 0) or 0
    contributors = gh.get("contributors_count", 0) or 0
    rd = channels.get("reddit", {}) if isinstance(channels, dict) else {}
    has_reddit = 1 if (isinstance(rd, dict) and rd.get("detected")) else 0
    community_score = _clamp(
        _log_scale(stars) * 18 + _log_scale(contributors) * 10 + has_reddit * 15
    )

    # --- 5. Content Engine (内容引擎) ---
    ws = sections.get("website_analysis", {})
    cur = ws.get("current", ws.get("current_site", {}))
    features = cur.get("features", {}) if isinstance(cur, dict) else {}
    content_features = sum(1 for k in ["blog", "docs", "changelog", "faq", "case_study"] if features.get(k))
    content_score = _clamp(content_features * 18 + 10)

    # --- 6. Launch Execution (Launch 执行力) ---
    ga = sections.get("growth_analysis", {})
    tp = sections.get("traffic_peaks", {})
    waves = ga.get("launch_waves", {})
    total_waves = waves.get("total_waves", 0) or 0
    peaks_detected = tp.get("summary", {}).get("total_peaks_detected", 0) or 0
    ph_launches = 1 + len(ph.get("other_launches", []))
    launch_score = _clamp(
        min(ph_launches * 15, 40) + min(total_waves * 10, 30) + min(peaks_detected * 3, 30)
    )

    dimensions = [
        {"key": "product", "label": _T(lang, "Product Power", "产品力"), "score": product_score, "emoji": "🎯"},
        {"key": "social", "label": _T(lang, "Social Influence", "社交影响力"), "score": social_score, "emoji": "📢"},
        {"key": "seo", "label": _T(lang, "SEO Authority", "SEO 权威度"), "score": seo_score, "emoji": "🔍"},
        {"key": "community", "label": _T(lang, "Open Source / Community", "开源/社区"), "score": community_score, "emoji": "💻"},
        {"key": "content", "label": _T(lang, "Content Engine", "内容引擎"), "score": content_score, "emoji": "📝"},
        {"key": "launch", "label": _T(lang, "Launch Execution", "Launch 执行力"), "score": launch_score, "emoji": "🚀"},
    ]

    total = sum(d["score"] for d in dimensions)
    avg = int(total / len(dimensions))

    return {
        "dimensions": dimensions,
        "total_score": total,
        "avg_score": avg,
    }
