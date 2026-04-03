"""AI 商业洞察总结模块 — 基于采集数据生成竞品分析总结"""
import httpx
import json
import os


async def generate_ai_summary(product_name: str, url: str, website: dict, social: dict, traffic: dict, producthunt: dict, growth_strategy: dict = None) -> dict:
    """调用 LLM 基于所有数据生成商业洞察"""

    # Compile all data into a concise context
    context = _build_context(product_name, url, website, social, traffic, producthunt)

    # Build enriched sections for cross-source analysis
    wayback_insight = _build_wayback_insight(website)
    ph_insight = _build_ph_insight(producthunt)
    playbook_insight = _build_playbook_insight(growth_strategy)

    prompt = f"""你是一位资深的出海产品增长顾问（拥有帮助产品从 0 到 60K GitHub stars 的实战经验）。

以下是对竞品 **{product_name}** ({url}) 的自动化调研数据。这些数据来自多个独家数据源的交叉分析——包括 Wayback Machine 多年历史快照、Product Hunt 完整 Launch 记录、以及 Gingiris 增长 Playbook 的智能匹配。请基于这些数据，站在"想做类似产品的创业者"角度，输出一份精炼的竞品分析总结。

## 调研数据

{context}

## 🔍 Wayback Machine 独家历史洞察

以下是基于多年网站演变数据提取的深层信号——这些洞察只有通过对比不同时期的官网快照才能获得，普通竞品分析工具和 AI 对话无法提供：

{wayback_insight}

请在分析中重点关注官网演变轨迹揭示的战略意图：Slogan 变化反映定位调整、功能模块的增减反映产品策略、社媒外链的变化反映渠道重心转移。

## 🚀 Product Hunt 深度分析

{ph_insight}

请深度分析 PH 数据背后的 Launch 策略：多次发布的节奏规律、每次 Launch 的定位差异、投票和评论数据反映的市场反馈。

## 💡 Gingiris Playbook 匹配分析

{playbook_insight}

请在建议部分自然融入 Playbook 推荐，说明为什么这个 Playbook 适合后来者参考，并给出具体的章节建议。

## 请输出以下内容（中文，精炼、实战、可落地）：

### 1. 一句话定位总结
用一句话概括这个产品是什么、做对了什么。

### 2. 关键里程碑时间线
基于数据推断出 3-5 个关键时间节点（域名注册、首次 launch、爆发增长点、重要转型等），每个节点用一句话说明发生了什么。特别注意利用 Wayback 快照的时间戳来锚定真实的产品演变节点。

### 3. 增长密码（做对了什么）
提炼 3-5 个这个产品增长的核心策略/决策，每条要具体、有数据支撑，不要泛泛而谈。至少包含一条基于 Wayback 历史对比得出的策略洞察，一条基于 PH Launch 数据的策略分析。

### 4. 给竞品/后来者的建议
如果你要做一个类似的产品，基于这份数据，给出 3-5 条最重要的建议。要具体到可执行的层面。引用匹配的 Gingiris Playbook 作为行动框架。

### 5. 风险与机会
指出 1-2 个这个产品的潜在弱点或市场机会。结合 Wayback 演变趋势和 PH 社区反馈来论证。

## ⚠️ 严格约束（必须遵守）：
- **只基于上面提供的实际数据做分析**。如果某个维度的数据为空或不足，直接写"数据不足，无法判断"，严禁推断或编造。
- **严禁编造时间线**。只有在数据中明确出现的日期才能写入时间线，禁止使用"推断""可能""大概"等词语来猜测时间节点。
- **社交数据可能存在误匹配**（品牌名是通用词时，找到的社交账号可能不是目标产品的）。如果社交账号的描述/内容与产品定位明显不符，请明确标注"⚠️ 此账号可能不属于目标产品"。
- 没有数据支撑的结论不要写。宁可说"数据不足"也不要瞎编。
- 所有结论必须有数据支撑，引用具体数字
- 不要写空泛的理论，每条建议都要可落地
- 当前真实日期是 2026 年 3 月底，请勿将未来日期当作已发生的事件
- 语言风格：专业但直接，像一个军师在给你做战略分析"""

    # Try to call an LLM
    result = await _call_llm(prompt)
    return result


