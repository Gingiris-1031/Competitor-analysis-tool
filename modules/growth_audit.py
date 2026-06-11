"""Growth Audit 模块 — 用户输入产品 URL，调用 TinyFish 抓站 + LLM + Gingiris Skills 生成三份增长诊断报告

报告输出：
1. Executive Summary（~2000 字）
2. Diagnosis Report（~8000 字）
3. 30-Day Action Plan（~6000 字）
"""
import asyncio
import httpx
import json
import logging
import os
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# TinyFish Fetch API
TINYFISH_FETCH_URL = "https://api.fetch.tinyfish.ai"

# ─── Gingiris Skills System Prompt ──────────────────────────────────────────

GINGIRIS_SKILLS_CONTEXT = """
你是 Gingiris 增长诊断引擎 — 由 Iris Wei（前 AFFiNE COO，60K+ GitHub Stars，30x Product Hunt #1）创建的 AI 增长顾问系统。

你的诊断基于以下 Gingiris Growth Framework：

## 核心方法论

### 1. Growth Finder 三维诊断框架
- **产品类型维度**：SaaS / OSS / AI Product / Mobile / Dev Tool / Consumer Web
- **增长阶段维度**：Pre-launch → Launch → Cold Start → Growth → Scale
- **渠道缺口维度**：SEO/Content / Community / Paid / Partnerships / PLG

### 2. SEO & GEO 双引擎（2026）
- SEO 解决"被 Google 搜到"，GEO 解决"被 AI 引用"（ChatGPT/Perplexity/Claude）
- 从 BOFU 往上做：先做高意向关键词（定价、对比），再做教育型内容
- 结构化数据 = 可引用：Key Stats 表格、FAQ Schema、对比矩阵
- IndexNow 秒级推送，不等爬虫
- 竞品对比页是 SEO 金矿
- robots.txt 必须开放 AI 爬虫（GPTBot, ClaudeBot, PerplexityBot）

### 3. B2B SaaS Growth
- PLG vs SLG 决策框架：ARPU < $500/月 → PLG 为主；ARPU > $2000/月 → SLG 为主
- 冷启动三板斧：Product Hunt + 内容 SEO + 社区种草
- 定价实验优先级：Value-based > Usage-based > Seat-based > Feature-gated
- 激活指标：注册 → aha moment 时间 < 3 分钟为标杆

### 4. Product Hunt Launch
- L-6 周开始准备：Hunter 关系、Pre-launch 邮件列表、Asset 制作
- 发布日黄金 4 小时决定排名
- 评论策略：前 1 小时 5-10 条 maker response，30 分钟内回复所有评论
- 多波 Launch 策略：间隔 3-6 个月，每次新角度

### 5. Open Source Marketing
- GitHub Stars ≠ 用户，但 Stars 是社交证明的基础设施
- Show HN → Reddit → Twitter thread → Awesome lists → Dev.to 分发链
- 每月 300+ stars 持续增长需要内容引擎，不能只靠 viral spikes
- README 是最重要的 landing page

### 6. ASO & Mobile Growth
- ASO 是复利：关键词 + 截图 + 副标题优化，一次做好持续收益
- Creator matrix = UGC at $0.50 CPM（vs paid $5-10 CPM）
- TikTok/Reels/Shorts 为主的 organic reach

### 7. KOL Outreach
- 10K-100K 粉丝的 micro-KOL ROI 最高
- 首次合作提供 3 个月免费 + 联合内容（不是直接付费推广）
- LinkedIn DM 对 B2B KOL 回复率最高

### 8. Community & Reddit
- Reddit 内容 = 40.11% 的 ChatGPT/Claude 训练数据（最高权重英语 UGC 源）
- 20 天账号养成期（Karma 0→500），不能急
- 去营销味是核心技能：解答问题、分享经验、偶尔提及产品

## 诊断规则

1. 只基于抓取到的真实数据做分析。数据不足的维度标注"数据不足"，不编造。
2. 数字要精确：不写"大量用户"，写具体数字或"数据不足"。
3. 每条建议必须具体到"今天就能开始执行"的程度。
4. 先诊断问题，再开方。不要跳过诊断直接给建议。
5. 风格：军师 + 医生，直接、不废话、每条有数据支撑。

## 🚨 反幻觉硬约束（违反任何一条 = 报告无效）

A. **绝不发明事实**：以下内容只能引用"目标产品网站数据"小节里**literally** 出现的文本：
   - URL / 路径（不可写入未抓到的 URL）
   - robots.txt 指令（不可凭空说 "Disallow: /xxx"）
   - 任何"数字"（用户数 / 流量 / 字符数 / 排名 / DA / 月搜索量）
   - 竞品名称及其定价（如必须提到竞品，定价处写 "数据不足，建议查证"）
   - 客户案例 / 推荐语 / 团队规模
   - 外链 / 反向链接数据（除非数据里给了 backlinks 字段）
B. **不允许出现以下短语，除非数据里有原文佐证**：
   "B2B 采购中 X% 的用户"、"行业基准是"、"参考竞品 X 收 $N"、"100+ founders"。
C. **数据缺失时的标准答案**：写 "数据不足（未抓取）"或 "不在抓取范围"，**不要**用 "应该有"、"通常是"补全。
D. **每条结论必须可追溯**：在重要 finding 后用 `（依据：<数据小节名>）` 标注来源。

## 🚨 反推论谬误（重要：absence on homepage ≠ nonexistence）

E. **"首页没看到 X" ≠ "用户没做 X"**。以下信号本质上**不在抓取范围内**，缺失只能写"首页/sitemap 未展示"，**不能**写"未启动/未合作/无活动"：
   - KOL / 网红 / influencer 合作（合作记录通常在 CRM、Notion、Slack，不在首页）
   - Product Hunt 历史发布（PH 发布过未必在 homepage 留链）
   - Reddit / Discord / Slack 社区运营（运营痕迹通常不公开展示在首页）
   - 付费投放 / SEM / 社媒广告（广告创意不在 homepage）
   - Sales pipeline / outbound 活动（B2B 销售不在 public-facing）
   - 已建立的 partnership / integration 生态（除非首页有 logo 墙）
   - Newsletter 订阅数 / 社群人数 / 客户数
   - 内部 GA / GSC / Mixpanel 数据
F. **所有渠道类建议必须以"如尚未启动"为前提**。例如："**如尚未启动**，可以考虑识别 Micro-KOL..."，而不是"启动 KOL 外联"。
G. **诊断报告必须有一段"## 本次审计的盲区"**，明确列出**未抓取**的维度（KOL 合作 / 付费投放 / Sales / 内部分析 / 客户访谈 / churn / paid spend），让用户知道边界。

## 🚨 渠道-产品类型匹配矩阵（不要一刀切）

H. **渠道推荐必须先判产品类型，再选对应渠道**：

| 产品类型 | 推荐渠道 | 不推荐 / 谨慎推荐 |
|---|---|---|
| **Enterprise Infra / API / B2B SDK**（如 TinyFish, Browserless, Vanta） | HN/Show HN, 技术博客 (Dev.to, blog), Dev advocacy, GTM enablement, LinkedIn outbound, Sales-led, GitHub examples/cookbook | **不推**：Product Hunt（带个人开发者非企业买家）、UGC 矩阵、TikTok |
| **Developer Tool / OSS**（如 AFFiNE, Supabase） | GitHub Stars 体系, HN, Reddit (r/programming, 相关 subs), Awesome lists, Show HN, Dev.to | UGC 矩阵（不太适合）|
| **Consumer / Prosumer SaaS / PLG**（如 Notion, Linear early stage） | Product Hunt, UGC 矩阵, X/Twitter, 创作者运营, SEO/Content, 社区 | 纯 outbound（CAC 太高）|
| **Mobile App / Consumer App** | ASO, Creator matrix (TikTok/Reels/Shorts), 应用商店内 ads, UGC | 纯 SEO（mobile 流量来源不同）|
| **B2B Mid-market SaaS** | SEO/Content, LinkedIn outbound, Webinar, ABM, Sales-led, 客户案例 | UGC 矩阵 |
| **B2C / Marketplace** | Paid social, SEO, Referral, Influencer | 纯技术内容 |

I. **判断产品类型的优先信号**：首页 hero 价值主张 → 客户案例品牌 → 定价金额 → ICP 描述。
   - 月费 > $500 OR 客户是 enterprise/Fortune 500 → 偏 sales-led，不推 PH/UGC
   - 月费 < $100 OR 个人/团队 用户为主 → 偏 PLG，PH/UGC 有意义
   - 完全开源、强调 GitHub stars → OSS 路径
"""

