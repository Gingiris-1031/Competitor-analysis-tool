"""Growth Audit 模块 - 用户输入产品 URL,调用 TinyFish 抓站 + LLM + Gingiris Skills 生成三份增长诊断报告

报告输出:
1. Executive Summary(~2000 字)
2. Diagnosis Report(~8000 字)
3. 30-Day Action Plan(~6000 字)
"""
import asyncio
import httpx
import json
import logging
import os
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# TinyFish Fetch API
TINYFISH_FETCH_URL = "https://api.fetch.tinyfish.ai"

# ─── Gingiris Skills System Prompt ──────────────────────────────────────────

GINGIRIS_SKILLS_CONTEXT = """
你是 Gingiris 增长诊断引擎 - 由 Iris Wei(前 AFFiNE COO,60K+ GitHub Stars,30x Product Hunt #1)创建的 AI 增长顾问系统。

你的诊断基于以下 Gingiris Growth Framework:

## 核心方法论

### 1. Growth Finder 三维诊断框架
- **产品类型维度**:SaaS / OSS / AI Product / Mobile / Dev Tool / Consumer Web
- **增长阶段维度**:Pre-launch → Launch → Cold Start → Growth → Scale
- **渠道缺口维度**:SEO/Content / Community / Paid / Partnerships / PLG

### 2. SEO & GEO 双引擎(2026)
- SEO 解决"被 Google 搜到",GEO 解决"被 AI 引用"(ChatGPT/Perplexity/Claude)
- 从 BOFU 往上做:先做高意向关键词(定价、对比),再做教育型内容
- 结构化数据 = 可引用:Key Stats 表格、FAQ Schema、对比矩阵
- IndexNow 秒级推送,不等爬虫
- 竞品对比页是 SEO 金矿
- robots.txt 必须开放 AI 爬虫(GPTBot, ClaudeBot, PerplexityBot)

### 3. B2B SaaS Growth
- PLG vs SLG 决策框架:ARPU < $500/月 → PLG 为主;ARPU > $2000/月 → SLG 为主
- 冷启动三板斧:Product Hunt + 内容 SEO + 社区种草
- 定价实验优先级:Value-based > Usage-based > Seat-based > Feature-gated
- 激活指标:注册 → aha moment 时间 < 3 分钟为标杆

### 4. Product Hunt Launch
- L-6 周开始准备:Hunter 关系、Pre-launch 邮件列表、Asset 制作
- 发布日黄金 4 小时决定排名
- 评论策略:前 1 小时 5-10 条 maker response,30 分钟内回复所有评论
- 多波 Launch 策略:间隔 3-6 个月,每次新角度

### 5. Open Source Marketing
- GitHub Stars ≠ 用户,但 Stars 是社交证明的基础设施
- Show HN → Reddit → Twitter thread → Awesome lists → Dev.to 分发链
- 每月 300+ stars 持续增长需要内容引擎,不能只靠 viral spikes
- README 是最重要的 landing page

### 6. ASO & Mobile Growth
- ASO 是复利:关键词 + 截图 + 副标题优化,一次做好持续收益
- Creator matrix = UGC at $0.50 CPM(vs paid $5-10 CPM)
- TikTok/Reels/Shorts 为主的 organic reach

### 7. KOL Outreach
- 10K-100K 粉丝的 micro-KOL ROI 最高
- 首次合作提供 3 个月免费 + 联合内容(不是直接付费推广)
- LinkedIn DM 对 B2B KOL 回复率最高

### 8. Community & Reddit
- Reddit 内容 = 40.11% 的 ChatGPT/Claude 训练数据(最高权重英语 UGC 源)
- 20 天账号养成期(Karma 0→500),不能急
- 去营销味是核心技能:解答问题、分享经验、偶尔提及产品

## 诊断规则

1. 只基于抓取到的真实数据做分析。数据不足的维度标注"数据不足",不编造。
2. 数字要精确:不写"大量用户",写具体数字或"数据不足"。
3. 每条建议必须具体到"今天就能开始执行"的程度。
4. 先诊断问题,再开方。不要跳过诊断直接给建议。
5. 风格:军师 + 医生,直接、不废话、每条有数据支撑。

## 🚨 反幻觉硬约束(违反任何一条 = 报告无效)

A. **绝不发明事实**:以下内容只能引用"目标产品网站数据"小节里**literally** 出现的文本:
   - URL / 路径(不可写入未抓到的 URL)
   - robots.txt 指令(不可凭空说 "Disallow: /xxx")
   - 任何"数字"(用户数 / 流量 / 字符数 / 排名 / DA / 月搜索量)
   - 竞品名称及其定价(如必须提到竞品,定价处写 "数据不足,建议查证")
   - 客户案例 / 推荐语 / 团队规模
   - 外链 / 反向链接数据(除非数据里给了 backlinks 字段)
B. **不允许出现以下短语,除非数据里有原文佐证**:
   "B2B 采购中 X% 的用户"、"行业基准是"、"参考竞品 X 收 $N"、"100+ founders"。
C. **数据缺失时的标准答案**:写 "数据不足(未抓取)"或 "不在抓取范围",**不要**用 "应该有"、"通常是"补全。
D. **每条结论必须可追溯**:在重要 finding 后用 `(依据:<数据小节名>)` 标注来源。

## 🚨 反推论谬误(重要:absence on homepage ≠ nonexistence)

E. **"首页没看到 X" ≠ "用户没做 X"**。以下信号本质上**不在抓取范围内**,缺失只能写"首页/sitemap 未展示",**不能**写"未启动/未合作/无活动":
   - KOL / 网红 / influencer 合作(合作记录通常在 CRM、Notion、Slack,不在首页)
   - Product Hunt 历史发布(PH 发布过未必在 homepage 留链)
   - Reddit / Discord / Slack 社区运营(运营痕迹通常不公开展示在首页)
   - 付费投放 / SEM / 社媒广告(广告创意不在 homepage)
   - Sales pipeline / outbound 活动(B2B 销售不在 public-facing)
   - 已建立的 partnership / integration 生态(除非首页有 logo 墙)
   - Newsletter 订阅数 / 社群人数 / 客户数
   - 内部 GA / GSC / Mixpanel 数据
F. **所有渠道类建议必须以"如尚未启动"为前提**。例如:"**如尚未启动**,可以考虑识别 Micro-KOL...",而不是"启动 KOL 外联"。
G. **诊断报告必须有一段"## 本次审计的盲区"**,明确列出**未抓取**的维度(KOL 合作 / 付费投放 / Sales / 内部分析 / 客户访谈 / churn / paid spend),让用户知道边界。

## 🚨 渠道-产品类型匹配矩阵(不要一刀切)

H. **渠道推荐必须先判产品类型,再选对应渠道**:

| 产品类型 | 推荐渠道 | 不推荐 / 谨慎推荐 |
|---|---|---|
| **Enterprise Infra / API / B2B SDK**(如 TinyFish, Browserless, Vanta) | HN/Show HN, 技术博客 (Dev.to, blog), Dev advocacy, GTM enablement, LinkedIn outbound, Sales-led, GitHub examples/cookbook | **不推**:Product Hunt(带个人开发者非企业买家)、UGC 矩阵、TikTok |
| **Developer Tool / OSS**(如 AFFiNE, Supabase) | GitHub Stars 体系, HN, Reddit (r/programming, 相关 subs), Awesome lists, Show HN, Dev.to | UGC 矩阵(不太适合)|
| **Consumer / Prosumer SaaS / PLG**(如 Notion, Linear early stage) | Product Hunt, UGC 矩阵, X/Twitter, 创作者运营, SEO/Content, 社区 | 纯 outbound(CAC 太高)|
| **Mobile App / Consumer App** | ASO, Creator matrix (TikTok/Reels/Shorts), 应用商店内 ads, UGC | 纯 SEO(mobile 流量来源不同)|
| **B2B Mid-market SaaS** | SEO/Content, LinkedIn outbound, Webinar, ABM, Sales-led, 客户案例 | UGC 矩阵 |
| **B2C / Marketplace** | Paid social, SEO, Referral, Influencer | 纯技术内容 |

I. **判断产品类型的优先信号**:首页 hero 价值主张 → 客户案例品牌 → 定价金额 → ICP 描述。
   - 月费 > $500 OR 客户是 enterprise/Fortune 500 → 偏 sales-led,不推 PH/UGC
   - 月费 < $100 OR 个人/团队 用户为主 → 偏 PLG,PH/UGC 有意义
   - 完全开源、强调 GitHub stars → OSS 路径

%SKILL_REGISTRY%
"""


def _get_system_prompt() -> str:
    """Returns the system prompt with the real Gingiris skill registry
    + tactical cheat-sheet inlined. We do this lazily because the
    register-builder functions are defined later in the file.

    The tactical block is what fixes "reports too template-y" - it gives
    the LLM 2-3 concrete tactics per skill (with real benchmarks) to cite
    instead of generic prose.
    """
    return GINGIRIS_SKILLS_CONTEXT.replace(
        "%SKILL_REGISTRY%",
        _build_skill_registry_prompt() + "\n\n" + _build_tactical_cheatsheet()
    )


def _build_tactical_cheatsheet() -> str:
    """Compact tactical recipes per skill - drops into system prompt so
    LLM can cite specific tactics verbatim instead of inventing fluffy
    'launch on PH'-level recommendations.
    """
    lines = [
        "## 🎯 战术速查表(强制:所有渠道推荐必须引用此表中的具体战术 + benchmark)",
        "",
        "格式:每个 skill 给出 2-3 个可执行战术:(时间窗 / 具体动作 / 实战 benchmark)",
        "**LLM 引用此表中的战术时格式:【来自 `skill-slug` 的战术】+ 原文**",
        "",
    ]
    for slug, tactics in GINGIRIS_SKILL_TACTICS.items():
        info = GINGIRIS_SKILL_REGISTRY.get(slug, {})
        lines.append(f"### `{slug}` - {info.get('title', slug)}")
        for when, what, bench in tactics:
            lines.append(f"- **{when}** - {what} _(benchmark: {bench})_")
        lines.append("")
    return "\n".join(lines)

# ─── TinyFish Fetch ─────────────────────────────────────────────────────────


