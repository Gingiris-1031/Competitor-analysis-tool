"""AI 商业洞察总结模块 — 基于采集数据生成竞品分析总结"""
import httpx
import json
import os


async def generate_ai_summary(product_name: str, url: str, website: dict, social: dict, traffic: dict, producthunt: dict) -> dict:
    """调用 LLM 基于所有数据生成商业洞察"""

    # Compile all data into a concise context
    context = _build_context(product_name, url, website, social, traffic, producthunt)

    prompt = f"""你是一位资深的出海产品增长顾问（拥有帮助产品从 0 到 60K GitHub stars 的实战经验）。

以下是对竞品 **{product_name}** ({url}) 的自动化调研数据。请基于这些数据，站在"想做类似产品的创业者"角度，输出一份精炼的竞品分析总结。

## 调研数据

{context}

## 请输出以下内容（中文，精炼、实战、可落地）：

### 1. 一句话定位总结
用一句话概括这个产品是什么、做对了什么。

### 2. 关键里程碑时间线
基于数据推断出 3-5 个关键时间节点（域名注册、首次 launch、爆发增长点、重要转型等），每个节点用一句话说明发生了什么。

### 3. 增长密码（做对了什么）
提炼 3-5 个这个产品增长的核心策略/决策，每条要具体、有数据支撑，不要泛泛而谈。

### 4. 给竞品/后来者的建议
如果你要做一个类似的产品，基于这份数据，给出 3-5 条最重要的建议。要具体到可执行的层面。

### 5. 风险与机会
指出 1-2 个这个产品的潜在弱点或市场机会。

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
    key_path = os.path.expanduser("~/.cola/secrets/deepseek_api_key")
    try:
        api_key = open(key_path).read().strip()
    except FileNotFoundError:
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