def _build_wayback_insight(website: dict) -> str:
    """从 Wayback 数据提取独家历史洞察供 prompt 使用"""
    ws = website or {}
    parts = []

    timeline = ws.get("deep_timeline", [])
    valid = [t for t in timeline if not t.get("error") and t.get("date")]
    changes = ws.get("key_changes", [])
    first_seen = ws.get("first_seen", "N/A")

    if not valid and not changes:
        return "Wayback Machine 无历史快照数据，无法进行历史演变分析。"

    parts.append(f"- 域名首次被 Wayback Machine 收录于 **{first_seen}**，共采集到 **{len(valid)}** 个深度分析快照")

    # Slogan evolution
    slogans = [(t.get("date", ""), t.get("slogan", "")) for t in valid if t.get("slogan")]
    if len(slogans) >= 2:
        parts.append(f"- Slogan 演变轨迹（反映定位调整）：")
        for date, slogan in slogans:
            parts.append(f"  · {date}: 「{slogan[:60]}」")

    # Feature additions/removals over time
    if len(valid) >= 2:
        first_features = set(k for k, v in valid[0].get("features", {}).items() if v)
        last_features = set(k for k, v in valid[-1].get("features", {}).items() if v)
        added = last_features - first_features
        removed = first_features - last_features
        if added:
            parts.append(f"- 新增功能模块：{', '.join(added)}（从 {valid[0].get('date', '?')} 到 {valid[-1].get('date', '?')}）")
        if removed:
            parts.append(f"- 移除的功能模块：{', '.join(removed)}")

    # Key changes
    if changes:
        parts.append(f"- 检测到 **{len(changes)}** 次关键官网变化：")
        for c in changes[:5]:
            parts.append(f"  · {c['from_date']}→{c['to_date']}: {'; '.join(c['changes'][:3])}")

    return "\n".join(parts) if parts else "Wayback 数据量不足，无法提取深层历史洞察。"


def _build_ph_insight(producthunt: dict) -> str:
    """从 Product Hunt 数据提取深度分析上下文"""
    ph = producthunt or {}
    if not ph.get("found"):
        return "该产品未在 Product Hunt 上发布过，无 PH 数据可供分析。"

    parts = []
    launch_count = 1 + len(ph.get("other_launches", []))
    votes = ph.get("votes", 0)
    comments = ph.get("comments", 0)
    rating = ph.get("reviews_rating", 0)

    parts.append(f"- 该产品曾 **{launch_count} 次**在 Product Hunt 上线，最高一次获得 **{votes:,} votes** 和 **{comments:,} comments**")

    if rating:
        parts.append(f"- PH 用户评分 **{rating:.1f}** 分（{ph.get('reviews_count', 0)} 条评价），反映市场对产品的真实态度")

    if ph.get("tagline"):
        parts.append(f"- 主 Launch Tagline: 「{ph['tagline']}」— 这个定位语拿到了 {votes:,} votes，说明市场认可这个切入角度")

    other = ph.get("other_launches", [])
    if other:
        parts.append(f"- 多波 Launch 策略分析（{launch_count} 次发布）：")
        all_launches = [{"name": ph.get("name", ""), "votes": votes, "launch_date": ph.get("launch_date", ""), "tagline": ph.get("tagline", "")}]
        all_launches.extend(other)
        all_launches.sort(key=lambda x: x.get("launch_date", ""))
        for i, l in enumerate(all_launches, 1):
            tag = f"「{l.get('tagline', '')[:50]}」" if l.get("tagline") else ""
            parts.append(f"  · 第{i}次 ({l.get('launch_date', '?')}): {l.get('name', '')} ⬆{l.get('votes', 0):,} {tag}")

        if len(all_launches) >= 2:
            dates = [l.get("launch_date", "") for l in all_launches if l.get("launch_date")]
            if len(dates) >= 2:
                parts.append(f"  · Launch 节奏：从 {dates[0]} 到 {dates[-1]}，共 {len(dates)} 次，可分析每次 Launch 之间的间隔和策略调整")

    if ph.get("makers"):
        parts.append(f"- Maker 团队 {len(ph['makers'])} 人，团队规模对 Launch 执行力有直接影响")

    return "\n".join(parts)