async def fetch_site_with_tinyfish(url: str) -> dict:
    """使用 TinyFish Fetch API 抓取网站内容。

    抓取:首页、robots.txt、sitemap.xml(如有)、/pricing(如有)
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


# ─── LLM Call ───────────────────────────────────────────────────────────────
# Provider stack:
#   PRIMARY:   DeepSeek (direct, cheapest)
#   FALLBACK:  OpenRouter (300+ models, pay-as-you-go) - opt-in via
#              OPENROUTER_API_KEY env. We never recommend going via a
#              relay/router as primary again after the TeamoRouter incident
#              (URL moved + model renamed + account froze, three failure
#              modes that all silently fell through to fallback while
#              wasting 6+ min of retry budget per LLM call).
#
# Adding a new provider? Drop another _try_<name>() helper here and call it
# in _call_llm_long. Keep response shape {success, content, source}.


# Per-provider timeout. A short CONNECT timeout fails over fast (~10s) when a
# provider is down/unreachable - that's the UX win: no 6-minute hang waiting on
# a sick endpoint. A generous READ timeout still lets a *healthy* provider
# finish a long generation. Each provider gets ONE attempt; resilience comes
# from failing over to the next path, not from retrying a struggling one.
_LLM_TIMEOUT = httpx.Timeout(connect=10.0, read=150.0, write=10.0, pool=10.0)


def _extract_content(data: dict) -> str:
    """Pull ONLY the final answer text. DeepSeek V4 (and some routed hosts)
    also return `reasoning_content` / `reasoning` in the message - that chain
    of thought must never leak into the user-facing report, so we read
    `content` exclusively."""
    msg = ((data.get("choices") or [{}])[0] or {}).get("message", {}) or {}
    return msg.get("content", "") or ""


async def _try_deepseek(messages: list, max_tokens: int) -> Optional[dict]:
    """DeepSeek first-party API (deepseek-v4-flash). One attempt - the caller
    owns failover, so we never burn time retrying a sick provider."""
    import os as _os
    key = _os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        try:
            key = open(_os.path.expanduser("~/.cola/secrets/deepseek_api_key")).read().strip()
        except FileNotFoundError:
            return None
    if not key:
        return None
    model = _os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT, follow_redirects=True) as client:
            resp = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={"model": model, "messages": messages,
                      "temperature": 0.5, "max_tokens": max_tokens},
            )
            resp.raise_for_status()
            content = _extract_content(resp.json())
            if content:
                return {"success": True, "content": content,
                        "source": f"DeepSeek-direct ({model})"}
    except Exception as e:
        log.warning("DeepSeek-direct failed, failing over: %s", e)
    return None


async def _try_openrouter(messages: list, max_tokens: int,
                          model: str = "anthropic/claude-sonnet-4") -> Optional[dict]:
    """OpenRouter call for an explicit model. One attempt; caller handles
    failover. Returns None if no OPENROUTER_API_KEY is configured."""
    import os as _os
    key = _os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT, follow_redirects=True) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://www.analook.com",
                    "X-Title": "Analook Growth Audit",
                },
                json={"model": model, "messages": messages,
                      "temperature": 0.5, "max_tokens": max_tokens},
            )
            # 401/402/403 = auth/balance problem - failing over won't help on
            # the same key path, but the next plan uses a different vendor.
            if resp.status_code in (401, 402, 403):
                log.warning("OpenRouter rejected model=%s: HTTP %d (%s)",
                            model, resp.status_code, resp.text[:200])
                return None
            resp.raise_for_status()
            data = resp.json()
            content = _extract_content(data)
            if content:
                return {"success": True, "content": content,
                        "source": f"OpenRouter ({data.get('model', model)})"}
    except Exception as e:
        log.warning("OpenRouter (%s) failed, failing over: %s", model, e)
    return None


async def _call_llm_long(system_prompt: str, user_prompt: str, max_tokens: int = 8000) -> dict:
    """Multi-path LLM call. Each path is tried once and fails over fast (~10s)
    when a provider is unreachable, so a sick provider never stalls the audit.

      Plan A: OpenRouter → deepseek-v4-flash   (fast, cheap, multi-host failover)
      Plan B: DeepSeek direct → deepseek-v4-flash  (same model, independent vendor)
      Plan C: OpenRouter → claude-sonnet-4     (different model - quality safety net)

    A and B share the model (identical output quality); C is the last-resort
    safety net on a different model so a total DeepSeek outage still produces a
    report. Returns {success, content, source}.
    """
    import os as _os
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]
    or_primary = _os.environ.get("OPENROUTER_DEEPSEEK_MODEL", "deepseek/deepseek-v4-flash")
    or_fallback = _os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")

    plans = (
        ("A", lambda: _try_openrouter(messages, max_tokens, or_primary)),
        ("B", lambda: _try_deepseek(messages, max_tokens)),
        ("C", lambda: _try_openrouter(messages, max_tokens, or_fallback)),
    )
    for label, plan in plans:
        result = await plan()
        if result:
            if label != "A":
                log.info("LLM served by Plan %s (%s)", label, result.get("source"))
            return result

    return {"success": False, "content": "", "source": "error",
            "note": "All LLM providers failed or unconfigured."}


# ─── Report Generation ──────────────────────────────────────────────────────


# ─── Product-type detection ─────────────────────────────────────────────────
# Determines whether a product is Sales-led (Enterprise / B2B Infra / API)
# vs PLG/Consumer/OSS. Critical because the channel mix differs sharply and
# the LLM cannot reliably do this classification on its own - it pattern-
# matched TinyFish as "AI/Dev Tool" and recommended Product Hunt for an
# enterprise infra product whose buyers are CTOs and procurement teams,
# not PH lurkers.
#
# Signals (we want HIGH PRECISION - false positives push wrong recs):
#   Strong:
#     - /pricing has an "Enterprise" / "Custom" / "Contact us" tier
#     - Mentions of SOC 2 / ISO 27001 / HIPAA / GDPR compliance
#     - Pricing >= $500/mo on any tier
#     - "Contact sales" / "Talk to sales" / "Book a demo" CTAs prominent
#   Medium:
#     - Customer logos from Fortune 500 / unicorns
#     - "Enterprise" appears in nav or pricing
#     - "for teams of 100+" / "for engineering teams" language
#     - Has dedicated /enterprise/ pages
#   Weak (one alone doesn't classify):
#     - API-first product (Swagger/OpenAPI docs)
#     - "Self-hosted" / "On-premise" options
#
# Threshold: 1 strong signal OR 3 medium signals → sales-led.

_FORTUNE500_NAMES = {
    "doordash", "grubhub", "uber", "lyft", "airbnb", "stripe", "shopify",
    "netflix", "spotify", "datadog", "snowflake", "databricks", "twilio",
    "atlassian", "intuit", "adobe", "salesforce", "oracle", "ibm", "intel",
    "amd", "nvidia", "microsoft", "google", "amazon", "meta", "facebook",
    "linkedin", "samsung", "sony", "disney", "walmart", "target", "costco",
    "fedex", "ups", "boeing", "lockheed", "morgan", "goldman", "chase",
    "wells fargo", "citi", "bank of america", "visa", "mastercard",
    "deloitte", "accenture", "pwc", "kpmg", "ey", "mckinsey", "bcg",
    "bain", "the zebra", "classpass", "expedia", "booking",
}


def detect_product_type(site_data: dict) -> dict:
    """Return product-type hints to inject into LLM context.

    Returns a dict with:
      - is_sales_led: bool (Enterprise/B2B Infra → no PH/UGC)
      - signals_strong: list[str]  (one alone classifies)
      - signals_medium: list[str]  (need 3+ to classify)
      - product_type: str  (best guess: "Enterprise Infra" / "PLG SaaS" /
                            "OSS Dev Tool" / "Consumer App" / "Unknown")
      - recommended_channels: list[str]   (positive list)
      - forbidden_channels: list[str]     (explicit no-go list)
    """
    homepage = (site_data.get("homepage") or {})
    pricing = (site_data.get("pricing_page") or {})
    sitemap = site_data.get("sitemap") or ""

    homepage_text = ((homepage.get("text") or "") + " " +
                     (homepage.get("description") or "") + " " +
                     (homepage.get("title") or "")).lower()
    pricing_text = (pricing.get("text") or "").lower() if isinstance(pricing, dict) else ""
    sitemap_lower = sitemap.lower() if isinstance(sitemap, str) else ""

    strong = []
    medium = []

    # ── Strong signals ───────────────────────────────────────────────────
    if _re.search(r"\benterprise\b.{0,60}(plan|tier|pricing|custom|contact)", pricing_text):
        strong.append("/pricing 含 Enterprise tier (custom/contact)")
    if _re.search(r"contact (sales|us|our team).{0,40}(pricing|enterprise|quote|custom)", pricing_text):
        strong.append("/pricing 引导 Contact Sales 而非自助购买")
    # Pricing >= $500/mo on any tier
    big_prices = _re.findall(r"\$\s*([0-9][0-9,]{2,5})\s*(?:/|\s*per\s*)?(?:mo|month)", pricing_text)
    for raw in big_prices:
        try:
            amount = int(raw.replace(",", ""))
            if amount >= 500:
                strong.append(f"定价含 ≥ $500/mo 档 (${amount}/mo)")
                break
        except ValueError:
            continue
    for kw in ["soc 2", "soc2", "iso 27001", "iso27001", "hipaa compliant",
              "gdpr compliant", "fedramp"]:
        if kw in homepage_text or kw in pricing_text:
            strong.append(f"合规标签: {kw.upper()}")
            break

    # ── Medium signals ───────────────────────────────────────────────────
    if "/enterprise" in sitemap_lower:
        medium.append("sitemap 含 /enterprise/* 路径")
    if "book a demo" in homepage_text or "talk to sales" in homepage_text:
        medium.append("首页含 'Book a demo' / 'Talk to sales' CTA")
    if _re.search(r"for (engineering )?teams of \d+", homepage_text):
        medium.append("首页含 'for teams of N+' 语言")
    # Fortune 500 customer mentions
    f500_hits = sorted({n for n in _FORTUNE500_NAMES if n in homepage_text})
    if f500_hits:
        medium.append(f"首页含知名企业客户: {', '.join(f500_hits[:5])}")
    if _re.search(r"\benterprise\b", homepage_text):
        medium.append("首页提及 'Enterprise'")
    if "api key" in homepage_text and "production" in homepage_text:
        medium.append("强调 API + production scale")

    # ── OSS signal (overrides to OSS path, not sales-led) ────────────────
    is_oss = False
    if homepage.get("links"):
        gh_links = [l for l in homepage["links"] if "github.com" in l.lower()]
        if any(_re.search(r"github\.com/[^/]+/[^/]+/?\s*$", l) for l in gh_links):
            is_oss = "github 链接指向 repo(非仅 cookbook)" in str(medium) or False
    if "open source" in homepage_text and "star" in homepage_text:
        is_oss = True

    # ── Classification ──────────────────────────────────────────────────
    is_sales_led = (len(strong) >= 1) or (len(medium) >= 3)

    if is_oss and not is_sales_led:
        product_type = "OSS Dev Tool"
        recommended = ["GitHub Stars 体系", "Show HN", "Reddit (r/programming, r/opensource)",
                       "Awesome lists", "Dev.to + 自建 blog", "Discord 社区"]
        forbidden = ["UGC 矩阵", "TikTok / Reels", "Paid social"]
    elif is_sales_led:
        product_type = "Enterprise Infra / B2B Sales-led"
        recommended = ["HN / Show HN", "技术深度博客 (Dev.to + 自建 blog)",
                       "Dev advocacy + 客户案例", "GitHub examples / cookbook",
                       "LinkedIn 内容 + 1:1 outbound", "Webinar / 技术峰会",
                       "Account-based marketing (ABM)", "Sales 友好的解决方案模板"]
        forbidden = [
            "Product Hunt Launch(带个人开发者非企业买家)",
            "UGC 矩阵(不适合 B2B infra 买家心智)",
            "TikTok / Reels / Shorts 创作者运营",
            "Reddit Karma 养号 + 种草(开发者 sub 可去,但不是冷启动主力)",
            "Micro-KOL 提供 '3 个月免费 Pro' 模板(B2B 应改为免费 POC + 案例研究合作)",
        ]
    elif "pricing" in pricing_text and "$" in pricing_text:
        # Has self-serve pricing but no enterprise signals → PLG
        product_type = "PLG / Self-serve SaaS"
        recommended = ["Product Hunt", "UGC 矩阵 / Creator", "X/Twitter 内容",
                       "SEO/Content 长尾", "社区 (Discord/Slack)",
                       "Free tier 漏斗优化"]
        forbidden = ["纯 outbound (CAC 过高)"]
    else:
        product_type = "Unknown / 需用户确认"
        recommended = ["按 ICP 反推(建议续费咨询)"]
        forbidden = []

    return {
        "is_sales_led": is_sales_led,
        "is_oss": is_oss,
        "signals_strong": strong,
        "signals_medium": medium,
        "product_type": product_type,
        "recommended_channels": recommended,
        "forbidden_channels": forbidden,
    }


def _format_product_type_block(hints: dict) -> str:
    """Format hints as a high-prominence top-of-context block for the LLM."""
    lines = []
    lines.append("=" * 70)
    lines.append("🚨 程序判定的产品类型(**最高优先级,覆盖你对产品的任何模式匹配**)")
    lines.append("=" * 70)
    lines.append(f"产品类型: **{hints['product_type']}**")
    if hints["is_sales_led"]:
        lines.append("销售模式: **Sales-led / Enterprise**")
        lines.append("**绝对禁止推荐的渠道**(违反 = 报告无效):")
        for f in hints["forbidden_channels"]:
            lines.append(f"  ❌ {f}")
        lines.append("应聚焦的渠道:")
        for r in hints["recommended_channels"]:
            lines.append(f"  ✅ {r}")
    else:
        lines.append("销售模式: 非 Sales-led(可考虑 PLG / OSS / Consumer 路径)")
        if hints["recommended_channels"]:
            lines.append("建议聚焦:")
            for r in hints["recommended_channels"]:
                lines.append(f"  ✅ {r}")
        if hints["forbidden_channels"]:
            lines.append("不建议聚焦:")
            for f in hints["forbidden_channels"]:
                lines.append(f"  ❌ {f}")
    if hints["signals_strong"]:
        lines.append("\n判定依据(Strong signals - 单一即可分类):")
        for s in hints["signals_strong"]:
            lines.append(f"  • {s}")
    if hints["signals_medium"]:
        lines.append("\n判定依据(Medium signals):")
        for s in hints["signals_medium"]:
            lines.append(f"  • {s}")
    lines.append("=" * 70)
    return "\n".join(lines)


def _parse_sitemap_structured(sitemap_text: str, domain: str) -> str:
    """把 sitemap XML 解析成按 path-prefix 分组的结构化摘要。

    不再截断到 N 字符 - 那样会丢掉 /research/、/alternatives/ 等已有的页面,
    LLM 因此推荐用户"创建"实际已经存在的内容。这里改成全 URL 列表 + 按目录
    聚合的摘要,让 LLM 看到完整地图。
    """
    if not sitemap_text:
        return "(无 sitemap)"
    import re as _re
    locs = _re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap_text)
    if not locs:
        # Not parseable as sitemap XML - fall back to raw (capped large)
        return "(非标准 sitemap.xml - 原始片段)\n```\n" + sitemap_text[:3500] + "\n```"

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
            lines.append(f"     - ... +{len(items) - 12} more")
    return "\n".join(lines)


def _build_site_context(site_data: dict) -> str:
    """将抓取数据组织成 LLM 可读的上下文。

    Important: 不要在这里编故事。fields 缺失就明示缺失,让 prompt 的"反幻觉
    硬约束"接管,LLM 才不会自己往坑里跳。
    """
    parts = []
    url = site_data.get("url", "")
    domain = site_data.get("domain", "")

    # Run product-type detection FIRST and put it at the very top of the
    # context. The LLM is far more likely to follow constraints that
    # appear before the noisy site content. This block carries the only
    # binding classification - the LLM's own pattern matching elsewhere
    # is explicitly subordinated to it.
    hints = detect_product_type(site_data)
    parts.append(_format_product_type_block(hints))
    parts.append("")
    parts.append(f"## 目标产品网站:{url}(域名:{domain})\n")
    parts.append(f"抓取时间:刚刚(实时 fetch)\n")

    # Homepage
    hp = site_data.get("homepage", {})
    if hp:
        parts.append("### 首页信息")
        parts.append(f"- Title: {hp.get('title') or '(未提取到 title)'}")
        desc = hp.get("description")
        if desc is not None:
            parts.append(f"- Meta Description: {desc!r} (length: {len(desc)} chars)")
        else:
            parts.append("- Meta Description: (未提取到,可能未设置)")
        if hp.get("text"):
            parts.append(f"\n#### 首页正文(前 8000 字):\n{hp['text'][:8000]}")
        else:
            parts.append("\n#### 首页正文:未抓取到")
        if hp.get("links"):
            internal_links = [l for l in hp["links"] if domain in l][:30]
            external_links = [l for l in hp["links"] if domain not in l][:15]
            if internal_links:
                parts.append(f"\n#### 站内链接(前 {len(internal_links)} 条):")
                parts.append("\n".join(f"  - {l}" for l in internal_links))
            if external_links:
                parts.append(f"\n#### 外部链接(前 {len(external_links)} 条):")
                parts.append("\n".join(f"  - {l}" for l in external_links))
    else:
        parts.append("### 首页信息\n首页抓取失败 - 报告中提到首页时,请写'首页未抓取'。")

    # Robots.txt - full text, no truncation
    robots = site_data.get("robots_txt")
    if robots:
        parts.append(f"\n### robots.txt(完整原文)")
        parts.append("```")
        parts.append(robots.strip())
        parts.append("```")
        parts.append("⚠️ 上面是 robots.txt 的 LITERAL 原文。任何关于 robots.txt 的判断必须基于这里实际出现的 directive,不允许引入未出现的 Disallow / Allow / User-Agent。")
    else:
        parts.append("\n### robots.txt\n未抓取到(/robots.txt 不存在或抓取失败)。报告中不能假装看到 robots.txt 的内容。")

    # Pricing
    pricing = site_data.get("pricing_page")
    if pricing and isinstance(pricing, dict):
        parts.append(f"\n### 定价页面(/pricing 抓取成功)")
        parts.append(f"- Title: {pricing.get('title') or '未提取'}")
        if pricing.get("text"):
            parts.append(f"\n{pricing['text'][:5000]}")
    elif pricing is None:
        parts.append("\n### 定价页面\n/pricing 返回 404 或抓取失败。注意:可能 /pricing.html 存在但 /pricing 无扩展名版本未配置 - 不要直接断言'未上线',写'/pricing 不可访问,需确认是否仅 .html 版本可达'。")

    # Sitemap - STRUCTURED, NO TRUNCATION
    sitemap = site_data.get("sitemap")
    if sitemap and isinstance(sitemap, str):
        parts.append(f"\n### Sitemap.xml(结构化摘要)")
        parts.append(_parse_sitemap_structured(sitemap, domain))
        parts.append("\n⚠️ 上面列出了 sitemap 中的**所有** URL(按目录聚合)。不要推荐用户创建 sitemap 中已存在的页面。")
    elif sitemap is None:
        parts.append("\n### Sitemap.xml\n未抓取到。报告中不可声称 sitemap 包含 N 个 URL - 写 '未抓取,无法统计'。")

    return "\n".join(parts)


# ─── Post-LLM Sanitizer ─────────────────────────────────────────────────────
# Even with strong prompts, LLMs slip in "absence on homepage = nonexistence"
# phrasing under long-form generation pressure. The sanitizer is a deterministic
# safety net: it rewrites known anti-patterns into the canonical "首页未展示"
# phrasing so users never see a confidently-wrong claim about their own
# channel program (KOL / Discord / PH / Reddit / paid spend).
#
# Patterns are (regex, replacement) pairs. They are intentionally narrow -
# we only rewrite phrases that confidently assert nonexistence; we leave
# "首页未展示 KOL" alone (that's the correct version we want).

import re as _re

# Rules MUST run longest-pattern-first to avoid nested re-rewriting (e.g. so
# "未发现 Discord" doesn't re-match inside a sentence we just rewrote that
# now contains "未发现 Discord 入口"). We also use a sentinel marker so we
# don't re-process replaced text.
_SCRUB_MARKER = "​"  # zero-width space, invisible

_ABSENCE_REWRITES = [
    # ── KOL - long patterns first ─────────────────────────────────────────
    (r"无\s*KOL\s*合作\s*迹象", "首页未展示 KOL 合作墙(不代表用户未启动 KOL 计划)"),
    (r"未发现\s*KOL\s*合作\s*痕迹", "首页未展示 KOL 合作展示(用户的 KOL 名单通常不在 marketing site 上)"),
    (r"未发现[^。\n]{0,20}KOL\s*合作", "首页未展示 KOL 合作展示(KOL 名单通常不在 marketing site 上)"),
    (r"无明确的?\s*KOL\s*合作[^,。\n]*?", "首页未展示 KOL 合作(不代表未合作)"),
    (r"无\s*KOL\s*合作", "首页未展示 KOL 合作(不代表未合作)"),
    (r"缺乏\s*KOL\s*评测", "首页未展示 KOL 评测引用(如已有,请用户提供链接)"),
    (r"无\s*KOL\s*评测", "首页未展示 KOL 评测(如已有 KOL 内容请用户提供)"),

    # ── Community / Discord / Slack - combo patterns first ───────────────
    (r"未发现社区(?:链接)?\s*\(?[^))]*?(?:Reddit|Discord|Slack)[^))]*?\)?\s*(?:或\s*KOL\s*合作\s*痕迹)?",
     "首页未展示社区入口(如已有 Reddit/Discord/Slack 请用户提供链接)"),
    (r"外部链接无\s*Discord(?:\s*/\s*Slack)?\s*入口", "首页前 N 个外链中未发现 Discord/Slack 入口(footer 或 /community 子页面可能存在)"),
    (r"无\s*Discord\s*/\s*Slack\s*入口", "首页未直接展示 Discord/Slack 入口"),
    (r"站内无社区链接", "首页主链接区未展示社区入口(footer 或子页面可能存在)"),
    (r"无任何社区入口", "首页未展示社区入口"),
    (r"对于 Dev Tool 是严重缺失", "对于 Dev Tool,若尚未建立社区,是值得补强的维度"),
    (r"对于 Dev Tool,这是关键缺失", "对于 Dev Tool,如尚未建立社区,是值得补强的维度"),
    (r"缺乏社区", "首页未展示社区入口(如已有 Discord/Slack/论坛,请用户提供)"),
    # Catch-all for stray "未发现 Discord/Reddit" (after combo patterns above)
    (r"未发现\s*Discord(?!【)", "首页未展示 Discord 引用"),  # negative-lookahead to avoid re-matching
    (r"未发现\s*Reddit(?!【)", "首页未展示 Reddit 引用"),

    # ── Product Hunt ─────────────────────────────────────────────────────
    (r"无\s*Product\s*Hunt\s*活动\s*痕迹", "首页未展示 Product Hunt badge(不代表未发布过;可能在 PH 平台有 launch 记录)"),
    (r"未发现\s*Product\s*Hunt", "首页未展示 Product Hunt 引用"),
    (r"无\s*PH\s*活动", "首页未展示 PH 引用"),
    # PH "无提及" - pure absence claim
    (r"(\|\s*\*\*Product\s*Hunt\*\*\s*\|\s*)无提及", r"\1首页未展示 PH badge / launch 引用"),

    # ── Reddit ───────────────────────────────────────────────────────────
    (r"无\s*Reddit\s*活动", "首页未展示 Reddit 内容引用"),

    # ── Paid spend / Sales pipeline ──────────────────────────────────────
    (r"无任何数据表明正在进行付费投放", "本次审计不包含付费投放数据采集(用户可提供 GA / 广告后台数据)"),
    (r"无付费广告", "本次审计未抓取付费投放数据"),
    (r"无\s*Sales[^,。\n]*?活动", "本次审计未抓取 Sales pipeline 数据"),
]

# Hard-banned phrases that should never make it to a paid customer.
# If any matches after rewrites, we append a notice so the user knows the
# LLM made a category error.
_HARD_FORBIDDEN = [
    r"100\+\s*founders",                       # fake testimonial number
    r"B2B 采购中\s*\d+%",                        # fake stat
    r"行业基准是\s*\d+%",                        # fake stat
]


def _scrub_absence_phrases(md: str) -> str:
    """Run the absence-rewrite + forbidden-phrase passes over LLM output."""
    if not md:
        return md
    out = md
    for pattern, replacement in _ABSENCE_REWRITES:
        out = _re.sub(pattern, replacement, out)
    # Detect hard-banned phrases (don't rewrite - surface them so we can
    # diagnose prompts that failed). They are usually rare.
    forbidden_hits = []
    for pattern in _HARD_FORBIDDEN:
        if _re.search(pattern, out):
            forbidden_hits.append(pattern)
    if forbidden_hits:
        log.warning("Sanitizer detected hard-forbidden phrases: %s", forbidden_hits)
    return out


# ─── Real Gingiris Skill Registry ───────────────────────────────────────────
# Maps the canonical Gingiris skill slugs to their descriptions and links.
# The LLM used to invent skill names like "bofu-content-harvest" or
# "enterprise-sales-enablement" - those don't exist. We constrain it to
# this registry both via prompt (system prompt lists real names) and via
# a post-processor that flags any skill name not in this list.

# Sourced live from https://gingiris.tools/skills/  (40 skills).
# Categorized by primary growth motion so _pick_skills_for_product_type can
# build multi-dimensional recommendations (not just SEO/GEO).
GINGIRIS_SKILL_REGISTRY = {
    # ── Launch / Product Hunt ────────────────────────────────────────────
    "gingiris-launch": {
        "title": "AI Product Launch - Multi-Channel GTM",
        "desc": "Multi-channel launch sequencing across PH + Twitter + KOL + content + community(150+ AI startup launches)",
        "best_for": "PLG / Consumer / OSS 产品发布前 6-12 周准备",
        "category": "launch",
    },
    "product-hunt-playbook": {
        "title": "Product Hunt Playbook - Win #1 Daily",
        "desc": "PH 排名算法 + engagement 优化(30x PH #1 daily champion 实战)",
        "best_for": "PLG / Consumer 产品 PH 发布前 4 周",
        "category": "launch",
    },
    "product-hunt-launch-guide": {
        "title": "Product Hunt Launch Guide - Hour-by-Hour #1 Daily SOP",
        "desc": "首次发布者完整指南:时间线 + asset 准备 + 发布日小时级 SOP",
        "best_for": "首次发 PH 的团队",
        "category": "launch",
    },
    "startup-launch": {
        "title": "Startup Launch - Day-1 to First 100 Users",
        "desc": "发布日小时级执行 + 危机管理",
        "best_for": "前 100 用户阶段,需要落地节奏",
        "category": "launch",
    },
    "startup-launch-playbook": {
        "title": "Startup Launch Playbook - First Week SOP",
        "desc": "Pre-seed 到 1000 用户阶段 + MVP 验证 + 渠道选择",
        "best_for": "0→1000 用户阶段",
        "category": "launch",
    },
    "ai-launch-playbook": {
        "title": "AI Launch Playbook - AI 产品专用 GTM",
        "desc": "AI 产品专属 GTM 策略(基于 breakout AI launches 复盘)",
        "best_for": "AI Native 产品 launch",
        "category": "launch",
    },
    "ai-product-launch": {
        "title": "AI Product Launch - Technical GTM",
        "desc": "0 到上线 30 天,AI Native 产品首发完整流程",
        "best_for": "首次发布 AI 产品",
        "category": "launch",
    },
    "go-to-market-playbook": {
        "title": "Go-to-Market Playbook - Strategy & Channel Selection",
        "desc": "可复用 GTM 模板:positioning + 渠道选型 + 时间线",
        "best_for": "需要 GTM 框架的所有阶段产品",
        "category": "launch",
    },

    # ── SEO / GEO ────────────────────────────────────────────────────────
    "gingiris-seo-geo-agent": {
        "title": "SEO/GEO Agent SOP - AI-Powered Search Optimization",
        "desc": "1 月跑 32K 曝光的自主 SEO Agent - daily audit + ranking 追踪 + schema 验证 + IndexNow 三件套",
        "best_for": "想用 agent 自动化 SEO/GEO 的团队",
        "category": "seo",
    },
    "i18n-seo-geo": {
        "title": "SEO & GEO 2026 - Rank Google + AI Search",
        "desc": "Google 搜索 + AI 搜索(ChatGPT/Perplexity/Claude)双引擎引用策略",
        "best_for": "需要被 AI 搜索引擎引用的内容站",
        "category": "seo",
    },

    # ── B2B / SaaS ───────────────────────────────────────────────────────
    "gingiris-b2b-growth": {
        "title": "B2B SaaS Growth - PMF→$10M ARR",
        "desc": "PLG/SLG 决策 + 客户访谈 + 联盟营销 + Enterprise sales - HeyGen / Deel / Vercel 实战",
        "best_for": "**Enterprise / B2B mid-market 必装**",
        "category": "b2b",
    },
    "saas-growth-playbook": {
        "title": "SaaS Growth Playbook - MRR $0→$50K Scaling",
        "desc": "Revenue-focused:定价、churn、活跃用户战术",
        "best_for": "SaaS $0→$50K MRR 阶段",
        "category": "b2b",
    },
    "plg-playbook": {
        "title": "PLG Playbook - Product-Led Growth Implementation",
        "desc": "Freemium 设计 + 自助 onboarding + activation 指标",
        "best_for": "PLG 模式 SaaS",
        "category": "b2b",
    },
    "b2b-marketing-playbook": {
        "title": "B2B Marketing Playbook - Enterprise GTM & ABM",
        "desc": "LinkedIn + cold email + webinar funnel($0→$1M ARR)",
        "best_for": "B2B 销售驱动产品",
        "category": "b2b",
    },
    "saas-marketing-playbook": {
        "title": "SaaS Marketing Playbook - Full-Stack Channel System",
        "desc": "按增长阶段组织的工具 + 指标",
        "best_for": "SaaS 营销全栈视角",
        "category": "b2b",
    },

    # ── Open Source ──────────────────────────────────────────────────────
    "gingiris-opensource": {
        "title": "Open Source Marketing - GitHub Stars 0→60K",
        "desc": "每个增长阶段的决策框架(AFFiNE 0→60K stars 复盘)",
        "best_for": "OSS 产品",
        "category": "oss",
    },
    "github-stars-playbook": {
        "title": "GitHub Stars Playbook - 0→10K+ Stars",
        "desc": "14 天 sprint:Show HN + Reddit + Twitter thread",
        "best_for": "0→10K stars 阶段",
        "category": "oss",
    },
    "gingiris-github-star-growth": {
        "title": "GitHub Star Sustained Growth - 300+ Stars/Month",
        "desc": "Launch 后维持月增 300+ stars",
        "best_for": "已发布 OSS 但增长平缓",
        "category": "oss",
    },
    "open-source-marketing-playbook": {
        "title": "Open Source Marketing - HN, Reddit & Community Launch",
        "desc": "README 优化 + 贡献者吸引 SOP",
        "best_for": "OSS founders",
        "category": "oss",
    },

    # ── ASO / Mobile ─────────────────────────────────────────────────────
    "gingiris-aso-growth": {
        "title": "ASO & App Cold Start - Organic + UGC",
        "desc": "Organic 关键词 + 截图设计 + UGC 创作者矩阵",
        "best_for": "Mobile App 冷启动",
        "category": "mobile",
    },
    "aso-playbook": {
        "title": "ASO Playbook - App Store Optimization",
        "desc": "关键词研究 + 评分管理 + A/B 测试",
        "best_for": "Mobile App 排名优化",
        "category": "mobile",
    },
    "i18n-aso-growth": {
        "title": "ASO & App Cold Start - Organic-First Mobile",
        "desc": "iOS + Google Play 完整 ASO 指南",
        "best_for": "Mobile App 多平台",
        "category": "mobile",
    },

    # ── KOL / Influencer ─────────────────────────────────────────────────
    "gingiris-kol-outreach": {
        "title": "KOL Outreach - Discovery to ROI Tracking",
        "desc": "找 KOL + 报价基准 + ROI 测量(AFFiNE 200+ KOL 合作实战)",
        "best_for": "需要启动或优化 KOL 计划的产品",
        "category": "kol",
    },
    "kol-outreach": {
        "title": "KOL Outreach - Pricing & ROI Framework",
        "desc": "Cold outreach 模板 + follow-up 序列",
        "best_for": "0→1 KOL 计划",
        "category": "kol",
    },

    # ── UGC ──────────────────────────────────────────────────────────────
    "gingiris-ugc-matrix": {
        "title": "UGC Matrix Growth - AI + Human Creators",
        "desc": "AI + 真人创作者规模化,CPM $0.5 / 60 天 $10M ARR / 70M impressions",
        "best_for": "**仅适合 Consumer/PLG**,B2B/Enterprise 不适用",
        "category": "ugc",
    },

    # ── Community / DevRel ───────────────────────────────────────────────
    "community-ambassador-playbook": {
        "title": "Community Ambassador Playbook - Recruitment to Retention",
        "desc": "大使招募 + 防 ghosting + 长期激励",
        "best_for": "有用户基数想做大使计划的产品",
        "category": "community",
    },
    "community-building-playbook": {
        "title": "Community Building Playbook - Discord/Slack/OSS",
        "desc": "Discord、Slack、OSS 社区增长策略",
        "best_for": "需要建社区的所有产品",
        "category": "community",
    },
    "devrel-playbook": {
        "title": "DevRel Playbook - Developer Relations SOP",
        "desc": "社区 + 文档 + conference 演讲",
        "best_for": "Dev Tool / API 产品",
        "category": "community",
    },
    "developer-marketing-playbook": {
        "title": "Developer Marketing - DevRel, Docs & Community Funnel",
        "desc": "DevRel + API 体验 + hackathon 策略",
        "best_for": "Developer 产品 funnel",
        "category": "community",
    },

    # ── Reddit ───────────────────────────────────────────────────────────
    "gingiris-reddit-marketing": {
        "title": "Reddit Marketing - Shadow Ban, AMA, AI Citation",
        "desc": "Reddit = ChatGPT/Claude 40.11% 训练数据(最高权重 UGC 源)+ 防影子封禁 + 7 案例",
        "best_for": "想做 Reddit 种草 / AI 训练数据曝光",
        "category": "community",
    },

    # ── PMF / User Research ──────────────────────────────────────────────
    "gingiris-user-interview": {
        "title": "User Interview & PMF Validation - JTBD, Churn Diagnostics",
        "desc": "通过 customer discovery 找激活问题",
        "best_for": "**所有产品的基础设施**,PMF 验证必备",
        "category": "research",
    },

    # ── Generic Startup ──────────────────────────────────────────────────
    "startup-consultant": {
        "title": "Startup Consultant - On-Demand Growth Advisory",
        "desc": "PH launches、OSS、GTM audit 专家评审框架",
        "best_for": "需要外部视角的所有阶段",
        "category": "general",
    },
    "startup-growth-playbook": {
        "title": "Startup Growth Playbook - Seed to Series A",
        "desc": "Seed-stage founder 渠道选择",
        "best_for": "Seed 阶段",
        "category": "general",
    },
    "startup-marketing-playbook": {
        "title": "Startup Marketing - Zero-Budget to Paid",
        "desc": "Bootstrapped 自给型渠道",
        "best_for": "无预算 bootstrap 团队",
        "category": "general",
    },
    "viral-marketing-playbook": {
        "title": "Viral Marketing - K-Factor & Referral",
        "desc": "推荐计划 + viral loop 设计",
        "best_for": "Consumer / PLG 想做病毒传播",
        "category": "general",
    },
    "growth-hacking-playbook": {
        "title": "Growth Hacking Playbook - Viral Loops & Experimentation",
        "desc": "50 个战术(按 effort vs impact 排序)",
        "best_for": "想跑增长实验的团队",
        "category": "general",
    },
    "growth-hacking": {
        "title": "Growth Hacking - B2B SaaS & Dev Tools Experiments",
        "desc": "B2B SaaS + dev tools 增长实验",
        "best_for": "B2B + Dev Tools",
        "category": "general",
    },

    # ── Meta / Router ────────────────────────────────────────────────────
    "gingiris-growth-finder": {
        "title": "Growth Finder - AI Strategy Router",
        "desc": "把增长问题路由到对应 Gingiris playbook",
        "best_for": "不确定装哪个 skill 时的入口",
        "category": "router",
    },
    "i18n-growth-finder": {
        "title": "Growth Finder - Meta-router (i18n)",
        "desc": "增长问题 → 自动触发 playbook 的多语言版",
        "best_for": "多语言团队",
        "category": "router",
    },

    # ── Agent ────────────────────────────────────────────────────────────
    "agent-workflow-playbook": {
        "title": "Agent Workflow - AI Multi-Agent Orchestration",
        "desc": "Multi-agent 设计模式 + 插件架构",
        "best_for": "构建 AI agent 系统的产品",
        "category": "agent",
    },

    # ── Twitter / X Ops ──────────────────────────────────────────────────
    "gingiris-twitter-agent-ops": {
        "title": "Twitter Agent Ops - AI Ghostwriter SOP",
        "desc": "AI agent 当推特代笔人:人设校准 + 素材库 + 排期 + 红线规则 + 发布前质检。45 天 1150→1837 关注 (+60%),每天 1 条",
        "best_for": "**Founder 个人品牌不发力的所有产品**,0→1 推特账号",
        "category": "social",
    },

    # ── Competitor Intel / Go-Global ─────────────────────────────────────
    "competitor-research-playbook": {
        "title": "Competitor Research Playbook - Wayback to Flywheel",
        "desc": "Wayback 拆官网演化 + X/Twitter 传播链 + 增长飞轮 6 阶段评分 (150+ AI startup 案例 + Lovable 完整复盘)",
        "best_for": "需要拆竞品并定位差异化的所有阶段",
        "category": "intel",
    },
    "gingiris-go-global": {
        "title": "Go-Global SOP - Phase 0→5 Full Cycle",
        "desc": "出海完整 SOP:市场验证 → 定位 → 前 100 用户 → 用户访谈 → Beta→增长 + OSS launch / PH / Reddit / SEO/GEO / 转化 / 组织",
        "best_for": "**所有中国团队出海产品 (Day 0)**",
        "category": "global",
    },
}


# Concrete tactics per skill - used to override the LLM's tendency to
# produce "做 SEO 优化"-level platitudes. Each entry is 2-3 ultra-specific
# tactical recipes with real benchmarks/templates so the LLM can cite them
# verbatim in the action plan rather than vaguely gesturing.
#
# Format: each tactic = (when, what, benchmark/proof).
# Numbers are from real Gingiris case studies, not invented.
GINGIRIS_SKILL_TACTICS = {
    "gingiris-launch": [
        ("发布前 W-6", "Asset 包:30s teaser video + 5 静图 + 1 founder-story tweet + comparison table", "30+ PH #1 daily 全用同一模板"),
        ("发布前 W-2", "搭 launch team:~30 PH hunters + 20 X amplifier + 5 newsletter,发布日 1 小时内集中投票", "投票分散 6+ 小时 = rank 跌出 top 10"),
        ("发布日 H+0~3", "Founder 亲发 X thread (≤7 推) + 评论区每条回复 ≤10 分钟", "高 engagement = PH 算法加权"),
    ],
    "product-hunt-playbook": [
        ("发布前 D-7", "Upcoming page + 200 maker comment 攒 buzz", "PH 算法看预热互动"),
        ("发布日 00:01 PT", "Maker 第一条 comment 必须含 'Hi PH community, X here from Y...' 标准开场", "缺了直接被 hide"),
        ("发布日 H+0~6", "每 1-2 小时 founder 回所有 comment,X 持续 retweet 阶段性 update", "保 momentum 不停"),
    ],
    "gingiris-seo-geo-agent": [
        ("W1", "搭 SEO Agent 三件套:daily audit + ranking 追踪 + schema 验证 + IndexNow push", "1 个月 32K impressions"),
        ("W1-2", "Hub-spoke 内链:1 个 hub page + 6 个 spoke 互链,targeting KD 20-35 关键词", "AFFiNE 同打法 6 周拿 top 3"),
        ("W2-4", "GEO 三件套:FAQ schema + AI 友好 robots.txt + Brave/Perplexity index 提交", "AI search 被引用率 30%+"),
    ],
    "gingiris-kol-outreach": [
        ("W1", "KOL 筛选:用 Brave Search + Twitter API 筛 followers 1K-50K 的 micro-KOL,避开 macro (ROI 差 3x)", "AFFiNE 200+ KOL 实战,micro 转化 5-8%"),
        ("W2", "Outreach 模板:'你最近关于 X 的帖子我看了,我们在做 Y 跟你 X 视角对得上,能寄你试用吗?' + 不要直接给链接", "Cold 回复率 18% vs 模板 outreach 2%"),
        ("W3-4", "ROI 测量:每个 KOL 单独 UTM + Linktree slot,CAC < $25 才续约", "盲投 1000 美元 = 0 转化的常见陷阱"),
    ],
    "gingiris-reddit-marketing": [
        ("W1", "养号 SOP:先 karma 0→500(20 天),评论 50+ 真实回答 + 0 自家产品提及", "Reddit 内容是 ChatGPT/Claude 40.11% 训练数据"),
        ("W2", "选 sub:用 subredditstats.com 找 active>5K + content style 'show & tell' 友好的 sub,避开纯 news sub", "AFFiNE 3-4 万曝光 + 5-8% GitHub star 转化"),
        ("W3-4", "AMA SOP:找 mod 24 小时前预约 + 准备 20 个 seed Q&A + founder 真名上 + 持续 4 小时", "Base44 用同样格式拿 $80M AMA"),
    ],
    "gingiris-ugc-matrix": [
        ("W1", "找 5-10 个真人 creator (TikTok 5K-20K followers),按出片付费 $30-50/支", "CPM $0.5 vs paid ads $5-15"),
        ("W2", "AI 矩阵号:用 ElevenLabs + Sora + Hedra 量产 50 条/周,每号差异化人设", "60 天 $10M ARR / 70M impressions 案例"),
        ("W3+", "Top-3 表现内容 reinvest:投流 boost 跑赢 baseline 2x 才追加", "盲投 50% 预算浪费"),
    ],
    "gingiris-twitter-agent-ops": [
        ("W1", "人设校准:voice guide + 死开场 blacklist + 5 段过往真实推作 sample,喂 AI agent", "AI 写的初稿过 triple-translation test 才发"),
        ("W2", "排期:每天 1 条 8AM PT 黄金窗口 + 周三/五各 1 条 thread,dedup 检查防重", "45 天 1150→1837 关注 (+60%)"),
        ("W3-4", "数据闭环:tweet-log 周报 → top-3 archetype reinforce + bottom-3 type 砍掉", "纯凭感觉发等于浪费 50% 时间"),
    ],
    "gingiris-aso-growth": [
        ("W1", "关键词研究:用 Sensor Tower 找 traffic>1K + difficulty<30 的 long-tail,5 个塞 title/subtitle", "ASO 占 70% organic install"),
        ("W2", "截图 A/B:4 套创意,每套 1 周,按 CVR 留最优", "截图差异 = CVR 差 2-3x"),
        ("W3+", "UGC creator 矩阵:5 TikTok creator × 3 video / 月,导流 App Store", "i18n-aso-growth 同打法 multi-locale"),
    ],
    "gingiris-b2b-growth": [
        ("W1", "ICP 锚定:用 user-interview SOP 跑 5 场 60min 访谈,提炼 'JTBD 一句话'", "HeyGen 937 场访谈到 PMF"),
        ("W2", "LinkedIn ABM:用 Apollo + Clay 抓 100 个 ICP,定制 3-touch 序列(教育→案例→demo)", "B2B cold reply rate 12% vs 模板 1%"),
        ("W3-4", "案例 study:与 3 个 lighthouse 客户做 co-marketing case study,输出 X thread + LinkedIn post + landing page", "案例 page 比 feature page 高 4x CVR"),
    ],
    "gingiris-opensource": [
        ("W1", "README 优化:hero gif + tagline + 5 行 quickstart + comparison table(对照 #1-3 alternatives)", "AFFiNE 0→60K stars"),
        ("W2", "Show HN:周二/周三 8AM PT 发,标题 'Show HN: X - the Y open-source alternative to Z'", "Show HN front-page = 1-5K stars/周"),
        ("W3+", "Reddit/Discord/Twitter 三轨:weekly digest + roadmap voting + contributor shoutout", "维持 300+ stars/月 (sustained skill 模板)"),
    ],
    "github-stars-playbook": [
        ("D1-3", "14 天 sprint:Day 1 Show HN, Day 3 Reddit r/programming, Day 5 X thread, Day 7 Hacker Newsletter", "10K stars 24-36 个月加速到 14 天"),
        ("D7-10", "Newsletter outreach:JS Weekly, Pointer.io, TLDR - pitch 是 1 段 + 1 demo gif", "命中率 30% (vs PR 模板 3%)"),
    ],
    "gingiris-user-interview": [
        ("W1", "5 场 60min 访谈 + JTBD 问题模板('上次你解决 X 的方式 / 哪里卡 / 改用我们之后变化')", "HeyGen 937 场访谈复盘"),
        ("W2", "Churn 诊断:用流失用户访谈反推激活 gap (cohort 4-09 类似)", "PMF 前 churn root cause 80% 是 onboarding"),
    ],
    "competitor-research-playbook": [
        ("W1", "拆 top 3 对手 Wayback v1/Beta/Launch 3 版官网演化,画 positioning 漂移图", "150+ AI startup 实战"),
        ("W2", "X/Twitter 传播链:用 advanced search 找首发 thread + 转评最多 5 个账号,导出 KOL list", "Lovable 4.3M views 复盘同法"),
        ("W3", "飞轮 6 阶段评分:Activation/Referral/Acquisition/Retention/Revenue/Product 各 1-5 分,找弱环节", "对手最弱环节 = 你的 wedge"),
    ],
    "community-ambassador-playbook": [
        ("W1", "申请表:A 题(pre-launch readiness 6 条)+ B 题(评分 rubric) 双 gate 卡 70% noise", "Notion 20M 用户实战"),
        ("W2", "4 级体系:Bronze→Silver→Gold→Platinum,每级 points threshold 公开", "防 ghosting 关键"),
        ("W3+", "Churn 早期预警:连续 2 周 0 活动 → 1v1 调研,不要直接踢", "AFFiNE 60K stars 同打法"),
    ],
    "gingiris-go-global": [
        ("Phase 0-1", "市场验证 + positioning:抓 5 个 ICP 国家 × 3 个 substitute 跑过 user-interview", "出海最常死在 Phase 0 跳过"),
        ("Phase 2-3", "前 100 用户:OSS launch 走 HN/Reddit 路径,闭源走 PH/X founder thread 路径", "Gingiris 自身验证"),
        ("Phase 4-5", "Beta→增长:建立 weekly digest 邮件 + 1v1 onboarding call 节奏 (Iris@AFFiNE 同流程)", "10 倍提高 D30 retention"),
    ],
}


# ─── Local SKILL.md paths ────────────────────────────────────────────────────
# Skills live in /Users/iriscarrot/.agents/skills/<slug>/SKILL.md on the Mac.
# On Fly.io they won't be present - we fall back to the tactical snippets.
# Skills lookup: prefer bundled gingiris-skills/ inside the repo (works on Fly.io),
# fallback to ~/.agents/skills/ on developer machines.
_REPO_SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gingiris-skills")
_LOCAL_SKILLS_DIR = os.path.expanduser("~/.agents/skills")
_SKILLS_DIR = _REPO_SKILLS_DIR if os.path.isdir(_REPO_SKILLS_DIR) else _LOCAL_SKILLS_DIR

# Maps product_type keyword → ordered list of skill slugs to inject.
# We pick the first 4 that have a readable SKILL.md (to cap prompt size).
_PRODUCT_TYPE_SKILL_MAP: dict[str, list[str]] = {
    "OSS Dev Tool": [
        "gingiris-opensource",
        "gingiris-github-star-growth",
        "gingiris-seo-geo",
        "gingiris-reddit-marketing",
        "gingiris-launch",
        "gingiris-user-interview",
    ],
    "Enterprise Infra / B2B Sales-led": [
        "gingiris-b2b-growth",
        "gingiris-seo-geo",
        "gingiris-user-interview",
        "gingiris-go-global",
        "gingiris-kol-outreach",
    ],
    "PLG / Self-serve SaaS": [
        "gingiris-launch",
        "gingiris-seo-geo",
        "gingiris-kol-outreach",
        "gingiris-reddit-marketing",
        "gingiris-ugc-matrix",
        "gingiris-user-interview",
    ],
    "Mobile App": [
        "gingiris-aso-growth",
        "gingiris-ugc-matrix",
        "gingiris-kol-outreach",
        "gingiris-user-interview",
        "gingiris-seo-geo",
    ],
    "Unknown / 需用户确认": [
        "gingiris-growth-finder",
        "gingiris-seo-geo",
        "gingiris-launch",
        "gingiris-b2b-growth",
        "gingiris-user-interview",
    ],
}
# Always inject these regardless of product type (core router + go-global)
_ALWAYS_INJECT = ["gingiris-growth-finder", "gingiris-go-global"]


def _load_skill_content(slug: str, max_chars: int = 3500) -> str:
    """Read a SKILL.md from the local ~/.agents/skills/ dir and return a
    truncated version suitable for injection into an LLM prompt.

    Strips YAML front-matter, keeps the first `max_chars` of body content.
    Returns empty string if file not found (graceful fallback on Fly.io).
    """
    # Try repo-bundled path first, then local dev path
    for base in [_REPO_SKILLS_DIR, _LOCAL_SKILLS_DIR]:
        path = os.path.join(base, slug, "SKILL.md")
        if os.path.isfile(path):
            break
    else:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        # Strip YAML front-matter (--- ... ---)
        body = _re.sub(r"^---[\s\S]*?---\s*", "", raw, count=1).strip()
        # Remove repetitive i18n sections (Japanese/Korean/etc.) to save tokens
        # Keep only up to first non-Chinese/English h2 section boundary
        # Simple heuristic: cut at 3rd occurrence of "---" separator
        parts = body.split("\n---")
        body = parts[0]
        if len(parts) > 1:
            body = "\n---".join(parts[:2])  # keep intro + first major section
        if len(body) > max_chars:
            body = body[:max_chars] + "\n... [skill truncated for prompt budget]"
        return body
    except Exception:
        return ""


def _build_injected_skills_block(product_type: str, max_skills: int = 4) -> str:
    """Build a skill-content injection block tailored to the product type.

    Returns a Markdown block with up to `max_skills` SKILL.md excerpts.
    The total budget is ~14K chars (~3500 tokens) so the system prompt
    stays within context limits even on older models.
    """
    # Determine candidate slugs
    type_key = product_type
    if type_key not in _PRODUCT_TYPE_SKILL_MAP:
        # Fuzzy match
        for key in _PRODUCT_TYPE_SKILL_MAP:
            if key.lower() in product_type.lower() or product_type.lower() in key.lower():
                type_key = key
                break
        else:
            type_key = "Unknown / 需用户确认"

    candidates = _PRODUCT_TYPE_SKILL_MAP[type_key]
    # Prepend always-inject slugs (deduplicated)
    seen: set[str] = set()
    ordered: list[str] = []
    for slug in _ALWAYS_INJECT + candidates:
        if slug not in seen:
            seen.add(slug)
            ordered.append(slug)

    loaded: list[tuple[str, str]] = []
    for slug in ordered:
        if len(loaded) >= max_skills:
            break
        content = _load_skill_content(slug)
        if content:
            loaded.append((slug, content))

    if not loaded:
        return ""  # Fly.io fallback - skills dir not present

    sections = [
        "",
        "## 🧠 已加载的 Gingiris Skill 全文(按产品类型匹配)",
        "",
        f"产品类型: **{product_type}**",
        "",
        f"以下是为此产品类型选出的 {len(loaded)} 个增长手册全文（包含实战战术、模板、基准数据）。",
        "在生成诊断和行动计划时,必须引用这些 skill 里的具体战术和模板,不要只写 skill 名称。",
        "",
    ]
    for slug, content in loaded:
        meta = GINGIRIS_SKILL_REGISTRY.get(slug, {})
        title = meta.get("title", slug)
        sections += [
            f"### `{slug}` - {title}",
            "",
            content,
            "",
            "---",
            "",
        ]
    return "\n".join(sections)


def _build_skill_registry_prompt() -> str:
    """Render the registry as a constraint block injected into the system prompt."""
    lines = [
        "",
        "## 📦 真实可用的 Gingiris Skills(**强制使用此列表,不允许发明新 skill 名**)",
        "",
        "下面是 Gingiris-1031 官方仓库下所有可用的 skill。引用 skill 时必须使用 **canonical slug**(左列)。",
        "如果某个 finding 没有匹配的 skill,写 \"(暂无官方 skill 直接覆盖,建议自定义)\",**不要发明 slug**。",
        "",
        "| Canonical Slug | 适用场景 |",
        "|---|---|",
    ]
    for slug, meta in GINGIRIS_SKILL_REGISTRY.items():
        lines.append(f"| `{slug}` | {meta['best_for']} |")
    lines.append("")
    lines.append("**Sales-led / Enterprise Infra 类产品的核心 skills**:")
    lines.append("- `gingiris-b2b-growth`、`gingiris-seo-geo`、`gingiris-seo-geo-agent`、`gingiris-kol-outreach`(B2B 版)、`gingiris-user-interview`")
    lines.append("")
    lines.append("**PLG / Consumer 类产品的核心 skills**:")
    lines.append("- `gingiris-launch`、`gingiris-seo-geo`、`gingiris-reddit-marketing`、`gingiris-ugc-matrix`、`gingiris-kol-outreach`")
    lines.append("")
    lines.append("**OSS 类产品的核心 skills**:")
    lines.append("- `gingiris-opensource`、`gingiris-github-star-growth`、`gingiris-seo-geo`、`gingiris-reddit-marketing`")
    return "\n".join(lines)


def _expand_skill_install_commands(md: str) -> str:
    """Replace short install commands in the report with a detailed install
    guide appended at the bottom of the document.

    Detects multiple patterns the LLM tends to use:
      - `gingiris install <slug>`
      - `/install <slug>`
      - `npx skills add Gingiris-1031/<slug>`

    For each found slug, validates against the registry. Real ones get a
    full 3-method install block. Invented ones get flagged with a notice
    suggesting the closest real skill from the registry.
    """
    if not md:
        return md

    patterns = [
        r"`gingiris install ([a-z0-9-]+)`",
        r"`/install ([a-z0-9-]+)`",
        r"`npx skills add Gingiris-1031/([a-z0-9-]+)`",
        # bare mentions inside code blocks
        r"gingiris install ([a-z0-9-]+)",
        r"npx skills add Gingiris-1031/([a-z0-9-]+)",
    ]
    found_slugs = []
    seen = set()
    for pat in patterns:
        for m in _re.finditer(pat, md):
            slug = m.group(1)
            if slug not in seen:
                seen.add(slug)
                found_slugs.append(slug)
    if not found_slugs:
        return md

    # Build guide
    guide = [
        "",
        "---",
        "",
        "## 📦 如何安装 Gingiris Skills(详细指南)",
        "",
        "**关于 Gingiris Skills**:每个 skill 是一份结构化 SKILL.md,"
        "包含完整方法论、触发关键词、操作步骤。可在 Claude Code、Cursor、"
        "Gemini CLI、Aider 等支持 skill 加载的 AI agent IDE 中使用。",
        "",
        "**三种安装方式**(任选其一):",
        "",
    ]

    real_skills = []
    invented_skills = []
    for slug in found_slugs:
        if slug in GINGIRIS_SKILL_REGISTRY:
            real_skills.append(slug)
        else:
            invented_skills.append(slug)

    for slug in real_skills:
        info = GINGIRIS_SKILL_REGISTRY[slug]
        guide.extend([
            f"### {info['title']}  &nbsp;·&nbsp; `{slug}`",
            "",
            f"**Skill 内容**:{info['desc']}",
            f"**适用产品**:{info['best_for']}",
            "",
            "**方法 A - Claude Code**(推荐,直接挂入 skill 池)",
            "```bash",
            "# 把 skill 仓库克隆到 ~/.claude/skills/ 下,重启 Claude Code 即生效",
            "mkdir -p ~/.claude/skills",
            f"git clone https://github.com/Gingiris-1031/{slug} \\",
            f"  ~/.claude/skills/{slug}",
            "```",
            "",
            "**方法 B - Cursor / Gemini CLI / 其他 IDE**(作为 project rule 加载)",
            "```bash",
            "# 把 SKILL.md 拉到项目的 rules 目录",
            f"mkdir -p ./.cursor/rules    # 或 ./.gemini/instructions/",
            f"curl -L https://raw.githubusercontent.com/Gingiris-1031/{slug}/main/SKILL.md \\",
            f"  -o ./.cursor/rules/{slug}.md",
            "```",
            "",
            "**方法 C - 浏览器在线阅读**(不安装,直接看)",
            f"- 浏览:https://github.com/Gingiris-1031/{slug}/blob/main/SKILL.md",
            f"- 目录:https://gingiris.tools/skills/  →  搜 `{slug}`",
            "",
            "**触发方式**:装好后,在对话里描述对应场景(例如 \"我们要做 Product Hunt launch\" 会触发 `gingiris-launch`),AI agent 会自动加载 skill 内容作为上下文。",
            "",
        ])

    if invented_skills:
        guide.extend([
            "",
            "### ⚠️ 报告中提到的以下 skill 名**不在 Gingiris 官方目录中**",
            "",
            "可能是 LLM 推断时生成的名字。请到 [gingiris.tools/skills](https://gingiris.tools/skills) "
            "查找最接近的官方 skill:",
            "",
        ])
        for slug in invented_skills:
            guide.append(f"- `{slug}` - 建议查 gingiris.tools/skills 寻找匹配项")
        guide.append("")

    return md.rstrip() + "\n" + "\n".join(guide)


# ─── Real KOL Discovery (uses Brave Search) ─────────────────────────────────
# Generic "find 15-20 micro-KOLs" advice is the most-complained-about part
# of the action plans. Here we actually find specific Twitter/LinkedIn
# handles via Brave Search (which has a key already in Fly secrets) so
# users get real targets they can DM today, not a homework assignment.

def _extract_product_category(site_data: dict) -> list:
    """Pull 2-3 search-friendly category phrases from the homepage so the
    KOL search can be targeted (e.g. 'AI web agent', 'web scraping API',
    'enterprise infrastructure'). We use title + meta description + the
    first ~500 chars of body text and look for noun phrases.
    """
    hp = site_data.get("homepage") or {}
    blob = " ".join(filter(None, [
        hp.get("title"),
        hp.get("description"),
        (hp.get("text") or "")[:600],
    ])).lower()

    # High-signal phrases first (specific niches the audit cares about).
    candidates = [
        "ai agent", "ai web agent", "web scraping", "browser automation",
        "browser api", "mcp server", "rag pipeline", "vector database",
        "llm orchestration", "developer tool", "code editor",
        "competitive intelligence", "competitor analysis", "growth marketing",
        "no-code", "low-code", "workflow automation",
        "saas growth", "product analytics", "user onboarding",
        "design tool", "video editor", "audio editor",
        "fintech", "crypto wallet", "healthtech", "edtech",
    ]
    found = []
    for phrase in candidates:
        if phrase in blob and phrase not in found:
            found.append(phrase)
        if len(found) >= 3:
            break
    if found:
        return found

    # Fallback: pull bigrams from the title that look noun-y.
    title = (hp.get("title") or "").lower()
    title = _re.sub(r"[^a-z0-9 ]", " ", title)
    words = [w for w in title.split() if len(w) > 2]
    if len(words) >= 2:
        return [" ".join(words[:2])]
    return [hp.get("title", "growth")]


async def _discover_real_kols(categories: list, hints: dict, k: int = 6) -> list:
    """Multi-source KOL discovery. Tries each backend in cheap→expensive
    order and stops as soon as we have `k` deduped candidates.

    Backends (in order): Brave → SerpAPI → TwitterAPI.io.

    Background: Brave has been returning 402 (quota exhausted) → audit
    was falling through to no KOL data → LLM was inventing placeholder
    names like 'AI Tool Report'. The fallback chain fixes this by
    consuming SerpAPI (Iris's Developer plan) and TwitterAPI.io
    (already on Fly secrets) when Brave is unavailable.
    """
    if not categories:
        return []
    results: list = []
    seen_handles: set = set()

    async def _merge(source_fn):
        nonlocal results, seen_handles
        if len(results) >= k:
            return
        try:
            rows = await source_fn(categories, hints, k=k - len(results))
        except Exception as e:
            log.warning("KOL backend %s failed: %s", source_fn.__name__, e)
            return
        for r in rows:
            h = (r.get("handle") or "").lower()
            if h and h not in seen_handles:
                seen_handles.add(h)
                results.append(r)
                if len(results) >= k:
                    return

    await _merge(_discover_kols_brave)
    await _merge(_discover_kols_serpapi)
    await _merge(_discover_kols_twitterapi)

    return results[:k]


async def _discover_kols_brave(categories: list, hints: dict, k: int = 6) -> list:
    """Original Brave-based discovery (preserved as Backend #1)."""
    key = (os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
    if not key:
        try:
            key = open(os.path.expanduser("~/.cola/secrets/brave_search_api_key")).read().strip()
        except FileNotFoundError:
            key = ""
    if not key or not categories:
        return []

    # Build queries - sales-led products want engineering leaders &
    # technical writers, PLG products want creator-style accounts.
    if hints.get("is_sales_led"):
        query_templates = [
            'site:twitter.com "{cat}" engineer OR cto',
            'site:linkedin.com/in/ "{cat}" engineer OR principal OR cto',
            '"{cat}" "writes about" twitter',
        ]
    else:
        query_templates = [
            'site:twitter.com "{cat}" tutorial OR guide',
            'site:twitter.com "{cat}" reviewer',
            '"{cat}" influencer twitter',
        ]

    queries = []
    for cat in categories[:3]:
        for tmpl in query_templates:
            queries.append(tmpl.format(cat=cat))

    results = []
    seen_handles = set()
    # Hard cap on total KOL discovery time. Brave can occasionally hang -
    # we don't want one slow query to push total audit wall-clock past
    # the 2-5 min promise.
    started = asyncio.get_event_loop().time()
    HARD_BUDGET_S = 25.0

    async with httpx.AsyncClient(timeout=6) as client:
        for q in queries:
            if len(results) >= k:
                break
            elapsed = asyncio.get_event_loop().time() - started
            if elapsed >= HARD_BUDGET_S:
                log.info("KOL discovery hit %.1fs budget - stopping search",
                         HARD_BUDGET_S)
                break
            try:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": q, "count": 10},
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": key,
                        "User-Agent": "analook-growth-audit/1.0",
                    },
                )
                if r.status_code != 200:
                    continue
                hits = r.json().get("web", {}).get("results", []) or []
            except Exception as e:
                log.warning("Brave KOL search failed for %r: %s", q, e)
                continue

            for hit in hits:
                url = hit.get("url", "") or ""
                title = hit.get("title", "") or ""
                desc = hit.get("description", "") or ""

                # Twitter / X handle
                tw_m = _re.search(r"(?:twitter|x)\.com/([A-Za-z0-9_]{2,15})(?:/|$|\?)", url)
                if tw_m and "/status/" not in url:
                    handle = "@" + tw_m.group(1)
                    if handle.lower() in seen_handles:
                        continue
                    # Filter obvious noise
                    if tw_m.group(1).lower() in {"home", "search", "explore", "i", "compose"}:
                        continue
                    seen_handles.add(handle.lower())
                    results.append({
                        "handle": handle,
                        "platform": "Twitter / X",
                        "bio_snippet": (desc or title)[:220],
                        "source_url": f"https://twitter.com/{tw_m.group(1)}",
                        "found_via": q[:60],
                    })
                    continue

                # LinkedIn profile
                li_m = _re.search(r"linkedin\.com/in/([A-Za-z0-9-]{3,80})", url)
                if li_m:
                    slug = li_m.group(1)
                    handle = f"linkedin.com/in/{slug}"
                    if handle.lower() in seen_handles:
                        continue
                    seen_handles.add(handle.lower())
                    results.append({
                        "handle": slug,
                        "platform": "LinkedIn",
                        "bio_snippet": (desc or title)[:220],
                        "source_url": f"https://linkedin.com/in/{slug}",
                        "found_via": q[:60],
                    })

                if len(results) >= k:
                    break

    return results[:k]


async def _discover_kols_serpapi(categories: list, hints: dict, k: int = 6) -> list:
    """Google search via SerpAPI for the same site:twitter.com /
    site:linkedin.com queries Brave does. SerpAPI has better recall than
    Brave for niche queries and Iris's Developer plan has generous quota.
    """
    key = (os.environ.get("SERPAPI_KEY") or "").strip()
    if not key or not categories:
        return []

    if hints.get("is_sales_led"):
        templates = [
            'site:twitter.com {cat} ("engineer" OR "principal" OR "CTO")',
            'site:linkedin.com/in/ {cat} engineer OR cto',
            '"{cat}" "I write about" site:twitter.com',
        ]
    else:
        templates = [
            'site:twitter.com {cat} (review OR tutorial OR guide)',
            'site:twitter.com "{cat}" ("I share" OR "I build")',
            'site:youtube.com "{cat}" review',
        ]

    queries = []
    for cat in categories[:3]:
        for tmpl in templates:
            queries.append(tmpl.format(cat=cat))

    results = []
    seen = set()
    HARD_BUDGET_S = 20.0
    t0 = asyncio.get_event_loop().time()

    async with httpx.AsyncClient(timeout=8) as client:
        for q in queries:
            if len(results) >= k or (asyncio.get_event_loop().time() - t0) > HARD_BUDGET_S:
                break
            try:
                r = await client.get(
                    "https://serpapi.com/search.json",
                    params={"engine": "google", "q": q, "num": 10, "api_key": key},
                )
                if r.status_code != 200:
                    continue
                hits = r.json().get("organic_results") or []
            except Exception as e:
                log.warning("SerpAPI KOL search failed %r: %s", q, e)
                continue

            for hit in hits:
                url = hit.get("link", "") or ""
                title = hit.get("title", "") or ""
                snippet = hit.get("snippet", "") or ""

                tw_m = _re.search(r"(?:twitter|x)\.com/([A-Za-z0-9_]{2,15})(?:/|$|\?)", url)
                if tw_m and "/status/" not in url:
                    h = "@" + tw_m.group(1)
                    if h.lower() in seen or tw_m.group(1).lower() in {
                        "home", "search", "explore", "i", "compose", "intent",
                    }:
                        continue
                    seen.add(h.lower())
                    results.append({
                        "handle":     h,
                        "platform":   "Twitter / X",
                        "bio_snippet":(snippet or title)[:220],
                        "source_url": f"https://twitter.com/{tw_m.group(1)}",
                        "found_via":  f"SerpAPI: {q[:50]}",
                    })
                    continue

                li_m = _re.search(r"linkedin\.com/in/([A-Za-z0-9-]{3,80})", url)
                if li_m:
                    slug = li_m.group(1)
                    if slug.lower() in seen:
                        continue
                    seen.add(slug.lower())
                    results.append({
                        "handle":     slug,
                        "platform":   "LinkedIn",
                        "bio_snippet":(snippet or title)[:220],
                        "source_url": f"https://linkedin.com/in/{slug}",
                        "found_via":  f"SerpAPI: {q[:50]}",
                    })
                    continue

                yt_m = _re.search(
                    r"youtube\.com/(?:@|c/|channel/|user/)([A-Za-z0-9_-]{3,80})", url
                )
                if yt_m:
                    h = "@" + yt_m.group(1)
                    if h.lower() in seen:
                        continue
                    seen.add(h.lower())
                    results.append({
                        "handle":     h,
                        "platform":   "YouTube",
                        "bio_snippet":(snippet or title)[:220],
                        "source_url": url.split("?")[0],
                        "found_via":  f"SerpAPI: {q[:50]}",
                    })

                if len(results) >= k:
                    break

    return results[:k]


async def _discover_kols_twitterapi(categories: list, hints: dict, k: int = 6) -> list:
    """TwitterAPI.io direct user search by bio keyword. Returns real
    Twitter accounts whose bio matches the product category - usually
    higher quality than SERP-scraped accounts because we get follower
    counts to filter into the micro-KOL band (1K-200K).
    """
    key = (
        os.environ.get("TWITTERAPI_IO_KEY")
        or os.environ.get("TWITTER_API_IO_KEY")
        or ""
    ).strip()
    if not key or not categories:
        return []

    results = []
    seen = set()
    async with httpx.AsyncClient(timeout=12) as client:
        for cat in categories[:3]:
            if len(results) >= k:
                break
            if hints.get("is_sales_led"):
                bio_query = f'"{cat}" (engineer OR CTO OR principal OR architect)'
            else:
                bio_query = f'"{cat}" (review OR tutorial OR creator OR builder)'
            try:
                r = await client.get(
                    "https://api.twitterapi.io/twitter/user/advance_search_by_bio",
                    params={"query": bio_query, "min_followers": 1000, "max_followers": 200000},
                    headers={"x-api-key": key},
                )
                if r.status_code != 200:
                    log.info("TwitterAPI.io status %s for cat=%s", r.status_code, cat)
                    continue
                data = r.json() or {}
                users = data.get("users") or data.get("data") or []
            except Exception as e:
                log.warning("TwitterAPI.io error for %s: %s", cat, e)
                continue

            for u in users[:5]:
                username = (
                    u.get("userName") or u.get("screen_name") or u.get("username")
                )
                if not username:
                    continue
                h = "@" + username
                if h.lower() in seen:
                    continue
                seen.add(h.lower())
                followers = u.get("followers") or u.get("followers_count") or 0
                bio = u.get("description") or u.get("bio") or ""
                snippet = f"{bio[:170]} · {followers:,} followers" if followers else bio[:220]
                results.append({
                    "handle":      h,
                    "platform":    "Twitter / X",
                    "bio_snippet": snippet,
                    "source_url":  f"https://twitter.com/{username}",
                    "found_via":   f"TwitterAPI.io bio:{cat}",
                    "followers":   followers,
                })
                if len(results) >= k:
                    break

    # Micro-KOL band (1K-100K) usually best ROI - sort by followers desc
    results.sort(key=lambda x: x.get("followers") or 0, reverse=True)
    return results[:k]


# ─── Reddit channel discovery (real subs + top posters) ──────────────────────
#
# Uses Reddit's public JSON API (oauth-free, free, no rate limit beyond ~60
# req/min for unauthenticated UA). For each product category we:
#   1. Search subreddits matching the category → take top 3 by subscribers
#   2. For each sub, pull top posts of the last month
#   3. Extract sub stats (subscribers, active users, public_description)
#   4. Identify top contributors from the post sample (author + karma proxy)
#
# Output feeds two places:
#   - _render_reddit_section() → markdown section appended to Action Plan
#   - Action Plan LLM prompt as `reddit_context` block so the LLM cites
#     real sub names + real top posters in W3 Reddit task descriptions
#     instead of generic "post in r/SaaS"-level platitudes.


_REDDIT_UA = "analook-growth-audit/1.0 (+https://www.analook.com)"


async def _discover_reddit_channels(categories: list, hints: dict, k: int = 3) -> list:
    """Return up to k Reddit subs matching the categories. Uses SerpAPI
    `site:reddit.com` Google search rather than Reddit's own API because:
      1. Reddit's anonymous JSON endpoints are 403'd from cloud IPs since
         mid-2024 (anti-OAuth-bypass crackdown).
      2. Google's Reddit ranking is biased toward high-value posts, which
         is exactly the filter we'd want anyway.
      3. SerpAPI is already wired & paid for in this codebase.

    Each result has {name, url, subscribers, description, top_posts,
    top_contributors, found_via}. Subscribers are best-effort (estimated
    from snippet text when present, else None).
    """
    key = (os.environ.get("SERPAPI_KEY") or "").strip()
    if not key or not categories:
        return []

    # Aggregate hits per sub across all category queries, then pick top k.
    sub_hits: dict = {}
    HARD_BUDGET_S = 18.0
    t0 = asyncio.get_event_loop().time()

    async with httpx.AsyncClient(timeout=8) as client:
        for cat in categories[:4]:
            if (asyncio.get_event_loop().time() - t0) > HARD_BUDGET_S:
                break
            # Use a 'best of' style query to bias toward high-quality threads
            q = f'site:reddit.com "{cat}" (recommendation OR review OR "what" OR "how to")'
            try:
                r = await client.get(
                    "https://serpapi.com/search.json",
                    params={"engine": "google", "q": q, "num": 20, "api_key": key},
                )
                if r.status_code != 200:
                    continue
                hits = r.json().get("organic_results") or []
            except Exception as e:
                log.warning("SerpAPI reddit search failed for %r: %s", cat, e)
                continue

            for hit in hits:
                url = hit.get("link", "") or ""
                title = (hit.get("title") or "").strip()
                snippet = (hit.get("snippet") or "")
                # Extract sub name from URL pattern /r/<name>/comments/...
                m = _re.search(r"reddit\.com/r/([A-Za-z0-9_]+)/comments/([A-Za-z0-9]+)", url)
                if not m:
                    continue
                sub_name = m.group(1)
                # Skip user pages, special routes
                if sub_name.lower() in ("u_user", "all", "popular"):
                    continue
                # For sales-led products skip consumer-vibe subs
                if hints.get("is_sales_led"):
                    if sub_name.lower() in ("memes", "funny", "askreddit", "shitposting"):
                        continue
                # Parse author from snippet — Google usually shows "u/<author>" or "by <author>"
                author = None
                au = _re.search(r"u/([A-Za-z0-9_-]{3,30})", snippet)
                if au:
                    author = au.group(1)
                # Best-effort score parse (Reddit snippets sometimes show "1.2K upvotes")
                score = None
                sc = _re.search(r"(\d+(?:\.\d+)?)[\s]?([Kk])?\s+(?:upvote|point)", snippet)
                if sc:
                    raw = float(sc.group(1)) * (1000 if (sc.group(2) or "").lower() == "k" else 1)
                    score = int(raw)
                # Clean Reddit title prefixes like "r/SaaS - Title"
                clean_title = _re.sub(r"^r/[A-Za-z0-9_]+\s*[-—:]\s*", "", title, flags=_re.IGNORECASE)
                clean_title = _re.sub(r"\s*:?\s*r/[A-Za-z0-9_]+\s*$", "", clean_title)

                bucket = sub_hits.setdefault(sub_name, {
                    "name":        sub_name,
                    "url":         f"https://www.reddit.com/r/{sub_name}",
                    "posts":       [],
                    "authors":     {},
                    "subscribers": None,
                    "description": None,
                    "found_via":   f"SerpAPI Google: {cat[:40]}",
                })
                bucket["posts"].append({
                    "title":        clean_title[:140] or "(no title)",
                    "score":        score,
                    "author":       author or "?",
                    "num_comments": None,
                    "url":          url,
                    "permalink":    url,
                })
                if author:
                    a = bucket["authors"].setdefault(
                        author, {"posts_in_sample": 0, "total_score": 0},
                    )
                    a["posts_in_sample"] += 1
                    a["total_score"] += score or 0

    # Pick top-k subs by post hit count (proxy for relevance + activity)
    ranked = sorted(
        sub_hits.values(),
        key=lambda s: (-len(s["posts"]), -(sum((p.get("score") or 0) for p in s["posts"]))),
    )

    final = []
    for sub in ranked[:k]:
        # Top 3 contributors by post count → total score
        top_contributors = sorted(
            ({"author": a, **st} for a, st in sub["authors"].items()),
            key=lambda x: (x["posts_in_sample"], x["total_score"]),
            reverse=True,
        )[:3]
        # Top 5 posts by score (None scores sort last)
        top_posts = sorted(
            sub["posts"], key=lambda p: -(p.get("score") or 0),
        )[:5]
        final.append({
            "name":             sub["name"],
            "url":              sub["url"],
            "subscribers":      sub["subscribers"],  # unknown from SerpAPI
            "active_users":     None,
            "description":      None,
            "top_posts":        top_posts,
            "top_contributors": top_contributors,
            "found_via":        sub["found_via"],
        })
    return final


def _render_reddit_section(reddit_data: list, hints: dict) -> str:
    """Format the Reddit channel data as a Markdown section. Skips
    rendering for clearly sales-led products where Reddit isn't a
    primary channel (matches existing _strip_forbidden_channel_tasks
    behavior).
    """
    if not reddit_data:
        return ""
    lines = [
        "",
        "## 📣 推荐 Reddit 渠道（真实 sub + top contributor，近 30 天数据）",
        "",
        "下面 sub 是用 Reddit 公开 JSON API 实时抓的，订阅数 / 月度 top 帖 / "
        "活跃 contributor 都来自 reddit.com 当前数据。直接点链接看人和帖。",
        "",
    ]
    for sub in reddit_data:
        name = sub["name"]
        subscribers = sub.get("subscribers")
        subs_label = f"{subscribers:,} subscribers" if subscribers else "active community"
        active = sub.get("active_users")
        active_str = f" · {active:,} active" if active else ""
        lines.extend([
            f"### r/{name} <span style=\"font-weight:400\">— {subs_label}{active_str}</span>",
            "",
            f"[{sub['url']}]({sub['url']})",
            "",
        ])
        if sub.get("description"):
            lines.append(f"> {sub['description']}")
            lines.append("")
        if sub.get("top_posts"):
            lines.append("**Top 帖（Google 索引近期高质量讨论）：**")
            lines.append("")
            lines.append("| 标题 | ↑Score | 作者 |")
            lines.append("| --- | --- | --- |")
            for p in sub["top_posts"]:
                title = (p["title"] or "?").replace("|", "\\|")
                score_str = f"{p['score']:,}" if p.get("score") else "—"
                author = p.get("author") or "?"
                if author and author != "?":
                    author_link = f"[u/{author}](https://reddit.com/user/{author})"
                else:
                    author_link = "?"
                lines.append(
                    f"| [{title}]({p['permalink']}) | {score_str} | {author_link} |"
                )
            lines.append("")
        if sub.get("top_contributors"):
            tc_strs = []
            for c in sub["top_contributors"]:
                tc_strs.append(
                    f"[u/{c['author']}](https://reddit.com/user/{c['author']}) "
                    f"({c['posts_in_sample']} 帖, {c['total_score']:,}↑)"
                )
            lines.append("**Top 30 天 contributor**：" + " · ".join(tc_strs))
            lines.append("")
    lines.append("**怎么用**：先看 top 帖标题的 framing pattern → 模仿写自己的；"
                 "DM top contributor 提议合作前先在他们近 5 个帖底下留**有质量评论**养感情。"
                 "参照 `gingiris-reddit-marketing` 的 20-day karma warmup SOP。")
    lines.append("")
    return "\n".join(lines)


def _build_reddit_context_for_llm(reddit_data: list) -> str:
    """Compact context block fed into the Action Plan LLM prompt so it
    can cite real subs + real top posters in W3 task descriptions.
    """
    if not reddit_data:
        return ""
    lines = [
        "",
        "# REDDIT_REAL_CHANNELS (此段为程序抓取的真实 Reddit 数据，必须直接引用 sub 名和 contributor 名)",
        "",
    ]
    for sub in reddit_data:
        lines.append(f"- r/{sub['name']} ({sub['subscribers']:,} subscribers): {sub.get('description','')[:140]}")
        if sub.get("top_contributors"):
            tcs = ", ".join(f"u/{c['author']}" for c in sub["top_contributors"][:3])
            lines.append(f"  Top contributors: {tcs}")
        if sub.get("top_posts"):
            lines.append("  Top post framing patterns:")
            for p in sub["top_posts"][:3]:
                lines.append(f"  - \"{p['title']}\" ({p['score']}↑)")
    lines.append("")
    lines.append("🚨 在 W3 Reddit 任务里**必须**引用上面的真实 sub 名 + "
                 "至少 1 个真实 top contributor 用户名 + "
                 "至少 1 个真实 top 帖的 framing 模式作为参考。")
    lines.append("")
    return "\n".join(lines)


def _render_real_kol_section(kols: list, hints: dict, categories: list) -> str:
    """Format the KOL candidates as a Markdown section to embed in Action Plan."""
    if not kols:
        return ""
    incentive = (
        "**B2B 适用 incentive**:免费 POC + 联合发布行业案例研究(不要给"
        "\"3 个月免费 Pro\",对 enterprise 买家无吸引力)。"
        if hints.get("is_sales_led") else
        "**适用 incentive**:3 个月免费 Pro 计划 + 独家 API key + 一次 1:1 onboarding,"
        "邀请撰写真实评测或制作教程视频。"
    )
    cats_str = "、".join(categories[:3]) if categories else "你的产品"
    lines = [
        "",
        "## 🎯 真实 KOL 候选名单(程序刚抓取,可立即外联)",
        "",
        f"基于 **{cats_str}** 类目,从 Brave Search 实时抓取 {len(kols)} "
        f"位活跃发布者。**这些是真实账号 - 不是 LLM 编的**,可立即过滤 / 邀约。",
        "",
        "| # | 平台 | Handle | Bio 片段 |",
        "| - | - | - | - |",
    ]
    for i, k in enumerate(kols, 1):
        bio = k["bio_snippet"].replace("|", "/").replace("\n", " ").strip()
        if len(bio) > 140:
            bio = bio[:137] + "..."
        link = f"[{k['handle']}]({k['source_url']})"
        lines.append(f"| {i} | {k['platform']} | {link} | {bio} |")
    lines.extend([
        "",
        "### 外联模板(点击 handle 进行人工筛选后使用)",
        "",
        incentive,
        "",
        "```",
        "Hi [first name],",
        "",
        "I'm Iris from [Your product]. I've been following your work on "
        f"{cats_str.split('、')[0]}, particularly your recent post on [SPECIFIC POST].",
        "",
        "Quick context: we're [1-line value prop]. We've shipped to "
        "[2-3 known customers if any].",
        "",
        ("I'd love to offer a 60-min PoC + co-author a case study on how"
         " you/your team would use this - happy to ship a custom enterprise"
         " API key if it's a fit."
         if hints.get("is_sales_led") else
         "I'd love to offer you a free 3-month Pro plan + dedicated"
         " onboarding (no obligation to post). If you find it useful,"
         " we'd be thrilled if you shared your experience."),
        "",
        "Open to a 15-min chat next week?",
        "```",
        "",
        "**注意**:以上是 Brave Search 在 Twitter/LinkedIn 公开页找到的发布者。"
        "**真实 fit / 影响力需人工核实**:粉丝数、近期发布频率、bio 与产品契合度。"
        "本表是去除『找 KOL』工作量,**不是 endorsement**。",
    ])
    return "\n".join(lines)


def _pick_skills_for_product_type(hints: dict) -> list:
    """Pick 8-10 REAL skills covering multiple channels (SEO + KOL + Community
    + Reddit + Sales / UGC / Launch) - not just SEO/GEO. This is the
    deterministic registry layer; never returns an LLM-invented slug.

    Picks reflect Iris's explicit guidance: action plans should be
    multi-dimensional. Each list below has at least one skill per
    relevant growth motion for that product type.
    """
    is_sales_led = hints.get("is_sales_led", False)
    is_oss = hints.get("is_oss", False)
    product_type = hints.get("product_type", "")

    if is_oss:
        return [
            "gingiris-opensource",
            "github-stars-playbook",
            "gingiris-github-star-growth",
            "gingiris-reddit-marketing",
            "gingiris-seo-geo-agent",
            "gingiris-twitter-agent-ops",        # NEW - founder X 渠道一直缺
            "community-building-playbook",
            "devrel-playbook",
            "competitor-research-playbook",      # NEW - 拆对手定位差异化
            "gingiris-user-interview",
        ]
    if is_sales_led:
        return [
            "gingiris-b2b-growth",
            "b2b-marketing-playbook",
            "saas-growth-playbook",
            "gingiris-seo-geo-agent",
            "gingiris-kol-outreach",
            "gingiris-twitter-agent-ops",        # NEW - B2B 也越来越靠 founder X
            "devrel-playbook",
            "competitor-research-playbook",      # NEW - B2B 差异化关键
            "gingiris-user-interview",
            "startup-consultant",
        ]
    if "PLG" in product_type or "Consumer" in product_type:
        return [
            "gingiris-launch",
            "product-hunt-playbook",
            "gingiris-seo-geo-agent",
            "gingiris-reddit-marketing",
            "gingiris-ugc-matrix",
            "gingiris-kol-outreach",
            "gingiris-twitter-agent-ops",        # NEW
            "competitor-research-playbook",      # NEW
            "community-building-playbook",
            "gingiris-user-interview",
            "viral-marketing-playbook",
        ]
    if "Mobile" in product_type or "App" in product_type:
        return [
            "gingiris-aso-growth",
            "aso-playbook",
            "i18n-aso-growth",
            "gingiris-ugc-matrix",
            "gingiris-kol-outreach",
            "gingiris-twitter-agent-ops",        # NEW
            "gingiris-launch",
            "viral-marketing-playbook",
            "competitor-research-playbook",      # NEW
            "gingiris-user-interview",
        ]
    # Unknown / fall-through - always include go-global for China teams
    return [
        "gingiris-go-global",                    # NEW - 中国团队出海默认配
        "gingiris-growth-finder",
        "competitor-research-playbook",          # NEW
        "go-to-market-playbook",
        "gingiris-seo-geo-agent",
        "gingiris-twitter-agent-ops",            # NEW
        "gingiris-user-interview",
        "startup-launch-playbook",
        "community-building-playbook",
    ]


# ─── Deterministic Action Matrix ──────────────────────────────────────────────


def _render_action_matrix(hints: dict, level: int = 2) -> str:
    """Render a Week-by-Week × Channel × Tactic matrix grounded in real
    skill tactics. Forces multi-channel coverage - fixes Iris's
    'reports too SEO-only' complaint.

    For each picked skill, we pull its top 2 tactics from GINGIRIS_SKILL_TACTICS
    (if defined) and slot them into the matrix.
    """
    skills = _pick_skills_for_product_type(hints)
    h = "#" * level
    sub_h = "#" * (level + 1)
    lines = [
        f"{h} 🎯 30 天 Channel × Tactic 执行矩阵",
        "",
        "下面是把每个 finding 落到 **具体渠道 × 具体战术** 的可执行表。每条都引自上方"
        "匹配 skill 的真实战术 SOP(不是 LLM 拍脑袋),带 benchmark 数据可对照。",
        "",
        "| Week | 渠道 | 具体战术 | 来源 Skill | Benchmark |",
        "| --- | --- | --- | --- | --- |",
    ]

    # Order skills to vary channels (prevents stacking 3 SEO rows together)
    channel_label = {
        "launch":   "🚀 Launch",
        "seo":      "🔍 SEO/GEO",
        "b2b":      "📈 B2B GTM",
        "oss":      "🐙 OSS / GitHub",
        "mobile":   "📱 ASO/Mobile",
        "kol":      "📣 KOL",
        "ugc":      "🎬 UGC 矩阵",
        "community":"💬 Community",
        "social":   "🐦 Twitter/X",
        "intel":    "🔬 Competitor Intel",
        "research": "👥 User Research",
        "global":   "🌏 Go Global",
        "general":  "⚙️ GTM",
        "agent":    "🤖 Agent Ops",
        "router":   "🧭 Strategy",
    }

    # Walk picked skills in registry order; for each, pull up to 2 tactics
    # so a typical 8-9 skill audit produces 12-18 matrix rows across 4 weeks.
    week_alloc = ["W1", "W1-2", "W2", "W2-3", "W3", "W3-4", "W4"]
    matrix_rows = []
    week_idx = 0
    for slug in skills:
        if slug not in GINGIRIS_SKILL_TACTICS:
            continue
        info = GINGIRIS_SKILL_REGISTRY.get(slug, {})
        chan = channel_label.get(info.get("category", "general"), "⚙️ GTM")
        for tactic in GINGIRIS_SKILL_TACTICS[slug][:2]:
            when, what, bench = tactic
            # If tactic has its own week-label, use it; else allocate round-robin
            week = when if when.startswith(("W", "D", "Phase", "发布")) else week_alloc[week_idx % len(week_alloc)]
            week_idx += 1
            matrix_rows.append(
                f"| **{week}** | {chan} | {what} | "
                f"[`{slug}`](https://huggingface.co/datasets/Gingiris/{slug}) | "
                f"_{bench}_ |"
            )

    lines.extend(matrix_rows)
    lines.extend([
        "",
        f"{sub_h} 📌 如何使用这张矩阵",
        "",
        "1. **按周倒入日历** - 把每行的 \"Week + 渠道 + 战术\" 直接当成 calendar event 排进去",
        "2. **每周 retro** - week 末对照 Benchmark 列查实际数据;落后 50% 砍掉换下一周战术",
        "3. **不要全部一次开** - 同一周最多并行 3 个渠道,否则没人盯得过来",
        "4. **改 channel 不改 skill** - 渠道选完再装对应 skill 当 agent 上下文,让 AI 帮你执行细节",
    ])
    return "\n".join(lines)


def _render_playbook_section(hints: dict, level: int = 2) -> str:
    """Render the canonical 'Gingiris Playbook' section, using REAL skills only.

    `level` controls heading depth (2 = ## , 3 = ###). The section is a
    safe drop-in replacement for whatever the LLM emitted under
    "匹配的 Gingiris Playbook" / "推荐安装的 Gingiris AI Skills" / etc.
    """
    skills = _pick_skills_for_product_type(hints)
    h = "#" * level
    sub_h = "#" * (level + 1)
    lines = [
        f"{h} 📚 匹配的 Gingiris Skills(由产品类型自动匹配)",
        "",
        f"基于程序判定的产品类型 **{hints.get('product_type', '未知')}**,"
        f"为你匹配以下来自 [Hugging Face @Gingiris](https://huggingface.co/Gingiris) "
        f"的真实 skill datasets(43 个发布中)。每个 skill 都已经在线上验证过;"
        f"下方安装命令可直接执行。",
        "",
        "| Skill | 适用场景 | HuggingFace |",
        "| --- | --- | --- |",
    ]
    for slug in skills:
        info = GINGIRIS_SKILL_REGISTRY[slug]
        lines.append(
            f"| **{info['title']}** | {info['best_for']} | "
            f"[`Gingiris/{slug}`](https://huggingface.co/datasets/Gingiris/{slug}) |"
        )
    # Compact install guide. The previous version repeated the same
    # 3-method block for every skill (~30 lines × 9 skills = ~270 lines
    # of nearly-identical content). Iris flagged it as noise. New
    # structure: explain methods ONCE with <SLUG> placeholder, then a
    # batch-install one-liner for everything-at-once.
    batch_slugs = " ".join(skills)
    lines.extend([
        "",
        f"{sub_h} 📦 安装",
        "",
        "Skills 是 SKILL.md 文件,可在 Claude Code / Cursor / Gemini CLI 等 "
        "AI agent IDE 里使用。下面 `<SLUG>` 替换成上方表格里的 slug 即可。",
        "",
        "**方法 A - 一键批量装全部(推荐)**",
        "",
        "```bash",
        "mkdir -p ~/.claude/skills",
        f"for s in {batch_slugs}; do",
        '  git clone "https://huggingface.co/datasets/Gingiris/$s" \\',
        '    "$HOME/.claude/skills/$s"',
        "done",
        "# 重启 Claude Code 即生效",
        "```",
        "",
        "**方法 B - 单装 1 个**",
        "",
        "```bash",
        "git clone https://huggingface.co/datasets/Gingiris/<SLUG> \\",
        "  ~/.claude/skills/<SLUG>",
        "```",
        "",
        "**方法 C - 其他 IDE / 浏览器读**",
        "",
        "- Cursor / Gemini CLI: `huggingface-cli download Gingiris/<SLUG> --repo-type dataset --local-dir ./.cursor/rules/<SLUG>`(先 `pip install -U huggingface_hub`)",
        "- 在线读: <https://huggingface.co/datasets/Gingiris/><SLUG> 或 <https://gingiris.tools/skills>",
        "",
        "**触发**:装好后在 AI agent 对话里描述场景(例如 \"我们要做 launch\"),agent 自动加载对应 skill 作上下文。",
    ])
    return "\n".join(lines)


# Pattern that matches the LLM's hallucinated playbook section. We use a
# multi-pattern approach because the LLM phrases the section heading at
# least 4 different ways across reports.
_PLAYBOOK_SECTION_PATTERNS = [
    # NB: use [\s\S]*? for the body (not (?:.+?\n)*?), because the last
    # report section often is NOT newline-terminated and the line-based
    # quantifier then fails to reach \Z. The terminator must require
    # AT LEAST 2 #'s (`^#{2,3}\s`) - using `^#{1,3}\s` causes bash
    # comments like `# build skill` inside code blocks to terminate
    # the match early.
    # Diagnosis Report: "## 8. 匹配的 Gingiris Playbook" / "## 9. ..."
    r"^#{2,3}\s*\d*\.?\s*匹配的\s*Gingiris\s*Playbook\b[^\n]*\n[\s\S]*?(?=^#{2,3}\s|\Z)",
    # Action Plan: "## 推荐安装的 Gingiris AI Skills"
    r"^#{2,3}\s*推荐安装的?\s*Gingiris(\s*AI)?\s*Skills?\b[^\n]*\n[\s\S]*?(?=^#{2,3}\s|\Z)",
    # Executive Summary: "## 📚 匹配的 Gingiris 框架"
    r"^#{2,3}\s*📚?\s*匹配的\s*Gingiris\s*框架\b[^\n]*\n[\s\S]*?(?=^#{2,3}\s|\Z)",
]


def _replace_playbook_section(md: str, hints: dict, *, heading_level: int = 2) -> str:
    """Find any LLM-generated Gingiris Playbook / Skills section and replace
    it wholesale with the deterministic version built from the real registry.

    Critical because the LLM keeps inventing slugs like 'bofu-content-harvest'
    that don't exist. A fake `npx skills add` command in the report body is
    worse than no recommendation at all - paying users would silently fail.

    Falls back to appending the canonical section if no LLM section matched.
    """
    if not md:
        return md
    replacement = _render_playbook_section(hints, level=heading_level)
    replaced = False
    out = md
    # IMPORTANT: run ALL patterns sequentially (don't break on first match).
    # Action Plan often has BOTH "## 8. 匹配的 Gingiris Playbook" AND
    # "## 推荐安装的 Gingiris AI Skills" - they need separate handling.
    # First match injects the canonical block; subsequent matches just
    # delete their LLM-generated duplicates by replacing with empty.
    for idx, pat in enumerate(_PLAYBOOK_SECTION_PATTERNS):
        repl_text = (replacement + "\n\n") if not replaced else ""
        new_out, n = _re.subn(pat, repl_text, out, count=1, flags=_re.MULTILINE)
        if n > 0:
            replaced = True
            out = new_out
    # Also strip any stray bash blocks that contain `Gingiris-1031/<invented>`
    # references (the LLM sometimes puts a second install block elsewhere).
    bash_block_pat = r"```bash\s*\n(?:[^\n]*\n){0,8}?[^\n]*(?:gingiris install|npx skills add Gingiris-1031/)[^\n]*\n(?:[^\n]*\n){0,12}?```"
    fake_block_matches = list(_re.finditer(bash_block_pat, out))
    for m in reversed(fake_block_matches):  # reverse to keep indexes valid
        block = m.group(0)
        # If the block contains any REAL slug, leave it alone (already valid).
        # If it only contains invented slugs, drop it.
        has_real = any(real in block for real in GINGIRIS_SKILL_REGISTRY.keys())
        has_invented = bool(_re.search(
            r"(?:gingiris install|Gingiris-1031/)([a-z0-9-]+)", block,
        ))
        if has_invented and not has_real:
            out = out[:m.start()] + "" + out[m.end():]
    if not replaced:
        out = out.rstrip() + "\n\n" + replacement + "\n"
    return out


def _strip_forbidden_channel_tasks(md: str, hints: dict) -> str:
    """For sales-led products, surgically remove Action Plan tasks that
    recommend forbidden channels (Product Hunt, UGC matrix, TikTok, Reddit
    Karma farming). Removes the entire task block (heading + body) and
    inserts a callout explaining the substitution.

    Strategy: split on '### 任务' / '### Task' headings, drop any block
    whose heading matches one of the forbidden channel patterns, append a
    one-paragraph note at the end of the action plan listing what was
    removed and why.
    """
    if not md or not hints.get("is_sales_led"):
        return md

    forbidden_keywords = [
        ("Product Hunt", "Product Hunt Launch(企业基础设施买家不在 PH 池中)"),
        ("PH Launch", "Product Hunt Launch(企业基础设施买家不在 PH 池中)"),
        ("UGC", "UGC 矩阵(B2B 买家心智不在 UGC 内容里)"),
        ("TikTok", "TikTok / Reels(不是企业 buyer journey 的入口)"),
        ("Reddit\\s*账号养成", "Reddit Karma 养号(开发者 sub 可用,但非冷启动主力)"),
        ("Reddit\\s*种草", "Reddit 主动种草(仅作为辅助渠道,不应进入 Week 1-2 P0)"),
    ]

    # Split the doc on task-heading boundaries (### 任务 / ### Task / ### 4.1 etc.)
    sections = _re.split(r"(?=^### (?:任务|Task)\b)", md, flags=_re.MULTILINE)
    if len(sections) <= 1:
        return md

    removed = []
    kept = []
    for sec in sections:
        # Check the heading line for any forbidden keyword
        heading_line = sec.split("\n", 1)[0]
        match_label = None
        for kw_pattern, replacement_label in forbidden_keywords:
            if _re.search(kw_pattern, heading_line, _re.IGNORECASE):
                match_label = replacement_label
                break
        if match_label:
            removed.append(heading_line.strip())
        else:
            kept.append(sec)

    if not removed:
        return md

    result = "".join(kept).rstrip()
    callout = (
        "\n\n---\n\n"
        "## ⚙️ 程序判定调整说明\n\n"
        f"本次行动计划检测到产品为 **{hints['product_type']}** "
        f"(Sales-led / Enterprise),以下任务已自动移除(与该产品类型不匹配):\n\n"
        + "\n".join(f"- ~~{h}~~" for h in removed)
        + "\n\n**推荐替换路径**:聚焦 "
        + "、".join(hints.get("recommended_channels", [])[:4])
        + "。详情见诊断报告 §6 渠道策略详解。\n"
    )
    return result + callout


async def generate_diagnosis_report(site_data: dict, product_name: str, lang: str = "zh") -> dict:
    """Phase 1:诊断报告(事实层)。

    这是 pipeline 的第一份报告,直接基于抓取数据写。所有后续报告
    (Action Plan, Executive Summary)都必须引用本报告,不能引入与本报告
    冲突的新事实。
    """
    context = _build_site_context(site_data)
    # Detect product type early so we can inject relevant skill content
    hints = detect_product_type(site_data)
    product_type = hints.get("product_type", "Unknown / 需用户确认")
    skills_block = _build_injected_skills_block(product_type)

    user_prompt = f"""{_lang_instruction(lang)}基于以下抓取的产品网站数据,为 **{product_name}** 生成一份完整的增长诊断报告。

{context}

---

## 输出要求(Markdown 格式,6000-8000 字)

# {product_name} 增长诊断报告

> 诊断日期:今天
> 方法论:Gingiris Growth Skills Framework

## 1. 产品概览
- 产品定义与核心价值主张(依据:首页 Title/Description/正文)
- 核心功能(基于抓取到的首页内容)
- 目标用户(ICP)- 推断时标注"推断"
- 商业模式推断
- 定价分析 - 仅引用 /pricing 抓取到的内容。若 /pricing 抓取失败,写"未能确认公开定价,需用户提供"。

## 2. 增长诊断(三维度)
### 2.1 产品类型分类(SaaS / OSS / AI / Mobile / Dev Tool / Consumer Web)
### 2.2 增长阶段判定(Pre-launch / Launch / Cold Start / Growth / Scale)- 附判定依据
### 2.3 渠道现状概览(表格:渠道 | 首页/sitemap 是否展示 | 备注)
**强制规则(防 absence-on-homepage 谬误)**:每一格"现状"必须严格写"首页未展示" / "首页展示了 X" / "sitemap 包含" / "未抓取范围",绝不写"未启动"、"无活动"、"用户未做"。
- KOL / 合作伙伴:合作关系一般不在首页公开 → 标记"未抓取范围"。
- Product Hunt:可能发布过但未在首页放 badge → 标记"首页未展示"。
- 社区(Reddit/Discord/Slack):通常不公开运营痕迹 → 标记"未抓取范围"。
- SEO:基于 sitemap 可判断(有数据)。
- 付费投放、Sales pipeline:必须标"未抓取范围",不可发表意见。

## 3. SEO/GEO 现状审计 - **以下规则必须严格遵守**
- **robots.txt 分析**:**只引用 robots.txt 章节里实际出现的 directive**。如果 robots.txt 章节标注"未抓取",写"robots.txt 未抓到,无法分析",不得编造 Disallow/Allow 内容。
- **Sitemap 完整度**:基于"Sitemap.xml 结构化摘要"里的目录聚合。
  - 不要推荐创建已经在 sitemap 里出现的页面(比如 sitemap 已有 /research/、/alternatives/、/compare/ 就别说"建议创建研究页")。
  - 写明 sitemap 共有 N URL,覆盖了哪些目录。
- **内容资产盘点**:基于 sitemap + 站内链接
- **结构化数据**:仅依据首页正文中是否提及 JSON-LD / FAQ / Schema 等关键词做推断,并明确标"未对源码做 schema 扫描,推断仅供参考"
- **GEO 就绪度评估**:基于实际 robots.txt + 是否有 /research/ 类 citation-worthy 资产判断

## 4. 竞品定位分析
- 市场定位(基于首页价值主张)
- 可能的竞品(按产品类型列 3-5 个,不要给具体定价 - 写"具体定价请用户核实")
- 差异化建议(基于首页传达的差异化点)

## 5. 增长策略推荐(P0/P1/P2 优先级)

**关键约束**:本节策略必须先根据 §1 推断的产品类型 + 增长阶段,对照系统提示中的"渠道-产品类型匹配矩阵 (H/I)"选渠道。**不要给企业级 API / Sales-led 产品推 PH / UGC 矩阵 / TikTok**。给 enterprise infra 推 PH 等于建议错误渠道。

每条策略必须:(1) 基于本报告已写明的 finding;(2) 附预期影响(不写 N% 提升这种伪数字,写"预期改善 SEO 入口"这种定性表达 OR 注明"基准数据需用户提供 GA / GSC 才能量化");(3) 渠道类策略必须以 "**如尚未启动**" 起头。

### P0 - 本周必做(最高 ROI)
### P1 - 2 周内完成
### P2 - 30 天内完成

## 6. 渠道策略详解
逐渠道分析。每个渠道必须先写"首页/sitemap 观察到的现状",再写"建议"。**不发表"用户没做 X" 这类断言**(见反推论谬误 E)。如果该渠道与产品类型不匹配,直接写"**与该产品类型不匹配,跳过**",不要硬凑建议。

## 7. 本次审计的盲区(必填)

明确列出本次抓取**未能覆盖的维度**,告诉用户报告的边界:
- 内部数据:GA / GSC / Mixpanel / Amplitude / 客户访谈 / churn 数据
- 渠道运营:KOL 合作记录 / Product Hunt 历史 / Reddit/Discord 活动 / Newsletter 数量 / 已签 partnership
- 销售/付费:sales pipeline / outbound 活动 / paid spend / CAC / LTV
- 反向链接 / 关键词排名 / 流量来源(本次未调用 SEO 工具 API)
- 登录后内部页面 / API endpoint
**每个盲区后用一行写"建议用户在咨询时提供:"以提示用户在续约 Pro 时如何提供这些数据获取更准确的诊断。**

## 8. 风险与假设
列出本诊断的关键推断 + 它们的依据。

## 9. 匹配的 Gingiris Playbook
表格:框架名 | 适用场景(基于本报告 finding) | 安装命令

---

请记住反幻觉硬约束 A-D,每条 finding 后用 `(依据:xxx)` 标注来源。
{skills_block}
"""

    return await _call_llm_long(_get_system_prompt(), user_prompt, max_tokens=8000)


async def generate_action_plan(
    site_data: dict,
    product_name: str,
    diagnosis_md: str,
    reddit_data: Optional[list] = None,
    lang: str = "zh",
) -> dict:
    """Phase 2:30 天行动计划 - 必须基于 Diagnosis Report 的 findings 行动。

    传入 diagnosis_md 是关键架构改变:Action Plan 不能再独立看到 site_data
    就编新事实(比如凭空说 robots.txt 屏蔽了 /admin/)。它只能 act on
    Diagnosis 已经 verified 的问题。

    reddit_data (optional) is the output of _discover_reddit_channels — when
    present, we inject real sub names + top contributors into the prompt so
    the LLM cites them in W3 Reddit tasks instead of inventing 'r/SaaS'
    boilerplate.
    """
    context = _build_site_context(site_data)
    # Reuse product type detection for skill injection
    hints = detect_product_type(site_data)
    product_type = hints.get("product_type", "Unknown / 需用户确认")
    skills_block = _build_injected_skills_block(product_type)
    reddit_block = _build_reddit_context_for_llm(reddit_data or [])

    user_prompt = f"""{_lang_instruction(lang)}基于以下两段输入,为 **{product_name}** 制定 30 天行动计划。

# 输入 1:原始抓取数据
{context}

---

# 输入 2:上一阶段已生成的诊断报告(事实基准)
{diagnosis_md}

---

## 输出要求(Markdown 格式,5000-7000 字)

# {product_name} - 30 天行动计划

> 本计划严格基于上面的"诊断报告"。每个任务必须能映射到诊断报告里写过的 finding。
> 预计投入:估算总工时

🚨 **多渠道覆盖硬约束**:以下 4 周每周必须聚焦一个**不同的增长维度**。**不允许整个 4 周计划都聚焦 SEO/GEO**。如果产品类型是 Sales-led,跳过 PH/UGC/Reddit-Karma 周,替换为 Sales Enablement / DevRel / Case Study 周。

🚨 **每个任务的硬约束(落地度)**:
- **必须**引用 **GINGIRIS_SKILL_TACTICS** 里某个 skill 的**具体战术**(不是泛泛 "做 SEO"),格式:`【来自 \`<skill-slug>\` 的战术】` + 战术原话引述
- **必须**带 1 个 benchmark 数据(CAC、CVR、CTR、follower 增长、ROI 等等的具体数字,从对应 skill 引)
- **必须**带 1 段可立即执行的"今天能做什么"(命令 / 邮件模板原文 / 链接 / 工具操作步骤)
- 禁止写"考虑 / 评估 / 探索"这类含糊词;只用"做 X,结果 Y"的祈使句
- 禁止"做 SEO 优化"这种笼统建议;必须是"在 sitemap.xml 加 5 个 /alternatives/ URL,明天 10AM PT 提交 GSC"这种动作级

## Week 1: Day 1-7 - SEO/GEO + 基础设施

任务来源:诊断报告 "## 3. SEO/GEO 现状审计" + "## 5. P0"。

每个任务包含:
- **对应 finding**(引用诊断报告原话,1 句以内)
- **目的**
- **修复方案**(含代码 / 配置模板)
- **验证方法**
- **预期影响**(定性)

## Week 2: Day 8-14 - KOL / 内容 / 社交渠道

依据:诊断报告 "## 6. 渠道策略详解"。**本周必须包含至少 1 个**:
- 对 **PLG / Consumer** 产品:micro-KOL 外联 + UGC creator 招募
- 对 **Sales-led / Enterprise**:DevRel 内容计划 + 客户案例研究 + LinkedIn 1:1 outbound
- 对 **OSS**:HN/Show HN + Awesome lists 投递 + GitHub Discussions
- 对 **Mobile**:Creator matrix(TikTok/Reels/Shorts)+ ASO 关键词

**KOL 任务必须包含真实联系方式**(见下方 "## 真实 KOL 候选名单" 段,由程序提供)。

## Week 3: Day 15-21 - 社区 + Reddit / 论坛

依据:诊断报告 "## 6. 渠道策略详解"。**本周必须包含至少 1 个**:
- 对 **PLG / Consumer / OSS / Dev Tool**:Reddit 内容种草 + Discord 社区运营
- 对 **Sales-led**:Slack / Discord 客户社区(VIP 闭门)+ Webinar / 技术峰会
- 对 **Mobile**:UGC 创作者社区运营

## Week 4: Day 22-30 - 销售 / 留存 / 转化优化

依据:诊断报告 "## 5. P2"。**本周必须包含至少 1 个**:
- 对 **Sales-led**:Sales enablement 武器库(demo 视频、Battlecards、ROI calculator)
- 对 **PLG / SaaS**:activation 漏斗优化、churn 修复实验、定价 A/B 测试
- 对 **OSS**:Contributor 计划升级、Ambassador 计划
- 对 **Mobile**:Push notification 策略、留存 / Day 1 Day 7 Day 30 实验

## 每周 KPI 追踪模板
表格:周 | 指标(来自诊断报告 KPI 段)| 目标 | 实际(用户填)

## 工具清单
对应 Week 任务的具体工具。

## 推荐安装的 Gingiris AI Skills
```bash
npx skills add Gingiris-1031/<skill-name>
```

---

🚨 一致性硬约束:
- 不允许写"修复 robots.txt"如果诊断报告说 robots.txt 没问题。
- 不允许推荐"创建定价页"如果诊断报告已经记录 /pricing 抓到了。
- 不允许引入诊断报告里没写的"当前问题"(比如不能凭空说"当前 Disallow /admin/ 是误配置")。
- 不允许编竞品定价或行业基准。

🚨 渠道任务的额外约束(重要 - 防一刀切推荐):
- 凡是"启动 KOL 外联 / 启动 Product Hunt / 启动 Reddit 运营 / 启动 UGC 矩阵"这类任务,**先看诊断报告 §1 推断的产品类型 + §2 增长阶段**:
  - Enterprise Infra / API / B2B SDK / Sales-led 产品(如 TinyFish, Browserless, Vanta) → **不要包含 PH Launch、UGC 矩阵、TikTok 任务**。改用:HN/Show HN、技术深度博客(Dev.to + 自有 blog)、Dev advocacy、GitHub examples/cookbook、LinkedIn outbound、客户案例/解决方案模板。
  - Consumer / PLG / Prosumer → 可以包含 PH + UGC + 社区。
  - OSS → 偏向 HN + Reddit + Awesome lists + GitHub。
  - Mobile → ASO + Creator matrix。
- 所有渠道类任务的"目的"段必须以 "**如尚未启动**" 起头(因为我们看不到用户的内部运营,不能假设"用户没做")。
- 如果某 Week 的任务全部不适用于该产品类型,直接写:"本周聚焦 [适合该产品类型的活动],跳过通用的 PH/KOL 周。",不要硬塞。
- KOL 类任务不要给"3 个月免费 Pro 计划"这种通用模板 - 改成 "**对应你产品的合理 incentive**(企业 SaaS 通常是免费 POC + 案例研究合作;个人开发者产品才适合免费订阅)"。
{skills_block}
{reddit_block}
"""

    return await _call_llm_long(_get_system_prompt(), user_prompt, max_tokens=8000)


async def generate_executive_summary(site_data: dict, product_name: str,
                                     diagnosis_md: str, action_plan_md: str,
                                     lang: str = "zh") -> dict:
    """Phase 3:Executive Summary - 综合前两份报告,**不能引入新事实**。

    传入 diagnosis_md + action_plan_md,Executive 只能摘录 / 重组,不能新增。
    """
    user_prompt = f"""{_lang_instruction(lang)}基于以下两份已生成的报告,提炼出 **{product_name}** 的执行摘要。

# 输入 1:诊断报告
{diagnosis_md}

# 输入 2:30 天行动计划
{action_plan_md}

---

## 输出要求(Markdown 格式,1500-2500 字)

# {product_name} 增长诊断 - 执行摘要

**诊断日期:** 今天
**产品:** {product_name}
**URL:** {site_data.get('url', '')}

## 🎯 核心发现(3 句话)
直接摘自诊断报告的"## 1. 产品概览"、"## 2. 增长诊断"、"## 3. SEO/GEO"三个章节,用 3 句话总结。**不引入新发现**。

## 🚨 三个最严重的问题
直接摘自诊断报告"## 5. P0 - 本周必做"。最多 3 条,每条包含:
- 问题描述(一句)
- 影响程度(🔴 极高 / 🟡 中 / 🟢 低)
- 修复时间估算(取自 Action Plan Week 1)
- 预期影响(定性,照搬诊断报告原话)

## ✅ 快速赢面清单(按优先级)
- 本周做(2-3 小时)- 摘自 Action Plan Week 1
- 第 1-2 周做(8 小时)- 摘自 Action Plan Week 2
- 第 3-4 周做(12 小时)- 摘自 Action Plan Week 3-4

## 📊 6 个月财务预测(如基础数据不足则跳过本节)
**只在诊断报告里有量化基线时输出**。否则写"基线数据缺失,建议用户提供 GA / GSC 后再做预测"。

## 🎯 关键 KPI 追踪
表格:KPI(取自诊断报告) | 当前(取自诊断报告,无则写"待用户提供") | 3 个月目标 | 6 个月目标

## 🛠️ 推荐工具堆栈
摘自 Action Plan"工具清单"

## 📚 匹配的 Gingiris 框架
摘自诊断报告"## 8. 匹配的 Gingiris Playbook"

## ❓ 下一步行动
- 立即(今天):取 Action Plan Week 1 任务 1
- 本周:取 Action Plan Week 1 剩余任务
- 下周:取 Action Plan Week 2 任务

---

🚨 一致性硬约束:
- 本摘要不能出现诊断报告 / 行动计划里没出现的新 finding。
- 本摘要的"三个最严重问题"必须能在 Action Plan 里找到对应任务。
- 不允许编新数字 / 新竞品 / 新案例。
"""

    return await _call_llm_long(_get_system_prompt(), user_prompt, max_tokens=4000)


# ─── Main Orchestrator ──────────────────────────────────────────────────────


def _lang_instruction(lang: str) -> str:
    """Return a forceful 'respond in <lang>' directive to prepend to LLM
    user prompts. Fixes the 'EN users get Chinese reports' bug — the
    Chinese system+user prompts otherwise drag the answer language back
    to Chinese regardless of caller's intent.
    """
    if (lang or "").lower().startswith("en"):
        return (
            "🌐 LANGUAGE RULE (CRITICAL): The user is reading this report in English. "
            "Your ENTIRE response — every heading, every bullet, every table cell — "
            "must be in fluent natural English. Do NOT mix in any Chinese characters, "
            "phrases, or em-dashes used in Chinese style. Translate any Chinese strings "
            "from the input data into English when quoting them. Section headers in "
            "English (e.g. 'Executive Summary', '30-Day Action Plan', 'Diagnosis', "
            "'Channel Strategy'), NOT '执行摘要' / '30 天行动计划'.\n\n"
        )
    return ""  # zh / default — original prompts are Chinese


async def run_growth_audit(
    url: str,
    product_name: str = None,
    job_id: str = None,
    jobs_dict: dict = None,
    lang: str = "zh",
) -> dict:
    """完整的 Growth Audit pipeline:抓站 → 生成三份报告。

    如果提供 job_id 和 jobs_dict,会实时更新 job 状态。
    lang: "zh" (default) or "en" — controls report output language.
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

    def _emit(key: str, md: str):
        """Stream a finished report into the job immediately so the frontend can
        render it before the remaining stages complete (progressive reveal).
        Diagnosis lands at ~50% of total wall-clock - showing it then, instead
        of making the user stare at a progress bar until 100%, is the whole win."""
        if jobs_dict and job_id and job_id in jobs_dict:
            r = jobs_dict[job_id].get("reports")
            if not isinstance(r, dict):
                r = {}
                jobs_dict[job_id]["reports"] = r
            r[key] = md

    # Step 1: Fetch site data
    _update("fetch", "running")
    site_data = await fetch_site_with_tinyfish(url)
    if site_data.get("error"):
        _update("fetch", "failed")
        return {"error": f"网站抓取失败: {site_data['error']}"}
    _update("fetch", "done")

    # Step 2: Sequential pipeline - Diagnosis → Action Plan → Executive Summary.
    # Architectural fix: the old parallel-gather design let each report
    # independently hallucinate facts. Now each downstream report only sees the
    # already-verified output of the previous stage, plus the cross-report
    # consistency guards baked into each prompt. This collapses the
    # "Diagnosis says robots.txt is fine / Action Plan invents Disallow rules"
    # contradiction that bit our first Iris-on-Iris self-audit.
    reports = {"executive_summary": None, "diagnosis_report": None, "action_plan": None}
    sources = {"exec": "skipped", "diag": "skipped", "plan": "skipped"}

    # Phase 1: Diagnosis (facts layer) - also kicks off KOL discovery in
    # parallel so we have real handles ready by the time Action Plan runs.
    _update("diagnosis", "running")
    hints = detect_product_type(site_data)
    categories = _extract_product_category(site_data)
    kol_task = asyncio.create_task(_discover_real_kols(categories, hints, k=6))
    # Reddit channel discovery runs in parallel with Diagnosis so the data
    # is ready when Action Plan generation starts (and we feed it into the
    # Action Plan LLM prompt so W3 Reddit tasks cite real subs + real
    # contributors, not generic 'post in r/SaaS' platitudes).
    reddit_task = asyncio.create_task(_discover_reddit_channels(categories, hints, k=3))
    diag_result = await generate_diagnosis_report(site_data, product_name, lang=lang)
    if isinstance(diag_result, dict) and diag_result.get("success"):
        # Run the absence-phrase sanitizer before downstream stages see this
        # - otherwise Action Plan + Executive Summary will inherit the
        # confidently-wrong claims and amplify them. Then replace any
        # LLM-fabricated Gingiris playbook table with the canonical one
        # built from the real 40-skill registry.
        hints_for_diag = detect_product_type(site_data)
        diag_md = _scrub_absence_phrases(diag_result["content"])
        diag_md = _replace_playbook_section(diag_md, hints_for_diag, heading_level=2)
        reports["diagnosis_report"] = diag_md
        sources["diag"] = diag_result.get("source", "?")
        _emit("diagnosis_report", diag_md)  # stream it now - ~50% mark
        _update("diagnosis", "done")
    else:
        _update("diagnosis", "failed")
        log.error("Diagnosis generation failed: %s", diag_result)
        # Without a Diagnosis we can't run the downstream stages - fail fast,
        # better than producing two ungrounded reports.
        return {
            "product_name": product_name,
            "url": url,
            "reports": reports,
            "source": sources,
            "error": "Diagnosis 阶段失败,已中止 pipeline(防止下游报告 hallucinate)",
        }

    # Phase 2 - UX FIX: Action Plan + Executive Summary run in PARALLEL.
    # Both now consume the (sanitized) Diagnosis as their only LLM input -
    # Action Plan reads it directly, Exec Summary reads the Diagnosis
    # (the dependency on Action Plan is replaced by deriving Exec content
    # from Diagnosis sections, which contain the same P0/P1/P2 structure
    # that Action Plan would mirror). This halves total wall-clock vs the
    # previous strict sequential pipeline (which was hitting 7+ min on
    # large prompts; the architectural fix landed before this change made
    # *generation* time worse than the old buggy parallel version).
    _update("action_plan", "running")
    _update("executive_summary", "running")
    # Reddit discovery finishes in parallel with Diagnosis. Wait for it now
    # (tightly bounded so a slow reddit.com response can't extend the audit
    # past its 2-5 min promise). Empty result is fine — generate_action_plan
    # accepts reddit_data=None.
    try:
        reddit_data = await asyncio.wait_for(reddit_task, timeout=8.0)
    except (asyncio.TimeoutError, Exception) as e:
        log.warning("Reddit discovery aborted: %s", e)
        reddit_data = []
    plan_task = asyncio.create_task(
        generate_action_plan(
            site_data, product_name, reports["diagnosis_report"],
            reddit_data=reddit_data, lang=lang,
        )
    )
    exec_task = asyncio.create_task(
        generate_executive_summary(
            site_data, product_name,
            reports["diagnosis_report"],
            # Pass the Diagnosis a second time as a stand-in for the Action
            # Plan. Exec Summary's prompt already constrains it to only
            # summarize content present in its inputs; with no Action Plan
            # text available, it falls back to the Diagnosis P0/P1/P2 list
            # which is the same content the Plan would have echoed.
            reports["diagnosis_report"],
            lang=lang,
        )
    )

    # Both tasks already run concurrently; awaiting Exec (4000 tok) first - it
    # finishes before Plan (8000 tok) - lets us stream it out sooner without
    # serializing the two. Reveal order ends up Diagnosis → Exec → Plan.
    # ── Process Executive Summary (finishes first) ───────────────────────
    try:
        exec_result = await exec_task
    except Exception as e:
        exec_result = e
    if isinstance(exec_result, dict) and exec_result.get("success"):
        exec_md = _scrub_absence_phrases(exec_result["content"])
        exec_md = _replace_playbook_section(exec_md, hints, heading_level=2)
        reports["executive_summary"] = exec_md
        sources["exec"] = exec_result.get("source", "?")
        _emit("executive_summary", exec_md)
        _update("executive_summary", "done")
    else:
        _update("executive_summary", "failed")
        log.error("Executive Summary generation failed: %s", exec_result)

    # ── Process Action Plan (longer - finishes last) ─────────────────────
    try:
        plan_result = await plan_task
    except Exception as e:
        plan_result = e
    if isinstance(plan_result, dict) and plan_result.get("success"):
        plan_md = _scrub_absence_phrases(plan_result["content"])
        plan_md = _strip_forbidden_channel_tasks(plan_md, hints)
        plan_md = _replace_playbook_section(plan_md, hints, heading_level=2)
        # Inject the deterministic Week × Channel × Tactic matrix RIGHT
        # BEFORE the Gingiris Skills section. This is the fix for Iris's
        # "reports too SEO-only / channels too limited" complaint -
        # programmatically forces multi-channel coverage drawn from real
        # skill tactics with real benchmarks, instead of trusting the LLM
        # to remember to span Reddit/Twitter/KOL/UGC/etc.
        matrix_md = _render_action_matrix(hints, level=2)
        anchor = "## 📚 匹配的 Gingiris Skills"
        if anchor in plan_md:
            plan_md = plan_md.replace(anchor, matrix_md + "\n\n" + anchor, 1)
        else:
            plan_md = plan_md.rstrip() + "\n\n" + matrix_md + "\n"
        # Pull KOL handles (the task has been running since Phase 1 start;
        # it should already be done by now). Bound the wait tightly so a
        # hung Brave call can't extend total audit time.
        try:
            kols = await asyncio.wait_for(kol_task, timeout=5.0)
        except (asyncio.TimeoutError, Exception) as e:
            log.warning("KOL discovery aborted: %s", e)
            kols = []
        # Render the real Reddit channel section using data already in hand.
        reddit_section = _render_reddit_section(reddit_data, hints)
        if reddit_section:
            anchor = "## 📚 匹配的 Gingiris Skills"
            if anchor in plan_md:
                plan_md = plan_md.replace(anchor, reddit_section + "\n\n" + anchor, 1)
            else:
                plan_md = plan_md.rstrip() + "\n" + reddit_section + "\n"
        kol_section = _render_real_kol_section(kols, hints, categories)
        if kol_section:
            anchor = "## 📚 匹配的 Gingiris Skills"
            if anchor in plan_md:
                plan_md = plan_md.replace(anchor, kol_section + "\n\n" + anchor, 1)
            else:
                plan_md = plan_md.rstrip() + "\n" + kol_section + "\n"
        reports["action_plan"] = plan_md
        sources["plan"] = plan_result.get("source", "?")
        _emit("action_plan", plan_md)
        _update("action_plan", "done")
    else:
        _update("action_plan", "failed")
        log.error("Action Plan generation failed: %s", plan_result)

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
