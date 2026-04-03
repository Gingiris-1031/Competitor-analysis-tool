"""定制增长策略模块 — 基于竞品数据自动匹配 Gingiris Playbook（纯规则引擎，无 LLM 调用）"""

PLAYBOOKS = {
    "gingiris-launch": {
        "name": "gingiris-launch",
        "label": "GTM 打榜 Playbook",
        "emoji": "🚀",
        "url": "https://github.com/Gingiris/gingiris-launch",
        "description": "Product Hunt 多波 Launch 全流程指南 — 从 L-6 周倒计时到发布后复盘",
    },
    "gingiris-b2b-growth": {
        "name": "gingiris-b2b-growth",
        "label": "B2B 增长 Playbook",
        "emoji": "🏢",
        "url": "https://github.com/Gingiris/gingiris-b2b-growth",
        "description": "B2B SaaS 从 0 到 100 企业客户的销售与渠道增长手册",
    },
    "gingiris-opensource": {
        "name": "gingiris-opensource",
        "label": "OSS 冷启动 Playbook",
        "emoji": "⭐",
        "url": "https://github.com/Gingiris/gingiris-opensource",
        "description": "开源项目从 0 到 60K stars 的社区冷启动完整路线图",
    },
    "growth-tools": {
        "name": "growth-tools",
        "label": "增长工具库",
        "emoji": "🛠️",
        "url": "https://github.com/Gingiris/growth-tools",
        "description": "增长黑客精选工具集合，配套任意 Playbook 使用",
    },
}