# ─── TinyFish Fetch ─────────────────────────────────────────────────────────


async def fetch_site_with_tinyfish(url: str) -> dict:
    """使用 TinyFish Fetch API 抓取网站内容。
    
    抓取：首页、robots.txt、sitemap.xml（如有）、/pricing（如有）
    """
    api_key = os.environ.get("TINYFISH_API_KEY", "").strip()
    if not api_key:
        try:
            api_key = open(os.path.expanduser("~/.cola/secrets/tinyfish_api_key")).read().strip()
        except FileNotFoundError:
            return {"error": "TINYFISH_API_KEY not configured"}

    parsed = urlparse(url if url.startswith("http") else f"https://{url}")
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Batch fetch: homepage + robots.txt + pricing (if exists)
    urls_to_fetch = [
        url,  # homepage
        f"{base}/robots.txt",
        f"{base}/pricing",
        f"{base}/sitemap.xml",
    ]

    results = {}
    try:
        async with httpx.AsyncClient(timeout=160) as client:
            resp = await client.post(
                TINYFISH_FETCH_URL,
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                json={
                    "urls": urls_to_fetch,
                    "format": "markdown",
                    "links": True,
                    "ttl": 0,  # fresh fetch
                },
            )
            resp.raise_for_status()
            data = resp.json()

            for r in data.get("results", []):
                page_url = r.get("url", "")
                if page_url == url or page_url == url.rstrip("/") or "robots" not in page_url and "pricing" not in page_url and "sitemap" not in page_url:
                    results["homepage"] = {
                        "title": r.get("title"),
                        "description": r.get("description"),
                        "text": (r.get("text") or "")[:12000],
                        "links": (r.get("links") or [])[:50],
                    }
                elif "robots.txt" in page_url:
                    results["robots_txt"] = (r.get("text") or "")[:2000]
                elif "pricing" in page_url:
                    results["pricing_page"] = {
                        "title": r.get("title"),
                        "text": (r.get("text") or "")[:6000],
                    }
                elif "sitemap" in page_url:
                    results["sitemap"] = (r.get("text") or "")[:4000]

            for e in data.get("errors", []):
                err_url = e.get("url", "")
                if "pricing" in err_url:
                    results["pricing_page"] = None
                elif "sitemap" in err_url:
                    results["sitemap"] = None

    except Exception as exc:
        log.error("TinyFish fetch failed: %s", exc)
        results["error"] = str(exc)[:200]

    results["url"] = url
    results["domain"] = parsed.netloc
    return results


