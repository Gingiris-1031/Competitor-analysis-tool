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
    report["sections"]["strategy_radar"] = _compute_strategy_radar(report["sections"])
    return report


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


def report_to_markdown(report: dict) -> str:
    meta = report["meta"]
    s = report["sections"]
    
    md = f"""# 竞品调研报告：{meta['product_name']}

> 生成时间：{meta['generated_at'][:19]}  
> 目标网址：{meta['url']}  
> 版本：{meta['version']}

---

## 1. 官网演变分析 🔍

> 🔍 **Wayback Machine 独家数据** — 基于多年历史快照的深度演变分析

"""
    ws = s["website_analysis"]
    md += f"**域名**：{ws['domain']}  \n"
    md += f"**首次出现**：{ws['first_seen']}  \n"
    md += f"**历史快照数**：{ws['total_snapshots']}  \n\n"

    # Timeline table
    timeline = ws.get("deep_timeline", [])
    current = ws.get("current", {})
    if timeline or current:
        all_points = [t for t in timeline if not t.get("error") and t.get("date")] + ([current] if current and "error" not in current else [])
        if all_points:
            md += "### 官网演变时间线\n\n"
            md += "| 维度 |"
            for p in all_points:
                label = "当前" if p.get("is_current") else p.get("date", "")
                md += f" {label} |"
            md += "\n|------|" + "------|" * len(all_points) + "\n"
            
            # Slogan row
            md += "| Slogan |"
            for p in all_points:
                md += f" {p.get('slogan', 'N/A')[:40]} |"
            md += "\n"
            
            # Structure row
            md += "| 官网结构 |"
            for p in all_points:
                parts = p.get("structure_summary", [])[:5]
                md += f" {'; '.join(parts)[:60]} |"
            md += "\n"
            
            # Features row
            md += "| 功能检测 |"
            for p in all_points:
                f = p.get("features", {})
                tags = [k for k, v in f.items() if v]
                md += f" {', '.join(tags)[:50]} |"
            md += "\n"
            
            # Social links row
            md += "| 社媒外链 |"
            for p in all_points:
                sl = list(p.get("social_links", {}).keys())
                md += f" {', '.join(sl) if sl else '无'} |"
            md += "\n\n"
    
    # Key changes
    changes = ws.get("key_changes", [])
    if changes:
        md += "### 关键变化记录\n\n"
        for c in changes:
            md += f"**{c['from_date']} → {c['to_date']}**\n"
            for item in c["changes"]:
                md += f"- {item}\n"
            md += "\n"

    # Social Media
    md += "## 2. 社交媒体渠道分析\n\n"
    md += "> 多平台渠道检测与传播指标分析\n\n"
    sm = s["social_media"]
    channels = sm.get("channels", {})
    
    md += "### 渠道检测\n\n"
    md += "| 平台 | 状态 | 链接 | 详情 |\n|------|------|------|------|\n"
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
        md += "### Reddit 热门讨论\n\n"
        md += "| 标题 | Subreddit | ⬆ | 💬 | 作者 |\n|------|-----------|---|---|------|\n"
        for post in reddit["top_posts"][:8]:
            md += f"| {post['title'][:50]} | r/{post['subreddit']} | {post['upvotes']} | {post['comments']} | u/{post['author']} |\n"
        md += "\n"
    
    # Propagation metrics
    pm = sm.get("propagation_metrics", {})
    if pm:
        md += "### 传播指标总览\n\n"
        md += "| 指标 | 数值 | 备注 |\n|------|------|------|\n"
        md += f"| 总参与人数 | {pm.get('total_participants', 0)} | 已采集渠道的去重统计 |\n"
        md += f"| 总互动量 | {pm.get('total_engagement', 0)} | Upvotes + Comments + Stars |\n"
        md += f"| 数据来源 | {', '.join(pm.get('data_sources', []))} | |\n"
        if pm.get("note"):
            md += f"\n> {pm['note']}\n\n"

    # Traffic
    md += "## 3. 流量与 SEO 分析\n\n"
    tr = s["traffic_analysis"]
    if tr.get("need_topup"):
        md += "> ⚠️ Caravo 余额不足。充值: https://www.caravo.ai/dashboard\n\n"
    else:
        rank = tr.get("domain_rank", {})
        bl = tr.get("backlinks", {})
        kw = tr.get("top_keywords", {})
        hist = tr.get("historical", {})
        growth = tr.get("growth_analysis", {})

        has_data = rank.get("organic_traffic") or bl.get("backlinks")
        if has_data:
            md += "数据来源: DataForSEO\n\n"

            # Core metrics
            md += "### 核心指标\n\n"
            md += "| 指标 | 数值 |\n|------|------|\n"
            if rank.get("organic_traffic") is not None:
                md += f"| 有机流量/月 | {rank['organic_traffic']:,} |\n"
            if rank.get("total_keywords") is not None:
                md += f"| 排名关键词 | {rank['total_keywords']:,} |\n"
            if rank.get("keywords_top10") is not None:
                md += f"| Top 10 关键词 | {rank['keywords_top10']:,} |\n"
            if rank.get("estimated_paid_cost") is not None:
                md += f"| 等效付费成本 | ${rank['estimated_paid_cost']:,}/月 |\n"
            if bl.get("backlinks") is not None:
                md += f"| 反向链接 | {bl['backlinks']:,} |\n"
            if bl.get("referring_domains") is not None:
                md += f"| 引用域名 | {bl['referring_domains']:,} |\n"
            if bl.get("domain_rank") is not None:
                md += f"| 域名排名 | {bl['domain_rank']} |\n"
            if bl.get("referring_ips") is not None:
                md += f"| 引用 IP | {bl['referring_ips']:,} |\n"
            md += "\n"

            # Historical trend
            hist_data = hist.get("history", [])
            if hist_data:
                md += "### 有机流量趋势\n\n"
                md += "| 月份 | 有机流量 | 关键词数 | Top10 | 新增 | 丢失 |\n"
                md += "|------|----------|----------|-------|------|------|\n"
                for h in hist_data:
                    md += f"| {h['date']} | {h.get('organic_traffic', 0):,} | {h.get('keywords', 0):,} | {h.get('top10', 0)} | +{h.get('new', 0):,} | -{h.get('lost', 0):,} |\n"
                md += "\n"

            # Growth phases
            if growth.get("phases"):
                md += "### 增长阶段分析\n\n"
                for p in growth["phases"]:
                    md += f"**{p['name']}**（{p['period']}）\n"
                    md += f"- {p['description']}\n\n"

            # Milestones
            if growth.get("milestones"):
                md += "### 关键里程碑\n\n"
                for m in growth["milestones"]:
                    md += f"- {m}\n"
                md += "\n"

            # Growth insights
            if growth.get("insights"):
                md += "### 增长洞察\n\n"
                for i in growth["insights"]:
                    md += f"- {i}\n"
                md += "\n"

            # Top keywords — branded
            branded_kw = kw.get("branded_keywords", [])
            non_branded_kw = kw.get("non_branded_keywords", [])
            legacy_kw = kw.get("keywords", [])

            if branded_kw:
                md += f"### 品牌词排名（{kw.get('branded_count', len(branded_kw))} 个）\n\n"
                md += "| 关键词 | 排名 | 月搜索量 | CPC | 竞争度 |\n|--------|------|----------|-----|--------|\n"
                for k_item in branded_kw:
                    md += f"| {k_item['keyword']} | #{k_item['position']} | {k_item.get('search_volume', 0):,} | ${k_item.get('cpc', 0):.2f} | {k_item.get('competition', '—')} |\n"
                md += "\n"

            if non_branded_kw:
                md += f"### 非品牌词 · 首页高曝光（{kw.get('non_branded_count', len(non_branded_kw))} 个，按搜索量排序）\n\n"
                md += "| 关键词 | 排名 | 月搜索量 | CPC | 竞争度 |\n|--------|------|----------|-----|--------|\n"
                for k_item in non_branded_kw:
                    md += f"| {k_item['keyword']} | #{k_item['position']} | {k_item.get('search_volume', 0):,} | ${k_item.get('cpc', 0):.2f} | {k_item.get('competition', '—')} |\n"
                md += "\n"

            gap_kw = kw.get("gap_keywords", [])
            if gap_kw:
                md += f"### 关键词缺口机会（竞争对手可切入的低竞争词，共 {kw.get('gap_keyword_count', len(gap_kw))} 个）\n\n"
                md += "| 关键词 | 当前排名 | 月搜索量 | 竞争度 | 机会评级 |\n|--------|----------|----------|--------|------------|\n"
                for k_item in gap_kw:
                    pos = k_item.get('position', 99)
                    vol = k_item.get('search_volume', 0)
                    comp = k_item.get('competition', '')
                    if pos > 10 and comp in ('LOW', ''):
                        opp = '🟢 高'
                    elif pos > 5 or comp == 'MEDIUM':
                        opp = '🟡 中'
                    else:
                        opp = '🔴 低'
                    md += f"| {k_item['keyword']} | #{pos} | {vol:,} | {comp or '—'} | {opp} |\n"
                md += "\n"

            elif not branded_kw and legacy_kw:
                md += f"### Top 排名关键词（共 {kw.get('total', 0):,} 个）\n\n"
                md += "| 关键词 | 排名 | 月搜索量 | CPC | 竞争度 |\n|--------|------|----------|-----|--------|\n"
                for k_item in legacy_kw:
                    md += f"| {k_item['keyword']} | #{k_item['position']} | {k_item.get('search_volume', 0):,} | ${k_item.get('cpc', 0):.2f} | {k_item.get('competition', '—')} |\n"
                md += "\n"

            # Error in rank data
            if rank.get("error") and not rank.get("organic_traffic"):
                md += f"> ⚠️ {rank['error']}\n\n"
        else:
            md += f"> {'⚠️ ' + tr.get('error', '') if tr.get('error') else '暂无流量数据'}\n\n"

    # Growth Analysis
    ga = s.get("growth_analysis", {})
    if ga and not ga.get("error"):
        md += "## 4. 增长深度分析\n\n"
        md += "> 📊 多渠道交叉增长分析 — 渠道拆解 · 0→1 故事线 · 多波 Launch\n\n"

        # --- Channel Breakdown ---
        cb = ga.get("channel_breakdown", {})
        if cb:
            active = cb.get("active_channels", [])
            dominant = cb.get("dominant_channel", "")
            md += "### 4.1 增长渠道拆解\n\n"
            if active:
                md += f"**活跃渠道**：{', '.join(active)}\n\n"
            if dominant:
                dominant_label = cb.get("channel_metrics", {}).get(dominant, {}).get("platform", dominant)
                md += f"**主导渠道**：{dominant_label}\n\n"

            # Channel metrics table
            cm = cb.get("channel_metrics", {})
            if cm:
                md += "#### 各渠道关键指标\n\n"
                md += "| 渠道 | 核心指标 | 数值 |\n|------|---------|------|\n"
                for ch_key, ch_data in cm.items():
                    platform = ch_data.get("platform", ch_key)
                    metrics_pairs = []
                    if ch_data.get("followers"): metrics_pairs.append(("Followers", f"{ch_data['followers']:,}"))
                    if ch_data.get("total_tweets"): metrics_pairs.append(("Tweets", f"{ch_data['total_tweets']:,}"))
                    if ch_data.get("top_tweet_likes"): metrics_pairs.append(("Top 推文 Likes", f"{ch_data['top_tweet_likes']:,}"))
                    if ch_data.get("avg_engagement"): metrics_pairs.append(("平均互动", f"{ch_data['avg_engagement']:,}"))
                    if ch_data.get("stars_total"): metrics_pairs.append(("Stars", f"{ch_data['stars_total']:,}"))
                    if ch_data.get("top_repo_stars"): metrics_pairs.append(("Top Repo Stars", f"{ch_data['top_repo_stars']:,}"))
                    if ch_data.get("total_mentions"): metrics_pairs.append(("提及次数", f"{ch_data['total_mentions']:,}"))
                    if ch_data.get("subreddit_members"): metrics_pairs.append(("Subreddit 成员", f"{ch_data['subreddit_members']:,}"))
                    if ch_data.get("monthly_traffic"): metrics_pairs.append(("月均流量", f"{ch_data['monthly_traffic']:,}"))
                    if ch_data.get("total_keywords"): metrics_pairs.append(("排名关键词", f"{ch_data['total_keywords']:,}"))
                    for label, val in metrics_pairs[:2]:
                        md += f"| {platform} | {label} | {val} |\n"
                md += "\n"

            # Content category stats
            tw_metrics = cm.get("twitter", {})
            content_cats = tw_metrics.get("content_categories", {})
            if content_cats:
                md += "#### Twitter 内容分类统计\n\n"
                md += "| 类型 | 推文数 |\n|------|--------|\n"
                cat_labels = {"launch": "发布/上线", "product_update": "产品更新", "community": "社区/互动", "tutorial": "教程/干货", "kol_collab": "KOL 合作", "other": "其他"}
                for cat, count in sorted(content_cats.items(), key=lambda x: x[1], reverse=True):
                    md += f"| {cat_labels.get(cat, cat)} | {count} |\n"
                md += "\n"

            # Top content
            top_content = cb.get("top_content", [])
            if top_content:
                md += "#### Top 内容表现（跨平台）\n\n"
                md += "| 平台 | 内容摘要 | Likes/Upvotes | 其他指标 |\n|------|---------|--------------|----------|\n"
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
            md += "### 4.2 0→1 成长故事线\n\n"
            first_seen = z2o.get("first_seen", "N/A")
            current_traffic = z2o.get("current_traffic", 0)
            growth_multiple = z2o.get("growth_multiple")
            md += f"**域名首次出现**：{first_seen}  \n"
            if current_traffic:
                md += f"**当前月均有机流量**：{current_traffic:,}  \n"
            if growth_multiple:
                md += f"**流量增长倍数**：{growth_multiple}x  \n"
            md += "\n"

            timeline = z2o.get("timeline", [])
            if timeline:
                md += "#### 关键事件时间线\n\n"
                md += "| 日期 | 类型 | 事件 | 来源 |\n|------|------|------|------|\n"
                type_labels = {"milestone": "🏁 里程碑", "launch": "🚀 发布", "traffic_spike": "📈 流量激增", "seo_milestone": "🔑 SEO 里程碑", "website_change": "🔄 官网变化"}
                for e in timeline:
                    date = e.get("date", "")[:10] if e.get("date") else "—"
                    etype = type_labels.get(e.get("type", ""), e.get("type", ""))
                    event_text = e.get("event", "")[:80].replace("|", "｜")
                    source = e.get("source", "")
                    md += f"| {date} | {etype} | {event_text} | {source} |\n"
                md += "\n"

            inflections = z2o.get("key_inflection_points", [])
            if inflections:
                md += "#### 关键拐点\n\n"
                for ip in inflections:
                    md += f"- **{ip.get('date', '')}** 流量从 {ip.get('traffic_before', 0):,} 增至 {ip.get('traffic_after', 0):,}（+{ip.get('growth_pct', 0)}%）\n"
                md += "\n"

        # --- Launch Waves ---
        lw = ga.get("launch_waves", {})
        if lw and lw.get("total_waves", 0) > 0:
            md += "### 4.3 多波 Launch 分析\n\n"
            md += f"**总 Launch 波次**：{lw['total_waves']}  \n"
            if lw.get("launch_cadence"):
                md += f"**Launch 节奏**：{lw['launch_cadence']}  \n"
            md += "\n"

            for wave in lw.get("launches", []):
                md += f"#### Wave {wave['wave_number']}：{wave.get('date_range', '')}\n\n"
                md += f"**渠道**：{', '.join(wave.get('channels', []))}  \n"
                impact = wave.get("total_impact", {})
                if impact.get("ph_votes"): md += f"**PH Votes**：{impact['ph_votes']:,}  \n"
                if impact.get("twitter_likes"): md += f"**Twitter Likes**：{impact['twitter_likes']:,}  \n"
                if impact.get("traffic_peak"): md += f"**流量峰值**：{impact['traffic_peak']:,}/月  \n"
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
        md += "## 5. Google Trends 流量峰值分析\n\n"
        md += "> 📊 **多源交叉归因分析** — Google Trends 热度数据 × PH/HN/Twitter 事件归因\n\n"
        tps = tp["summary"]
        md += f"**查询词**：{tps.get('primary_query', '')}  \n"
        md += f"**数据周数**：{tps.get('total_weeks', 0)}  \n"
        md += f"**峰值搜索热度**：{tps.get('max_interest', 0)}（{tps.get('max_interest_date', '')}）  \n"
        md += f"**平均热度**：{tps.get('avg_interest', 0)}  \n"
        md += f"**近期趋势**：{tps.get('recent_trend', 'N/A')}  \n"
        md += f"**当前阶段**：{tps.get('current_phase', 'N/A')}  \n"
        md += f"**检测到峰值数**：{tps.get('total_peaks_detected', 0)}（已关联 {tps.get('matched_peaks', 0)} 个，未匹配 {tps.get('unmatched_peaks', 0)} 个）  \n\n"

        # Growth phases with insights
        phases = tp.get("growth_phases", [])
        if phases:
            md += "### 增长阶段划分\n\n"
            for ph in phases:
                channels = ph.get("active_channels", [])
                ch_str = " · ".join(channels) if channels else "—"
                peak_count = ph.get("peak_count", 0)
                md += f"**{ph['phase']}** ({ph['start_date']} → {ph['end_date']}, {ph['week_count']}周, 均值 {ph['avg_value']})  \n"
                md += f"活跃渠道: {ch_str}"
                if peak_count:
                    md += f" | 峰值事件: {peak_count}个"
                md += "  \n"
                for insight in ph.get("insights", []):
                    md += f"- {insight}\n"
                md += "\n"

        # Detected peaks — with attribution
        peaks = tp.get("detected_peaks", [])
        if peaks:
            md += "### 检测到的峰值事件\n\n"
            for i, pk in enumerate(peaks, 1):
                status = pk.get("status", "unmatched")
                attr = pk.get("attribution", {})

                # Status badge
                if status == "attributed":
                    status_badge = f"**归因**: {attr.get('primary_channel', '?')}（{'高可信度' if attr.get('confidence') == 'high' else '中等可信度'}）"
                elif status == "ph_matched":
                    status_badge = "**归因**: Product Hunt 发布"
                else:
                    status_badge = "**归因**: 未找到明确来源"

                md += f"### 峰值事件 #{i}: {pk.get('peak_date_label', '')} （热度: {pk.get('peak_value', 0)}/100）\n\n"
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
                        md += f"**{channel_icon} {src['channel']}**（impact score: {src['impact_score']}）\n"
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
                        delta_str = f"峰值晚于 Launch {delta} 天" if delta >= 0 else f"峰值早于 Launch {abs(delta)} 天"
                        md += f"- 🏆 {m.get('label', '')} （{delta_str}）\n"
                    md += "\n"
                else:
                    md += f"> {attr.get('summary', pk.get('hypothesis', '未找到明确来源'))}\n\n"

        # Unmatched peaks summary
        unmatched = tp.get("unmatched_peaks", [])
        if unmatched:
            md += "### 疑似未记录的 Launch 事件\n\n"
            for pk in unmatched:
                attr = pk.get("attribution", {})
                summary = attr.get("summary") or pk.get("hypothesis", "")
                md += f"- **{pk.get('peak_date_label', '')}** 热度峰值 {pk.get('peak_value', 0)}：{summary}\n"
            md += "\n"

    # Propagation Analysis
    prop = s.get("propagation", {})
    if prop and not prop.get("error") and prop.get("data_mode") not in (None, "empty"):
        md += "## 6. 传播深度分析\n\n"

        root = prop.get("root_post", {})
        if root.get("text"):
            md += f"**Launch 帖**：{root['text'][:150]}  \n"
            md += f"**互动数据**：❤️{root.get('likes',0):,} 🔄{root.get('retweets',0):,} 💬{root.get('replies',0):,} 👁{root.get('views',0):,}  \n\n"

        # Approximate analysis (降级模式)
        approx = prop.get("approximate_analysis")
        if approx:
            md += f"> {approx.get('note', '')}  \n\n"
            agg = approx.get("aggregate_metrics", {})
            if agg:
                md += "### 聚合指标（近似）\n\n"
                md += f"- 总 Retweets：{agg.get('total_retweets', 0):,}\n"
                md += f"- 总 Likes：{agg.get('total_likes', 0):,}\n"
                md += f"- 总 Views：{agg.get('total_views', 0):,}\n"
                md += f"- 平均互动/推文：{agg.get('avg_engagement_per_tweet', 0)}\n\n"
            est = approx.get("propagation_estimate", {})
            if est.get("estimated_reach"):
                md += f"**预估触达人数**：{est['estimated_reach']:,}  \n"
            if est.get("viral_coefficient"):
                md += f"**病毒系数（RT/推文）**：{est['viral_coefficient']}  \n\n"
        else:
            # Full mode: KOL + four-stage
            inf = prop.get("influencer_analysis", {})
            if inf.get("total_kols", 0) > 0:
                md += f"**KOL 参与数（10K+ 粉丝）**：{inf['total_kols']}  \n\n"

                top_inf = inf.get("top_influencers", [])
                if top_inf:
                    md += "### Top 影响者\n\n"
                    md += "| 账号 | 粉丝 | 类型 | 参与时间 |\n|------|------|------|----------|\n"
                    for u in top_inf[:8]:
                        hours = f"{u.get('hours_after_launch', '?')}h" if u.get('hours_after_launch') is not None else "N/A"
                        md += f"| @{u['screen_name']} | {u.get('followers',0):,} | {u.get('user_type','')} | {hours} |\n"
                    md += "\n"

            # Four stage
            stages = prop.get("four_stage_timeline", {})
            if stages:
                md += "### 四阶段传播模型\n\n"
                md += "| 阶段 | 标签 | 参与人数 |\n|------|------|----------|\n"
                for stage_key, stage_data in stages.items():
                    md += f"| {stage_key} | {stage_data.get('label','')} | {stage_data.get('count',0)} |\n"
                md += "\n"

            # Propagation rhythm
            rhythm = prop.get("propagation_rhythm", {})
            if rhythm:
                md += "### 传播节奏\n\n"
                md += "| 时间窗口 | 参与人数 | 粉丝触达 |\n|----------|----------|----------|\n"
                for bk, bv in rhythm.items():
                    md += f"| {bv.get('label', bk)} | {bv.get('count', 0)} | {bv.get('total_followers_reached', 0):,} |\n"
                md += "\n"

    # Summary
    md += "## 7. 综合评估\n\n"
    for f in s["summary"]["findings"]:
        md += f"- {f}\n"

    # Growth Strategy
    gs = s.get("growth_strategy", {})
    if gs and not gs.get("error") and gs.get("primary"):
        md += "\n## 8. 定制增长策略（Gingiris Playbook 推荐）\n\n"
        md += "> 💡 **Gingiris Playbook 独家推荐** — 基于 Wayback 历史 + PH Launch + 社交传播的交叉分析自动匹配\n\n"
        primary = gs["primary"]
        secondary = gs.get("secondary", [])
        gt = gs.get("growth_tools")

        md += f"### {primary.get('emoji', '📘')} 主推：{primary.get('label', '')}\n\n"
        md += f"> 👉 [{primary.get('label', '')}]({primary.get('url', '')})\n\n"
        md += f"{primary.get('description', '')}\n\n"

        reasons = primary.get("reasons", [])
        if reasons:
            md += "**匹配原因**\n\n"
            for r in reasons:
                md += f"- ✓ {r}\n"
            md += "\n"

        tips = primary.get("custom_tips", [])
        if tips:
            md += "**🎯 定制建议（基于竞品数据）**\n\n"
            for i, tip in enumerate(tips, 1):
                md += f"{i}. {tip}\n"
            md += "\n"

        if secondary:
            md += "### 辅助 Playbook\n\n"
            for s_pb in secondary:
                md += f"- {s_pb.get('emoji', '')} **{s_pb.get('label', '')}**：{s_pb.get('url', '')}\n"
                if s_pb.get("reasons"):
                    md += f"  - {s_pb['reasons'][0]}\n"
                if s_pb.get("custom_tips"):
                    md += f"  - 💡 {s_pb['custom_tips'][0]}\n"
            md += "\n"

        if gt:
            md += f"### {gt.get('emoji', '🛠️')} 配套工具库\n\n"
            md += f"> [{gt.get('label', '')}]({gt.get('url', '')})  \n"
            md += f"> {gt.get('description', '')}\n\n"

    md += "\n---\n*报告由竞品调研工具自动生成，部分数据需手动验证。*\n"
    return md


import math as _math

def _compute_strategy_radar(sections: dict) -> dict:
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
        {"key": "product", "label": "产品力", "score": product_score, "emoji": "🎯"},
        {"key": "social", "label": "社交影响力", "score": social_score, "emoji": "📢"},
        {"key": "seo", "label": "SEO 权威度", "score": seo_score, "emoji": "🔍"},
        {"key": "community", "label": "开源/社区", "score": community_score, "emoji": "💻"},
        {"key": "content", "label": "内容引擎", "score": content_score, "emoji": "📝"},
        {"key": "launch", "label": "Launch 执行力", "score": launch_score, "emoji": "🚀"},
    ]

    total = sum(d["score"] for d in dimensions)
    avg = int(total / len(dimensions))

    return {
        "dimensions": dimensions,
        "total_score": total,
        "avg_score": avg,
    }