def recommend_playbooks(report_data: dict) -> dict:
    """
    基于竞品报告数据自动推荐 Playbook 组合。

    Args:
        report_data: generate_report() 返回的完整报告 dict
                     也接受 job["results"] 形式的 raw results dict

    Returns:
        {
            "primary": {"playbook": "gingiris-launch", "score": 3, "reasons": [...], "custom_tips": [...], "url": "...", ...},
            "secondary": [...],
            "growth-tools": {...},   # 始终附加
        }
    """
    # Support both report["sections"] format and raw results dict
    sections = report_data.get("sections", report_data)

    # Unpack data sources
    website = sections.get("website_analysis") or sections.get("website") or {}
    social = sections.get("social_media") or sections.get("social") or {}
    traffic = sections.get("traffic_analysis") or sections.get("traffic") or {}
    ph = sections.get("producthunt") or {}
    growth = sections.get("growth_analysis") or {}
    peaks = sections.get("traffic_peaks") or {}
    product_name = report_data.get("meta", {}).get("product_name", "") or report_data.get("product_name", "")
    url = report_data.get("meta", {}).get("url", "") or report_data.get("url", "")

    # Helper accessors
    current = website.get("current", {}) or {}
    if not current and isinstance(website.get("current_site"), dict):
        current = website["current_site"]
    features = current.get("features", {}) or {}
    channels = social.get("channels", {}) or {}
    tw = channels.get("twitter", {}) or {}
    gh = channels.get("github", {}) or {}
    rd = channels.get("reddit", {}) or {}

    # ── Score each playbook ──────────────────────────────────────────────────
    scores = {k: {"score": 0, "reasons": [], "custom_tips": []} for k in PLAYBOOKS}

    # ── gingiris-launch ──────────────────────────────────────────────────────
    ls = scores["gingiris-launch"]

    # PH launch found
    if ph.get("found"):
        ls["score"] += 1
        launch_count = 1 + len(ph.get("other_launches", []))
        votes = ph.get("votes", 0)
        ls["reasons"].append(f"竞品已在 Product Hunt 发布 {launch_count} 次（最高 {votes:,} votes）")
        if launch_count >= 2:
            ls["custom_tips"].append(
                f"竞品通过 {launch_count} 波 PH 多次 Launch 保持持续曝光。"
                f"参考 Playbook「多波 Launch」节奏——每隔 3-4 个月发一次，每次聚焦不同功能点。"
            )
        else:
            ls["custom_tips"].append(
                f"竞品做过 PH Launch 并拿到 {votes:,} votes。参考 Playbook 第 3 章「L-6 周倒计时」规划首次发布。"
            )

    # Twitter followers + launch tweets
    tw_followers = tw.get("followers") or 0
    if tw_followers > 1000 and tw.get("detected"):
        ls["score"] += 1
        ls["reasons"].append(f"竞品 Twitter {tw_followers:,} followers，社交传播是主要增长引擎")
        ls["custom_tips"].append(
            f"竞品 Twitter 有 {tw_followers:,} followers，在 PH Launch 时 Twitter 是主力放大器。"
            "建议先建立自己的 Twitter 阵地再规划 PH 发布节点。"
        )

    # Video / demo on website
    if features.get("video") or features.get("demo"):
        ls["score"] += 1
        ls["reasons"].append("官网有品牌视频或 Demo，产品展示完善，适合 Launch 驱动传播")
        ls["custom_tips"].append(
            "竞品有 Demo/视频，PH 发布页最重要的是 First Thumbnail — 参考 Playbook 第 5 章视觉资产清单。"
        )

    # Traffic peaks / growth phases
    peaks_summary = peaks.get("summary", {}) or {}
    growth_phases = peaks.get("growth_phases", []) or []
    has_peak_growth = any(
        p.get("phase", "").lower() in ("growth", "爆发期", "增长期", "climbing")
        for p in growth_phases
    )
    if has_peak_growth or peaks_summary.get("current_phase") in ("growth", "爬坡期", "爆发期"):
        ls["score"] += 1
        phase = peaks_summary.get("current_phase", "爬坡期")
        ls["reasons"].append(f"竞品流量处于「{phase}」——趋势窗口尚未关闭，赶上 Launch 时机")
        max_date = peaks_summary.get("max_interest_date", "")
        if max_date:
            ls["custom_tips"].append(
                f"竞品 Google Trends 在 {max_date} 前后出现流量爆发峰值。"
                "若你有融资/功能里程碑，可与 Launch 时间节点对齐，借势放大曝光。"
            )

    # ── gingiris-b2b-growth ──────────────────────────────────────────────────
    bs = scores["gingiris-b2b-growth"]

    if features.get("pricing"):
        bs["score"] += 1
        bs["reasons"].append("官网有定价页面（含 Enterprise/Team 方案），产品已进入商业化阶段")
        bs["custom_tips"].append(
            "竞品已有定价页面。对标 Playbook「定价页心理学」章节——重点看其 Enterprise CTA 的话术设计。"
        )

    if features.get("logos"):
        bs["score"] += 1
        bs["reasons"].append("官网有客户 Logo 墙，B2B 社会证明已建立")
        bs["custom_tips"].append(
            "竞品 Logo 墙已成为重要的 B2B 信任背书。Playbook 第 7 章有 Logo 墙设计和主动邀请客户展示的 SOP。"
        )

    linkedin_ch = channels.get("linkedin", {}) or {}
    if linkedin_ch.get("detected") or linkedin_ch.get("detected") is None:
        if linkedin_ch.get("url") or linkedin_ch.get("detected") is None:
            bs["score"] += 1
            bs["reasons"].append("LinkedIn 渠道存在或待确认，B2B 决策者触达路径清晰")
            bs["custom_tips"].append(
                "Playbook 的 LinkedIn 章节包含「产品更新推文转 LinkedIn 文章」的内容复用 SOP，ROI 极高。"
            )

    # Case study / blog / docs
    if features.get("blog") or features.get("docs"):
        bs["score"] += 1
        bs["reasons"].append("有博客/文档，内容营销和 SEO 基础已就绪")
        bs["custom_tips"].append(
            "竞品有内容体系。Playbook 第 9 章「客户案例裂变」——如何把第一个付费客户变成 Case Study 并反哺销售。"
        )

    # ── gingiris-opensource ──────────────────────────────────────────────────
    os_s = scores["gingiris-opensource"]

    gh_stars = gh.get("stars_total") or 0
    if gh.get("detected") or gh_stars > 0:
        os_s["score"] += 1
        stars_str = f"{gh_stars:,} stars" if gh_stars else "已检测到 GitHub 账号"
        os_s["reasons"].append(f"竞品在 GitHub 有活跃存在（{stars_str}）")
        if gh_stars > 100:
            os_s["custom_tips"].append(
                f"竞品 GitHub 已有 {gh_stars:,} stars。Playbook 第 2 章「README 黄金首屏」——竞品怎么写 README，你就反向拆解它的 Hook 点。"
            )
        else:
            os_s["custom_tips"].append(
                "竞品有 GitHub 存在。Playbook 第 1 章「开源冷启动的第一个 100 stars」——社区选择 > 流量购买。"
            )

    # HN/Reddit mentions in traffic attribution
    peak_events = peaks.get("detected_peaks", []) or []
    has_hn = any(
        src.get("channel") == "Hacker News"
        for pk in peak_events
        for src in (pk.get("attribution", {}).get("all_sources") or [])
    )
    if has_hn:
        os_s["score"] += 1
        os_s["reasons"].append("竞品在 Hacker News 有显著讨论，开发者社区认知度高")
        os_s["custom_tips"].append(
            "竞品曾登上 HN 并带来流量峰值。Playbook 第 4 章「如何写一篇 HN Show HN」——从标题到第一条评论的完整 SOP。"
        )

    if rd.get("detected") and (rd.get("total_mentions", 0) or 0) > 5:
        os_s["score"] += 1
        mentions = rd.get("total_mentions", 0)
        os_s["reasons"].append(f"Reddit 有 {mentions} 次提及，社区口碑已在发酵")
        os_s["custom_tips"].append(
            f"竞品 Reddit 已有 {mentions} 次提及。Playbook 第 5 章「Reddit 冷启动」——不要直接推销，从 r/roastmyproduct 开始建立可信度。"
        )

    # Public repos
    gh_repos = gh.get("public_repos") or 0
    if gh_repos > 0:
        os_s["score"] += 1
        os_s["reasons"].append(f"竞品有 {gh_repos} 个公开 GitHub 仓库，开源策略清晰")

    # ── growth-tools（始终推荐）────────────────────────────────────────────
    # Calculated last, after others are scored

    # ── Rank and build output ────────────────────────────────────────────────
    MIN_SCORE = 2
    ranked = sorted(
        [k for k in ["gingiris-launch", "gingiris-b2b-growth", "gingiris-opensource"] if scores[k]["score"] >= MIN_SCORE],
        key=lambda k: scores[k]["score"],
        reverse=True,
    )

    # If nothing qualifies, take highest scorer anyway
    if not ranked:
        ranked = sorted(
            ["gingiris-launch", "gingiris-b2b-growth", "gingiris-opensource"],
            key=lambda k: scores[k]["score"],
            reverse=True,
        )[:1]

    def build_entry(key: str) -> dict:
        pb = PLAYBOOKS[key]
        sc = scores[key]
        return {
            "playbook": key,
            "label": pb["label"],
            "emoji": pb["emoji"],
            "url": pb["url"],
            "description": pb["description"],
            "score": sc["score"],
            "reasons": sc["reasons"],
            "custom_tips": sc["custom_tips"],
        }

    primary = build_entry(ranked[0]) if ranked else None
    secondary = [build_entry(k) for k in ranked[1:]]

    # growth-tools always appended as auxiliary
    gt_pb = PLAYBOOKS["growth-tools"]
    growth_tools_entry = {
        "playbook": "growth-tools",
        "label": gt_pb["label"],
        "emoji": gt_pb["emoji"],
        "url": gt_pb["url"],
        "description": gt_pb["description"],
        "score": 0,
        "reasons": ["配套任意 Playbook 使用，提供精选增长工具集"],
        "custom_tips": ["把竞品用过的工具逐一对标，优先使用相同工具栈可节省 60% 的踩坑时间。"],
    }

    return {
        "primary": primary,
        "secondary": secondary,
        "growth_tools": growth_tools_entry,
        "all_scores": {k: scores[k]["score"] for k in scores},
        "product_name": product_name,
    }