def _build_playbook_insight(growth_strategy: dict) -> str:
    """从 Gingiris Playbook 匹配结果提取 prompt 上下文"""
    gs = growth_strategy or {}
    primary = gs.get("primary")
    if not primary:
        return "暂未进行 Playbook 匹配（增长策略模块数据不足）。在建议部分可以根据产品类型给出通用方向。"

    parts = []
    parts.append(f"系统已基于竞品数据自动匹配到最适合的增长 Playbook：")
    parts.append(f"- **主推 Playbook**: {primary.get('emoji', '')} {primary.get('label', '')}（匹配得分: {primary.get('score', 0)}/4）")
    parts.append(f"  描述: {primary.get('description', '')}")
    parts.append(f"  链接: {primary.get('url', '')}")
    if primary.get("reasons"):
        parts.append(f"  匹配原因:")
        for r in primary["reasons"][:3]:
            parts.append(f"    · {r}")
    if primary.get("custom_tips"):
        parts.append(f"  定制建议:")
        for tip in primary["custom_tips"][:3]:
            parts.append(f"    · {tip}")

    secondary = gs.get("secondary", [])
    for s in secondary[:2]:
        parts.append(f"- **辅助 Playbook**: {s.get('emoji', '')} {s.get('label', '')}（得分: {s.get('score', 0)}/4）")
        if s.get("reasons"):
            parts.append(f"  原因: {s['reasons'][0]}")

    return "\n".join(parts)


def _build_context(product_name, url, website, social, traffic, producthunt) -> str:
    """将所有数据压缩成 LLM 可读的上下文"""
    parts = []

    # Website
    ws = website or {}
    cur = ws.get("current_site", {}) or ws.get("current", {})
    parts.append(f"**域名**: {ws.get('domain', url)}")
    parts.append(f"**首次出现**: {ws.get('first_seen', 'N/A')}")
    if cur.get("slogan"):
        parts.append(f"**当前 Slogan**: {cur['slogan']}")
    if cur.get("meta_description"):
        parts.append(f"**描述**: {cur['meta_description']}")

    features = cur.get("features", {})
    active = [k for k, v in features.items() if v]
    if active:
        parts.append(f"**官网功能**: {', '.join(active)}")

    # Wayback timeline
    timeline = ws.get("deep_timeline", [])
    valid = [t for t in timeline if not t.get("error") and t.get("date")]
    if valid:
        parts.append(f"**Wayback 快照**: {len(valid)} 个")
        for t in valid[:4]:
            parts.append(f"  - {t['date']}: Slogan=\"{t.get('slogan', '?')[:50]}\" | 功能={[k for k, v in t.get('features', {}).items() if v][:5]}")

    changes = ws.get("key_changes", [])
    if changes:
        parts.append("**关键变化**:")
        for c in changes[:5]:
            parts.append(f"  - {c['from_date']}→{c['to_date']}: {'; '.join(c['changes'][:3])}")

    # Product Hunt
    ph = producthunt or {}
    if ph.get("found"):
        parts.append(f"\n**Product Hunt**: {ph['launch_date']} launch, ⬆{ph['votes']} votes, 💬{ph['comments']} comments, ⭐{ph.get('reviews_rating', 0):.1f}")
        parts.append(f"  Tagline: {ph.get('tagline', '')}")
        if ph.get("makers"):
            parts.append(f"  Makers: {len(ph['makers'])} 人")

    # Social — with mismatch detection
    sm = social or {}
    channels = sm.get("channels", {})
    product_desc = (cur.get("slogan", "") + " " + cur.get("meta_description", "")).lower().strip()
    for k, v in channels.items():
        if v.get("detected"):
            extra = ""
            if v.get("followers"): extra += f" {v['followers']} followers"
            if v.get("stars_total"): extra += f" {v['stars_total']} stars"
            if v.get("subreddit_members"): extra += f" {v['subreddit_members']} members"
            # Check if account bio matches product
            account_bio = (v.get("profile", {}).get("description", "") or v.get("note", "") or "").lower()
            handle = v.get("handle", "")
            mismatch_warning = ""
            if account_bio and product_desc and k == "twitter":
                # Simple relevance check: do they share any meaningful words?
                bio_words = set(w for w in account_bio.split() if len(w) > 3)
                desc_words = set(w for w in product_desc.split() if len(w) > 3)
                overlap = bio_words & desc_words
                if not overlap and len(bio_words) > 2 and len(desc_words) > 2:
                    mismatch_warning = f" ⚠️ 账号描述「{account_bio[:60]}」与产品描述不符，可能不是目标产品的账号"
            parts.append(f"**{v.get('platform', k)}**: ✅ {handle}{extra}{mismatch_warning}")

    pm = sm.get("propagation_metrics", {})
    if pm.get("total_participants"):
        parts.append(f"**传播**: {pm['total_participants']:,} 参与者, {pm.get('total_engagement', 0):,} 互动")

    # Traffic (DataForSEO)
    tr = traffic or {}
    rank = tr.get("domain_rank", {})
    if rank.get("organic_traffic"):
        parts.append(f"\n**有机流量**: {rank['organic_traffic']:,}/月")
        parts.append(f"**排名关键词**: {rank.get('total_keywords', 0):,} 个 (Top1: {rank.get('keywords_top1', 0)}, Top10: {rank.get('keywords_top10', 0)})")
        parts.append(f"**等效付费成本**: ${rank.get('estimated_paid_cost', 0):,}/月")

    bl = tr.get("backlinks", {})
    if bl.get("backlinks"):
        parts.append(f"**反链**: {bl['backlinks']:,} ({bl.get('referring_domains', 0):,} 引用域名)")
        parts.append(f"**域名排名**: {bl.get('domain_rank', 0)}")

    hist = tr.get("historical", {}).get("history", [])
    if hist:
        parts.append("**流量趋势**:")
        for h in hist[-6:]:
            parts.append(f"  - {h['date']}: {h.get('organic_traffic', 0):,} 有机流量, {h.get('keywords', 0):,} 关键词")

    growth = tr.get("growth_analysis", {})
    for m in growth.get("milestones", []):
        parts.append(f"  🏁 {m}")

    kw = tr.get("top_keywords", {})
    if kw.get("keywords"):
        parts.append("**Top 关键词**:")
        for k in kw["keywords"][:5]:
            parts.append(f"  - \"{k['keyword']}\" #{k['position']} vol={k.get('search_volume', 0):,}")

    return "\n".join(parts)