# ─── LLM Call (reuse pattern from ai_summary.py) ───────────────────────────


async def _call_llm_long(system_prompt: str, user_prompt: str, max_tokens: int = 8000) -> dict:
    """调用 LLM，支持 system + user 分离，更大 max_tokens。
    优先 TeamoRouter，fallback DeepSeek。
    """
    teamo_key = os.environ.get("TEAMOROUTER_API_KEY", "").strip()
    if not teamo_key:
        try:
            teamo_key = open(os.path.expanduser("~/.cola/secrets/teamorouter_api_key")).read().strip()
        except FileNotFoundError:
            pass

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Try TeamoRouter
    if teamo_key:
        model = os.environ.get("TEAMOROUTER_MODEL", "TeamoRouter-best")
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    resp = await client.post(
                        "https://router.teamolab.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {teamo_key}", "Content-Type": "application/json"},
                        json={
                            "model": model,
                            "messages": messages,
                            "temperature": 0.5,
                            "max_tokens": max_tokens,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        return {"success": True, "content": content, "source": f"TeamoRouter ({data.get('model', model)})"}
            except Exception as e:
                log.warning("TeamoRouter attempt %d failed: %s", attempt, e)
            if attempt < 1:
                await asyncio.sleep(2)

    # Fallback: DeepSeek
    ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not ds_key:
        try:
            ds_key = open(os.path.expanduser("~/.cola/secrets/deepseek_api_key")).read().strip()
        except FileNotFoundError:
            pass

    if ds_key:
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    resp = await client.post(
                        "https://api.deepseek.com/chat/completions",
                        headers={"Authorization": f"Bearer {ds_key}", "Content-Type": "application/json"},
                        json={
                            "model": "deepseek-chat",
                            "messages": messages,
                            "temperature": 0.5,
                            "max_tokens": max_tokens,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        return {"success": True, "content": content, "source": "DeepSeek"}
            except Exception as e:
                log.warning("DeepSeek attempt %d failed: %s", attempt, e)
            if attempt < 1:
                await asyncio.sleep(3)

    return {"success": False, "content": "", "source": "error", "note": "LLM 不可用"}


# ─── Report Generation ──────────────────────────────────────────────────────


def _parse_sitemap_structured(sitemap_text: str, domain: str) -> str:
    """把 sitemap XML 解析成按 path-prefix 分组的结构化摘要。

    不再截断到 N 字符 — 那样会丢掉 /research/、/alternatives/ 等已有的页面，
    LLM 因此推荐用户"创建"实际已经存在的内容。这里改成全 URL 列表 + 按目录
    聚合的摘要，让 LLM 看到完整地图。
    """
    if not sitemap_text:
        return "（无 sitemap）"
    import re as _re
    locs = _re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap_text)
    if not locs:
        # Not parseable as sitemap XML — fall back to raw (capped large)
        return "（非标准 sitemap.xml — 原始片段）\n```\n" + sitemap_text[:3500] + "\n```"

    # Group by first 2 path segments
    from collections import defaultdict
    buckets: dict[str, list[str]] = defaultdict(list)
    for u in locs:
        try:
            from urllib.parse import urlparse as _up
            p = _up(u)
            path = p.path.rstrip("/") or "/"
            segs = [s for s in path.split("/") if s]
            if not segs:
                key = "/ (homepage)"
            elif len(segs) == 1:
                key = "/" + segs[0] if "." in segs[0] else "/" + segs[0] + "/"
            else:
                key = "/" + segs[0] + "/"
            buckets[key].append(path)
        except Exception:
            buckets["(unparsed)"].append(u)

    lines = [f"Total URLs in sitemap: {len(locs)}", ""]
    for key in sorted(buckets, key=lambda k: (-len(buckets[k]), k)):
        items = buckets[key]
        lines.append(f"  {key}  ({len(items)})")
        # Show up to 12 per bucket; if more, summarize
        for item in items[:12]:
            lines.append(f"     - {item}")
        if len(items) > 12:
            lines.append(f"     - … +{len(items) - 12} more")
    return "\n".join(lines)


def _build_site_context(site_data: dict) -> str:
    """将抓取数据组织成 LLM 可读的上下文。

    Important: 不要在这里编故事。fields 缺失就明示缺失，让 prompt 的"反幻觉
    硬约束"接管，LLM 才不会自己往坑里跳。
    """
    parts = []
    url = site_data.get("url", "")
    domain = site_data.get("domain", "")

    parts.append(f"## 目标产品网站：{url}（域名：{domain}）\n")
    parts.append(f"抓取时间：刚刚（实时 fetch）\n")

    # Homepage
    hp = site_data.get("homepage", {})
    if hp:
        parts.append("### 首页信息")
        parts.append(f"- Title: {hp.get('title') or '（未提取到 title）'}")
        desc = hp.get("description")
        if desc is not None:
            parts.append(f"- Meta Description: {desc!r} (length: {len(desc)} chars)")
        else:
            parts.append("- Meta Description: （未提取到，可能未设置）")
        if hp.get("text"):
            parts.append(f"\n#### 首页正文（前 8000 字）：\n{hp['text'][:8000]}")
        else:
            parts.append("\n#### 首页正文：未抓取到")
        if hp.get("links"):
            internal_links = [l for l in hp["links"] if domain in l][:30]
            external_links = [l for l in hp["links"] if domain not in l][:15]
            if internal_links:
                parts.append(f"\n#### 站内链接（前 {len(internal_links)} 条）：")
                parts.append("\n".join(f"  - {l}" for l in internal_links))
            if external_links:
                parts.append(f"\n#### 外部链接（前 {len(external_links)} 条）：")
                parts.append("\n".join(f"  - {l}" for l in external_links))
    else:
        parts.append("### 首页信息\n首页抓取失败 — 报告中提到首页时，请写'首页未抓取'。")

    # Robots.txt — full text, no truncation
    robots = site_data.get("robots_txt")
    if robots:
        parts.append(f"\n### robots.txt（完整原文）")
        parts.append("```")
        parts.append(robots.strip())
        parts.append("```")
        parts.append("⚠️ 上面是 robots.txt 的 LITERAL 原文。任何关于 robots.txt 的判断必须基于这里实际出现的 directive，不允许引入未出现的 Disallow / Allow / User-Agent。")
    else:
        parts.append("\n### robots.txt\n未抓取到（/robots.txt 不存在或抓取失败）。报告中不能假装看到 robots.txt 的内容。")

    # Pricing
    pricing = site_data.get("pricing_page")
    if pricing and isinstance(pricing, dict):
        parts.append(f"\n### 定价页面（/pricing 抓取成功）")
        parts.append(f"- Title: {pricing.get('title') or '未提取'}")
        if pricing.get("text"):
            parts.append(f"\n{pricing['text'][:5000]}")
    elif pricing is None:
        parts.append("\n### 定价页面\n/pricing 返回 404 或抓取失败。注意：可能 /pricing.html 存在但 /pricing 无扩展名版本未配置 — 不要直接断言'未上线'，写'/pricing 不可访问，需确认是否仅 .html 版本可达'。")

    # Sitemap — STRUCTURED, NO TRUNCATION
    sitemap = site_data.get("sitemap")
    if sitemap and isinstance(sitemap, str):
        parts.append(f"\n### Sitemap.xml（结构化摘要）")
        parts.append(_parse_sitemap_structured(sitemap, domain))
        parts.append("\n⚠️ 上面列出了 sitemap 中的**所有** URL（按目录聚合）。不要推荐用户创建 sitemap 中已存在的页面。")
    elif sitemap is None:
        parts.append("\n### Sitemap.xml\n未抓取到。报告中不可声称 sitemap 包含 N 个 URL — 写 '未抓取，无法统计'。")

    return "\n".join(parts)


async def generate_diagnosis_report(site_data: dict, product_name: str) -> dict:
    """Phase 1：诊断报告（事实层）。

    这是 pipeline 的第一份报告，直接基于抓取数据写。所有后续报告
    （Action Plan, Executive Summary）都必须引用本报告，不能引入与本报告
    冲突的新事实。
    """
    context = _build_site_context(site_data)

    user_prompt = f"""基于以下抓取的产品网站数据，为 **{product_name}** 生成一份完整的增长诊断报告。

{context}

---

## 输出要求（Markdown 格式，6000-8000 字）

# {product_name} 增长诊断报告

> 诊断日期：今天
> 方法论：Gingiris Growth Skills Framework

## 1. 产品概览
- 产品定义与核心价值主张（依据：首页 Title/Description/正文）
- 核心功能（基于抓取到的首页内容）
- 目标用户（ICP）— 推断时标注"推断"
- 商业模式推断
- 定价分析 — 仅引用 /pricing 抓取到的内容。若 /pricing 抓取失败，写"未能确认公开定价，需用户提供"。

## 2. 增长诊断（三维度）
### 2.1 产品类型分类（SaaS / OSS / AI / Mobile / Dev Tool / Consumer Web）
### 2.2 增长阶段判定（Pre-launch / Launch / Cold Start / Growth / Scale）— 附判定依据
### 2.3 渠道现状概览（表格：渠道 | 首页/sitemap 是否展示 | 备注）
**强制规则（防 absence-on-homepage 谬误）**：每一格"现状"必须严格写"首页未展示" / "首页展示了 X" / "sitemap 包含" / "未抓取范围"，绝不写"未启动"、"无活动"、"用户未做"。
- KOL / 合作伙伴：合作关系一般不在首页公开 → 标记"未抓取范围"。
- Product Hunt：可能发布过但未在首页放 badge → 标记"首页未展示"。
- 社区（Reddit/Discord/Slack）：通常不公开运营痕迹 → 标记"未抓取范围"。
- SEO：基于 sitemap 可判断（有数据）。
- 付费投放、Sales pipeline：必须标"未抓取范围"，不可发表意见。

## 3. SEO/GEO 现状审计 — **以下规则必须严格遵守**
- **robots.txt 分析**：**只引用 robots.txt 章节里实际出现的 directive**。如果 robots.txt 章节标注"未抓取"，写"robots.txt 未抓到，无法分析"，不得编造 Disallow/Allow 内容。
- **Sitemap 完整度**：基于"Sitemap.xml 结构化摘要"里的目录聚合。
  - 不要推荐创建已经在 sitemap 里出现的页面（比如 sitemap 已有 /research/、/alternatives/、/compare/ 就别说"建议创建研究页"）。
  - 写明 sitemap 共有 N URL，覆盖了哪些目录。
- **内容资产盘点**：基于 sitemap + 站内链接
- **结构化数据**：仅依据首页正文中是否提及 JSON-LD / FAQ / Schema 等关键词做推断，并明确标"未对源码做 schema 扫描，推断仅供参考"
- **GEO 就绪度评估**：基于实际 robots.txt + 是否有 /research/ 类 citation-worthy 资产判断

## 4. 竞品定位分析
- 市场定位（基于首页价值主张）
- 可能的竞品（按产品类型列 3-5 个，不要给具体定价 — 写"具体定价请用户核实"）
- 差异化建议（基于首页传达的差异化点）

## 5. 增长策略推荐（P0/P1/P2 优先级）

**关键约束**：本节策略必须先根据 §1 推断的产品类型 + 增长阶段，对照系统提示中的"渠道-产品类型匹配矩阵 (H/I)"选渠道。**不要给企业级 API / Sales-led 产品推 PH / UGC 矩阵 / TikTok**。给 enterprise infra 推 PH 等于建议错误渠道。

每条策略必须：(1) 基于本报告已写明的 finding；(2) 附预期影响（不写 N% 提升这种伪数字，写"预期改善 SEO 入口"这种定性表达 OR 注明"基准数据需用户提供 GA / GSC 才能量化"）；(3) 渠道类策略必须以 "**如尚未启动**" 起头。

### P0 — 本周必做（最高 ROI）
### P1 — 2 周内完成
### P2 — 30 天内完成

## 6. 渠道策略详解
逐渠道分析。每个渠道必须先写"首页/sitemap 观察到的现状"，再写"建议"。**不发表"用户没做 X" 这类断言**（见反推论谬误 E）。如果该渠道与产品类型不匹配，直接写"**与该产品类型不匹配，跳过**"，不要硬凑建议。

## 7. 本次审计的盲区（必填）

明确列出本次抓取**未能覆盖的维度**，告诉用户报告的边界：
- 内部数据：GA / GSC / Mixpanel / Amplitude / 客户访谈 / churn 数据
- 渠道运营：KOL 合作记录 / Product Hunt 历史 / Reddit/Discord 活动 / Newsletter 数量 / 已签 partnership
- 销售/付费：sales pipeline / outbound 活动 / paid spend / CAC / LTV
- 反向链接 / 关键词排名 / 流量来源（本次未调用 SEO 工具 API）
- 登录后内部页面 / API endpoint
**每个盲区后用一行写"建议用户在咨询时提供："以提示用户在续约 Pro 时如何提供这些数据获取更准确的诊断。**

## 8. 风险与假设
列出本诊断的关键推断 + 它们的依据。

## 9. 匹配的 Gingiris Playbook
表格：框架名 | 适用场景（基于本报告 finding） | 安装命令

---

请记住反幻觉硬约束 A-D，每条 finding 后用 `（依据：xxx）` 标注来源。
"""

    return await _call_llm_long(GINGIRIS_SKILLS_CONTEXT, user_prompt, max_tokens=8000)


async def generate_action_plan(site_data: dict, product_name: str, diagnosis_md: str) -> dict:
    """Phase 2：30 天行动计划 — 必须基于 Diagnosis Report 的 findings 行动。

    传入 diagnosis_md 是关键架构改变：Action Plan 不能再独立看到 site_data
    就编新事实（比如凭空说 robots.txt 屏蔽了 /admin/）。它只能 act on
    Diagnosis 已经 verified 的问题。
    """
    context = _build_site_context(site_data)

    user_prompt = f"""基于以下两段输入，为 **{product_name}** 制定 30 天行动计划。

# 输入 1：原始抓取数据
{context}

---

# 输入 2：上一阶段已生成的诊断报告（事实基准）
{diagnosis_md}

---

## 输出要求（Markdown 格式，5000-7000 字）

# {product_name} — 30 天行动计划

> 本计划严格基于上面的"诊断报告"。每个任务必须能映射到诊断报告里写过的 finding。
> 预计投入：估算总工时

## Week 1: Day 1-7 — 基础设施修复

任务来源说明：本周任务来自诊断报告"## 5. 增长策略推荐 → P0"小节。**不引入诊断报告未涵盖的新问题**。

每个任务包含：
- **对应 finding**（引用诊断报告原话，1 句以内）
- **目的**
- **修复方案**（含代码 / 配置模板）
- **验证方法**
- **预期影响**（定性，不编 N% 数字）

## Week 2: Day 8-14 — 内容引擎启动
依据：诊断报告"## 3. SEO/GEO 现状审计"和"## 5. P1"。

## Week 3: Day 15-21 — 渠道拓展
依据：诊断报告"## 6. 渠道策略详解"。

## Week 4: Day 22-30 — 加速与验证
依据：诊断报告"## 5. P2"。

## 每周 KPI 追踪模板
表格：周 | 指标（来自诊断报告 KPI 段）| 目标 | 实际（用户填）

## 工具清单
对应 Week 任务的具体工具。

## 推荐安装的 Gingiris AI Skills
```bash
npx skills add Gingiris-1031/<skill-name>
```

---

🚨 一致性硬约束：
- 不允许写"修复 robots.txt"如果诊断报告说 robots.txt 没问题。
- 不允许推荐"创建定价页"如果诊断报告已经记录 /pricing 抓到了。
- 不允许引入诊断报告里没写的"当前问题"（比如不能凭空说"当前 Disallow /admin/ 是误配置"）。
- 不允许编竞品定价或行业基准。

🚨 渠道任务的额外约束（重要 — 防一刀切推荐）：
- 凡是"启动 KOL 外联 / 启动 Product Hunt / 启动 Reddit 运营 / 启动 UGC 矩阵"这类任务，**先看诊断报告 §1 推断的产品类型 + §2 增长阶段**：
  - Enterprise Infra / API / B2B SDK / Sales-led 产品（如 TinyFish, Browserless, Vanta） → **不要包含 PH Launch、UGC 矩阵、TikTok 任务**。改用：HN/Show HN、技术深度博客（Dev.to + 自有 blog）、Dev advocacy、GitHub examples/cookbook、LinkedIn outbound、客户案例/解决方案模板。
  - Consumer / PLG / Prosumer → 可以包含 PH + UGC + 社区。
  - OSS → 偏向 HN + Reddit + Awesome lists + GitHub。
  - Mobile → ASO + Creator matrix。
- 所有渠道类任务的"目的"段必须以 "**如尚未启动**" 起头（因为我们看不到用户的内部运营，不能假设"用户没做"）。
- 如果某 Week 的任务全部不适用于该产品类型，直接写："本周聚焦 [适合该产品类型的活动]，跳过通用的 PH/KOL 周。"，不要硬塞。
- KOL 类任务不要给"3 个月免费 Pro 计划"这种通用模板 — 改成 "**对应你产品的合理 incentive**（企业 SaaS 通常是免费 POC + 案例研究合作；个人开发者产品才适合免费订阅）"。
"""

    return await _call_llm_long(GINGIRIS_SKILLS_CONTEXT, user_prompt, max_tokens=8000)


async def generate_executive_summary(site_data: dict, product_name: str,
                                     diagnosis_md: str, action_plan_md: str) -> dict:
    """Phase 3：Executive Summary — 综合前两份报告，**不能引入新事实**。

    传入 diagnosis_md + action_plan_md，Executive 只能摘录 / 重组，不能新增。
    """
    user_prompt = f"""基于以下两份已生成的报告，提炼出 **{product_name}** 的执行摘要。

# 输入 1：诊断报告
{diagnosis_md}

# 输入 2：30 天行动计划
{action_plan_md}

---

## 输出要求（Markdown 格式，1500-2500 字）

# {product_name} 增长诊断 — 执行摘要

**诊断日期：** 今天
**产品：** {product_name}
**URL：** {site_data.get('url', '')}

## 🎯 核心发现（3 句话）
直接摘自诊断报告的"## 1. 产品概览"、"## 2. 增长诊断"、"## 3. SEO/GEO"三个章节，用 3 句话总结。**不引入新发现**。

## 🚨 三个最严重的问题
直接摘自诊断报告"## 5. P0 — 本周必做"。最多 3 条，每条包含：
- 问题描述（一句）
- 影响程度（🔴 极高 / 🟡 中 / 🟢 低）
- 修复时间估算（取自 Action Plan Week 1）
- 预期影响（定性，照搬诊断报告原话）

## ✅ 快速赢面清单（按优先级）
- 本周做（2-3 小时）— 摘自 Action Plan Week 1
- 第 1-2 周做（8 小时）— 摘自 Action Plan Week 2
- 第 3-4 周做（12 小时）— 摘自 Action Plan Week 3-4

## 📊 6 个月财务预测（如基础数据不足则跳过本节）
**只在诊断报告里有量化基线时输出**。否则写"基线数据缺失，建议用户提供 GA / GSC 后再做预测"。

## 🎯 关键 KPI 追踪
表格：KPI（取自诊断报告） | 当前（取自诊断报告，无则写"待用户提供"） | 3 个月目标 | 6 个月目标

## 🛠️ 推荐工具堆栈
摘自 Action Plan"工具清单"

## 📚 匹配的 Gingiris 框架
摘自诊断报告"## 8. 匹配的 Gingiris Playbook"

## ❓ 下一步行动
- 立即（今天）：取 Action Plan Week 1 任务 1
- 本周：取 Action Plan Week 1 剩余任务
- 下周：取 Action Plan Week 2 任务

---

🚨 一致性硬约束：
- 本摘要不能出现诊断报告 / 行动计划里没出现的新 finding。
- 本摘要的"三个最严重问题"必须能在 Action Plan 里找到对应任务。
- 不允许编新数字 / 新竞品 / 新案例。
"""

    return await _call_llm_long(GINGIRIS_SKILLS_CONTEXT, user_prompt, max_tokens=4000)


# ─── Main Orchestrator ──────────────────────────────────────────────────────


async def run_growth_audit(url: str, product_name: str = None, job_id: str = None, jobs_dict: dict = None) -> dict:
    """完整的 Growth Audit pipeline：抓站 → 生成三份报告。
    
    如果提供 job_id 和 jobs_dict，会实时更新 job 状态。
    """
    # Parse product name from URL if not provided
    if not product_name:
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        import re
        brand = re.sub(r'^www\.', '', parsed.netloc.lower())
        brand = re.sub(r'\.[a-z]{2,6}$', '', brand)
        product_name = brand.replace("-", " ").replace("_", " ").capitalize()

    def _update(stage: str, status: str):
        if jobs_dict and job_id and job_id in jobs_dict:
            jobs_dict[job_id]["progress"][stage] = status

    # Step 1: Fetch site data
    _update("fetch", "running")
    site_data = await fetch_site_with_tinyfish(url)
    if site_data.get("error"):
        _update("fetch", "failed")
        return {"error": f"网站抓取失败: {site_data['error']}"}
    _update("fetch", "done")

    # Step 2: Sequential pipeline — Diagnosis → Action Plan → Executive Summary.
    # Architectural fix: the old parallel-gather design let each report
    # independently hallucinate facts. Now each downstream report only sees the
    # already-verified output of the previous stage, plus the cross-report
    # consistency guards baked into each prompt. This collapses the
    # "Diagnosis says robots.txt is fine / Action Plan invents Disallow rules"
    # contradiction that bit our first Iris-on-Iris self-audit.
    reports = {"executive_summary": None, "diagnosis_report": None, "action_plan": None}
    sources = {"exec": "skipped", "diag": "skipped", "plan": "skipped"}

    # Phase 1: Diagnosis (facts layer)
    _update("diagnosis", "running")
    diag_result = await generate_diagnosis_report(site_data, product_name)
    if isinstance(diag_result, dict) and diag_result.get("success"):
        reports["diagnosis_report"] = diag_result["content"]
        sources["diag"] = diag_result.get("source", "?")
        _update("diagnosis", "done")
    else:
        _update("diagnosis", "failed")
        log.error("Diagnosis generation failed: %s", diag_result)
        # Without a Diagnosis we can't run the downstream stages — fail fast,
        # better than producing two ungrounded reports.
        return {
            "product_name": product_name,
            "url": url,
            "reports": reports,
            "source": sources,
            "error": "Diagnosis 阶段失败，已中止 pipeline（防止下游报告 hallucinate）",
        }

    # Phase 2: Action Plan (grounded on Diagnosis)
    _update("action_plan", "running")
    plan_result = await generate_action_plan(
        site_data, product_name, reports["diagnosis_report"]
    )
    if isinstance(plan_result, dict) and plan_result.get("success"):
        reports["action_plan"] = plan_result["content"]
        sources["plan"] = plan_result.get("source", "?")
        _update("action_plan", "done")
    else:
        _update("action_plan", "failed")
        log.error("Action Plan generation failed: %s", plan_result)

    # Phase 3: Executive Summary (synthesizes Diagnosis + Action Plan only)
    _update("executive_summary", "running")
    if reports.get("action_plan"):
        exec_result = await generate_executive_summary(
            site_data, product_name,
            reports["diagnosis_report"], reports["action_plan"],
        )
        if isinstance(exec_result, dict) and exec_result.get("success"):
            reports["executive_summary"] = exec_result["content"]
            sources["exec"] = exec_result.get("source", "?")
            _update("executive_summary", "done")
        else:
            _update("executive_summary", "failed")
            log.error("Executive Summary generation failed: %s", exec_result)
    else:
        # Without Action Plan, Exec Summary would re-introduce ungrounded content
        _update("executive_summary", "failed")
        log.warning("Skipping Exec Summary — no Action Plan to synthesize from.")

    return {
        "product_name": product_name,
        "url": url,
        "site_data_summary": {
            "homepage_title": site_data.get("homepage", {}).get("title"),
            "has_robots": bool(site_data.get("robots_txt")),
            "has_pricing": bool(site_data.get("pricing_page")),
            "has_sitemap": bool(site_data.get("sitemap")),
        },
        "reports": reports,
        "source": sources,
    }