def build_qa_playbook_context(growth_strategy: dict, question: str) -> str:
    """
    为 QA prompt 构建 Playbook 推荐注入文本。
    当 growth_strategy 有推荐时，返回可直接注入 prompt 的文本块。
    """
    if not growth_strategy or not growth_strategy.get("primary"):
        return ""

    product_name = growth_strategy.get("product_name", "该竞品")
    primary = growth_strategy["primary"]
    secondary = growth_strategy.get("secondary", [])
    gt = growth_strategy.get("growth_tools")

    # Detect if question is growth-related
    growth_keywords = [
        "launch", "发布", "ph", "product hunt", "上线",
        "b2b", "企业", "sales", "渠道", "获客",
        "开源", "github", "star", "community", "社区",
        "工具", "tool", "推荐", "怎么做", "增长", "策略",
        "如何", "growth",
    ]
    q_lower = question.lower()
    is_growth_question = any(kw in q_lower for kw in growth_keywords)

    lines = []
    lines.append("\n## 定制增长策略（Gingiris Playbook 推荐）")
    lines.append(
        f"基于对 {product_name} 的竞品分析，系统已自动匹配以下 Playbook："
    )
    lines.append(
        f"\n### 主推 Playbook：{primary['emoji']} {primary['label']}"
    )
    lines.append(f"链接：{primary['url']}")
    lines.append(f"匹配原因：" + "；".join(primary["reasons"][:3]) if primary["reasons"] else "")
    if primary["custom_tips"]:
        lines.append("定制建议：")
        for tip in primary["custom_tips"][:3]:
            lines.append(f"- {tip}")

    if secondary:
        lines.append("\n### 辅助 Playbook")
        for s in secondary[:2]:
            lines.append(f"- {s['emoji']} **{s['label']}**：{s['url']}")
            if s["reasons"]:
                lines.append(f"  原因：{s['reasons'][0]}")

    if gt:
        lines.append(f"\n### 工具库")
        lines.append(f"- {gt['emoji']} **{gt['label']}**：{gt['url']}")

    if is_growth_question:
        lines.append(
            "\n> **请在回答中自然融入上述 Playbook 推荐**，"
            "用具体的竞品数据支撑建议，让用户明白为什么推荐这个 Playbook，"
            "并在合适位置附上链接。不要生硬地列清单——像顾问一样自然地提及。"
        )
    else:
        lines.append(
            "\n> 若本问题涉及增长策略方向，可在回答末尾简短提及最相关的 Playbook 供用户参考。"
        )

    return "\n".join(lines)