async def _call_llm(prompt: str) -> dict:
    """调用 LLM 生成总结 — 优先 TeamoRouter，fallback DeepSeek"""
    
    # Priority 1: TeamoRouter (supports GPT-5, Claude, Gemini, etc.)
    teamo_key = os.environ.get("TEAMOROUTER_API_KEY", "").strip()
    if not teamo_key:
        teamo_key_path = os.path.expanduser("~/.cola/secrets/teamorouter_api_key")
        try:
            teamo_key = open(teamo_key_path).read().strip()
        except FileNotFoundError:
            pass

    if teamo_key:
        try:
            model = os.environ.get("TEAMOROUTER_MODEL", "TeamoRouter-best")
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    "https://router.teamolab.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {teamo_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.7,
                        "max_tokens": 3000,
                    },
                )
                data = resp.json()
                actual_model = data.get("model", model)
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    return {"success": True, "content": content, "source": f"TeamoRouter ({actual_model})"}
        except Exception as e:
            pass  # Fall through to DeepSeek

    # Priority 2: DeepSeek direct
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        try:
            api_key = open(os.path.expanduser("~/.cola/secrets/deepseek_api_key")).read().strip()
        except FileNotFoundError:
            pass
    if not api_key:
        return _fallback_summary(prompt)

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 3000,
                },
            )
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                return {"success": True, "content": content, "source": "DeepSeek"}
    except Exception as e:
        return {"success": False, "content": "", "note": f"LLM 调用失败: {str(e)[:100]}", "source": "error"}

    return _fallback_summary(prompt)


def _fallback_summary(prompt: str) -> dict:
    """无 LLM API 时的规则化总结"""
    return {
        "success": False,
        "content": "",
        "note": "🔍 AI 分析需要配置 TeamoRouter API Key（~/.cola/secrets/teamorouter_api_key）或 DeepSeek API Key。当前展示基于规则的数据总结。",
        "source": "fallback",
    }
