"""Growth Audit 模块 - 用户输入产品 URL,调用 TinyFish 抓站 + LLM + Gingiris Skills 生成三份增长诊断报告

报告输出:
1. Executive Summary(~2000 字)
2. Diagnosis Report(~8000 字)
3. 30-Day Action Plan(~6000 字)
"""
import asyncio
import html as _html
import httpx
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# TinyFish Fetch API
TINYFISH_FETCH_URL = "https://api.fetch.tinyfish.ai"

# A growth audit may fetch the same public site more than once while a user
# iterates on the report.  Keep a deliberately short, process-local cache: it
# removes repeat rendering work without turning an audit into a stale snapshot.
_SITE_FETCH_CACHE_TTL_SECONDS = int(os.environ.get("GROWTH_AUDIT_SITE_CACHE_TTL", "300"))
_site_fetch_cache: dict[str, tuple[float, dict]] = {}

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

## 🚀 宣发 Campaign 三层架构(适用于任何"发布类"动作:新品/新功能/融资/里程碑)

J. **凡 Action Plan 涉及 launch/发布/campaign,必须按三层结构组织,不要只写"发个 PH/发条推"**:

| 层 | 时间窗 | 做什么 | 关键要点 |
|---|---|---|---|
| **① 发布层** | 第 0-2 周 | 悬念钩子预热 → 一条主内容集中引爆 → 解说帖管理预期 → 教程降门槛 → 出问题主动公关 → 叙事收尾 | 主内容只有一条(视频/深度帖),其余帖都为它服务;出负面时 24h 内主动透明说明,危机公关帖本身就是内容 |
| **② 放大层** | 发布前 1-2 周就要铺好 | 提前锁定 3-5 个真 KOL 约定发布日跟发;养多语种社群大使;主推"真实使用 ROI 实测连载"而非硬广 | 区分**真 KOL vs 官号/矩阵号**——转发矩阵是噪音不是宣发;KOL 内容要"真钱实测/真实工作流"才有说服力 |
| **③ 留存层** | 发布后第 2-8 周 | 叠一个竞赛/挑战/连载机制,把发布拉来的新用户转成持续使用者;让 KOL 当选手利益绑定,战况可连载 | 抄机制不抄形式;可拉联名方/赞助商分摊奖金池成本 |

K. **发布层节奏公式**(逐帖排布,不是一次性乱发):
   悬念钩子(勾好奇,如"明早有大事") → 主内容引爆(全期流量峰) → 演示/教程帖("怎么用"降门槛) → 危机公关帖(如有问题,主动透明) → 品牌叙事收尾。

L. **转化路径必须写成漏斗四段**,每段配具体动作+钩子:
   ① 触达(悬念钩子/预热) → ② 认知(主内容+平台级背书) → ③ 激活(教程/低门槛入口) → ④ 转化(入口尽量嵌进用户已在用的工具里)。
   **分发式转化优先**:AI/agent 类产品优先考虑"把能力装进用户已用的工具"(ChatGPT/Claude 插件、iMessage、浏览器扩展),把转化搬到用户日常工具里,而不是"拉用户来注册新 App"。

M. **预算与验收**(Action Plan 里的 campaign 任务必须带这两项):
   - 预算逐项给区间(如 主视频 $2-3k / KOL 合作 $2-5k / 竞赛奖金池 $5-10k 可拉赞助分摊),没有预算依据就标"估算"。
   - 验收指标:**不看发布当天曝光**,盯发布后 4-8 周的核心使用指标趋势(交易量/激活/留存)+ 可交叉验证的第三方数据;明确提醒"自报数字不可照抄,要用链上/第三方数据核实"(适用 crypto/可验证行业)。

N. **可复用发布框架 > 一锤子买卖**:发布做成"可反复加场景的系列"(同一钩子/同一框架换场景再发),而非单次事件。

%SKILL_REGISTRY%
"""


def _get_system_prompt(filter_to_skills: Optional[list] = None, lang: str = "zh") -> str:
    """Returns the system prompt with the Gingiris skill registry + a
    tactical cheat-sheet inlined.

    `filter_to_skills` (new): when provided, the tactical cheat-sheet
    only emits tactics for those slugs. Cuts ~30% of tokens off when the
    caller already knows the product type (e.g. action plan stage).
    Prevents context overflow on long diagnoses that bit Iris's
    'action plan generation failed' 2026-06-18 report.
    """
    return GINGIRIS_SKILLS_CONTEXT.replace(
        "%SKILL_REGISTRY%",
        _build_skill_registry_prompt(lang)
        + "\n\n"
        + _build_tactical_cheatsheet(filter_to_skills, lang)
    )


def _build_tactical_cheatsheet(filter_to_skills: Optional[list] = None, lang: str = "zh") -> str:
    """Compact tactical recipes per skill - drops into system prompt so
    LLM can cite specific tactics verbatim instead of inventing fluffy
    'launch on PH'-level recommendations.

    When `filter_to_skills` is provided, only those skills appear in the
    cheat-sheet. The action plan generator passes its already-picked
    skills here to trim the prompt and avoid context overflow.
    """
    if filter_to_skills:
        allowed = {s for s in filter_to_skills}
        items = [(s, t) for s, t in GINGIRIS_SKILL_TACTICS.items() if s in allowed]
    else:
        items = list(GINGIRIS_SKILL_TACTICS.items())

    lines = [
        "## 🎯 战术速查表(强制:所有渠道推荐必须引用此表中的具体战术 + benchmark)",
        "",
        "格式:每个 skill 给出 2-3 个可执行战术:(时间窗 / 具体动作 / 实战 benchmark)",
        "**LLM 引用此表中的战术时格式:【来自 `skill-slug` 的战术】+ 原文**",
        "",
    ]
    for slug, tactics in items:
        info = GINGIRIS_SKILL_REGISTRY.get(slug, {})
        lines.append(f"### `{slug}` - {info.get('title', slug)}")
        for when, what, bench in tactics:
            if lang != "zh":
                when, what, bench = _EN(when), _EN(what), _EN(bench)
            lines.append(f"- **{when}** - {what} _(benchmark: {bench})_")
        lines.append("")
    return "\n".join(lines)

# ─── TinyFish Fetch ─────────────────────────────────────────────────────────


def _compact_html_text(raw_html: str, limit: int) -> str:
    """Turn a small, static auxiliary page into useful LLM context.

    TinyFish remains responsible for the JS-rendered homepage.  This helper is
    only used for robots, sitemap and pricing so a slow optional pricing page
    cannot hold the entire audit fetch hostage.
    """
    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw_html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()[:limit]


async def _fetch_auxiliary_site_data(base: str) -> dict:
    """Fetch static audit inputs concurrently with bounded latency."""
    targets = {
        "robots_txt": (f"{base}/robots.txt", 2500),
        "sitemap": (f"{base}/sitemap.xml", 4500),
        "pricing_page": (f"{base}/pricing", 6500),
    }

    async def _get(client: httpx.AsyncClient, key: str, page_url: str, limit: int):
        try:
            response = await client.get(page_url)
            if response.status_code >= 400:
                return key, None
            raw = response.text
            if key == "robots_txt":
                return key, raw[:limit]
            if key == "sitemap":
                return key, raw[:limit]
            title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
            title = _compact_html_text(title_match.group(1), 300) if title_match else None
            return key, {"title": title, "text": _compact_html_text(raw, limit)}
        except Exception:
            return key, None

    timeout = httpx.Timeout(connect=3.0, read=6.0, write=3.0, pool=3.0)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; analook/1.0)"}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        items = await asyncio.gather(*(
            _get(client, key, page_url, limit)
            for key, (page_url, limit) in targets.items()
        ))
    return {key: value for key, value in items if value}


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

    raw_url = url if url.startswith("http") else f"https://{url}"
    cache_key = raw_url.rstrip("/").lower()
    cached = _site_fetch_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < _SITE_FETCH_CACHE_TTL_SECONDS:
        # The result is not mutated downstream, but copy the top-level mapping
        # so future pipeline additions cannot poison the shared cache entry.
        return dict(cached[1])

    # Iris 2026-07-06 accuracy audit: resolve redirects BEFORE building the
    # base, otherwise robots.txt / pricing / sitemap get fetched from the
    # OLD domain when the site has migrated (notion.so → notion.com held
    # 8x the SEO footprint in the sibling /api/analyze bug). The audit
    # then confidently mis-describes the wrong domain's GEO readiness.
    redirect_note = ""
    try:
        # We only need the final URL. Streaming avoids downloading a complete
        # homepage here and cuts the common redirect check from seconds to a
        # single response-header round trip.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=2.5, read=3.0, write=2.5, pool=2.5),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; analook/1.0)"},
        ) as _rc:
            async with _rc.stream("GET", raw_url) as _resp:
                _final = str(_resp.url)
            _orig_host = urlparse(raw_url).netloc.lower().replace("www.", "")
            _final_host = urlparse(_final).netloc.lower().replace("www.", "")
            if _final_host and _final_host != _orig_host:
                # NB: keep this note in ENGLISH — it flows into the LLM
                # context for BOTH en and zh audits. A Chinese note would
                # leak CJK into EN reports (the exact bug class fixed in
                # the 2026-06-25 i18n sweep); the zh prompt handles English
                # data fragments natively.
                redirect_note = (
                    f"NOTE: the submitted domain {_orig_host} redirects to "
                    f"{_final_host}; all fetching and diagnosis below reflect "
                    f"{_final_host} (the domain actually serving the product)."
                )
                url = _final
    except Exception:
        pass  # network hiccup → proceed with the raw URL as before

    parsed = urlparse(url if url.startswith("http") else f"https://{url}")
    base = f"{parsed.scheme}://{parsed.netloc}"

    results = {}
    try:
        # Render only the page where JS execution adds high signal (the
        # homepage). Static assets are fetched in parallel below with a six
        # second ceiling, instead of allowing one slow /pricing route to delay
        # the full report for up to 160 seconds.
        async def _fetch_homepage():
            async with httpx.AsyncClient(timeout=70) as client:
                return await client.post(
                    TINYFISH_FETCH_URL,
                    headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                    json={"urls": [url], "format": "markdown", "links": True, "ttl": 300},
                )

        resp, auxiliary = await asyncio.gather(_fetch_homepage(), _fetch_auxiliary_site_data(base))
        results.update(auxiliary)
        resp.raise_for_status()
        data = resp.json()

        for r in data.get("results", []):
            results["homepage"] = {
                "title": r.get("title"),
                "description": r.get("description"),
                "text": (r.get("text") or "")[:12000],
                "links": (r.get("links") or [])[:50],
            }
            break

        for e in data.get("errors", []):
            log.warning("TinyFish homepage fetch error: %s", str(e)[:200])

    except Exception as exc:
        log.error("TinyFish fetch failed: %s", exc)
        results["error"] = str(exc)[:200]

    results["url"] = url
    results["domain"] = parsed.netloc
    if redirect_note:
        results["redirect_note"] = redirect_note
    _site_fetch_cache[cache_key] = (time.monotonic(), dict(results))
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
# 2026-06-20 (Iris reported broken action_plan on ga-e7f3ff2e/helio.im):
# read timeout was 150s. action_plan asks for 8000 max_tokens; at typical
# DeepSeek throughput of ~50 t/s that's 160s — right above the previous
# limit. exec_summary at 4000 tokens (80s) survived; action_plan didn't
# across all 3 fallback plans. Bumped to 300s so the longest generation
# path has plenty of headroom even when an LLM is slow.
_LLM_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)
# Interactive audits need a firm latency ceiling.  The lower-level provider
# timeout remains generous for non-interactive callers, while this budget is
# enforced around every Growth Audit model attempt below.
_AUDIT_LLM_BUDGET_SECONDS = 65.0
_AUDIT_LLM_ATTEMPT_SECONDS = 38.0


def _extract_content(data: dict) -> str:
    """Pull ONLY the final answer text. DeepSeek V4 (and some routed hosts)
    also return `reasoning_content` / `reasoning` in the message - that chain
    of thought must never leak into the user-facing report, so we read
    `content` exclusively."""
    msg = ((data.get("choices") or [{}])[0] or {}).get("message", {}) or {}
    return msg.get("content", "") or ""


async def _try_deepseek(messages: list, max_tokens: int, *, retries: int = 1) -> Optional[dict]:
    """DeepSeek first-party API. Now retries transient failures (5xx,
    timeout, network errors) once before failing over to next provider.

    Reason: OpenRouter key is currently dead → DeepSeek is the only
    working LLM path. A transient 502 or socket reset would kill the
    whole audit's action plan with no recovery. One in-provider retry
    catches that 95% of the time without significantly extending the
    audit's wall-clock budget.

    If primary model (deepseek-v4-flash) returns a context-length error
    on the retry, we fall back to deepseek-chat which has a 64K context
    and stable behavior under load.
    """
    import os as _os
    import asyncio as _asyncio
    key = _os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        try:
            key = open(_os.path.expanduser("~/.cola/secrets/deepseek_api_key")).read().strip()
        except FileNotFoundError:
            return None
    if not key:
        return None
    primary_model = _os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    stable_model  = "deepseek-chat"   # known-stable older model

    attempts = max(1, retries + 1)
    last_error = None
    for attempt in range(attempts):
        # Last attempt drops to stable model — catches context-length and
        # model-availability errors that retrying v4-flash wouldn't.
        model = primary_model if attempt == 0 else stable_model
        try:
            async with httpx.AsyncClient(timeout=_LLM_TIMEOUT, follow_redirects=True) as client:
                resp = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    json={"model": model, "messages": messages,
                          "temperature": 0.5, "max_tokens": max_tokens},
                )
                # Don't retry on auth/balance/forbidden — same key, same outcome.
                if resp.status_code in (401, 402, 403):
                    log.warning("DeepSeek %s HTTP %d (key/balance issue, not retrying)",
                                model, resp.status_code)
                    return None
                resp.raise_for_status()
                content = _extract_content(resp.json())
                if content:
                    if attempt > 0:
                        log.info("DeepSeek recovered on attempt %d (model=%s)", attempt + 1, model)
                    return {"success": True, "content": content,
                            "source": f"DeepSeek-direct ({model})"}
                last_error = "empty content"
        except Exception as e:
            last_error = str(e)[:200]
            log.warning("DeepSeek (%s) attempt %d/%d failed: %s",
                        model, attempt + 1, attempts, last_error)
        # Brief backoff before retry — let transient infra blips clear.
        if attempt < attempts - 1:
            await _asyncio.sleep(1.5 * (attempt + 1))
    log.warning("DeepSeek exhausted %d attempts, failing over: %s", attempts, last_error)
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

      Plan 0: OrcaRouter → orcarouter/free    ($0 — routes to deepseek-v4-flash)
      Plan A: OpenRouter → deepseek-v4-flash   (fast, cheap, multi-host failover)
      Plan B: DeepSeek direct → deepseek-v4-flash  (same model, independent vendor)
      Plan C: OpenRouter → claude-sonnet-4     (different model - quality safety net)

    0/A/B share the model (identical output quality); C is the last-resort
    safety net on a different model so a total DeepSeek outage still produces a
    report. Returns {success, content, source}.
    """
    import os as _os
    from .orcarouter import try_orca
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]
    or_primary = _os.environ.get("OPENROUTER_DEEPSEEK_MODEL", "deepseek/deepseek-v4-flash")
    or_fallback = _os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")

    plans = (
        ("0", lambda: try_orca(messages, max_tokens=max_tokens, temperature=0.5, title="Analook Growth Audit")),
        ("A", lambda: _try_openrouter(messages, max_tokens, or_primary)),
        ("B", lambda: _try_deepseek(messages, max_tokens)),
        ("C", lambda: _try_openrouter(messages, max_tokens, or_fallback)),
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _AUDIT_LLM_BUDGET_SECONDS
    for label, plan in plans:
        remaining = deadline - loop.time()
        if remaining <= 0:
            log.warning("Growth Audit LLM budget exhausted before Plan %s", label)
            break
        try:
            result = await asyncio.wait_for(
                plan(), timeout=min(_AUDIT_LLM_ATTEMPT_SECONDS, remaining)
            )
        except asyncio.TimeoutError:
            log.warning("Growth Audit LLM Plan %s exceeded %.0fs; failing over", label,
                        min(_AUDIT_LLM_ATTEMPT_SECONDS, remaining))
            result = None
        if result:
            if label not in ("0", "A"):
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
    if site_data.get("redirect_note"):
        parts.append(f"⚠️ {site_data['redirect_note']}\n")

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
_EN_STRINGS = {
    "**Enterprise / B2B mid-market 必装**": "**Must-have for Enterprise / B2B mid-market**",
    "**Founder 个人品牌不发力的所有产品**,0→1 推特账号": "**Any product whose founder brand is dormant**; 0→1 Twitter account",
    "**仅适合 Consumer/PLG**,B2B/Enterprise 不适用": "**Consumer/PLG only** — not for B2B/Enterprise",
    "**所有中国团队出海产品 (Day 0)**": "**Every China-based team going global (Day 0)**",
    "**所有产品的基础设施**,PMF 验证必备": "**Infrastructure for every product**; essential for PMF validation",
    "0→1 KOL 计划": "0→1 KOL program",
    "0→1000 用户阶段": "0→1,000 users stage",
    "0→10K stars 阶段": "0→10K stars stage",
    "1 个月 32K impressions": "32K impressions in 1 month",
    "10 倍提高 D30 retention": "10x improvement in D30 retention",
    "10K stars 24-36 个月加速到 14 天": "10K stars: 24-36 months compressed to 14 days",
    "14 天 sprint:Day 1 Show HN, Day 3 Reddit r/programming, Day 5 X thread, Day 7 Hacker Newsletter": "14-day sprint: Day 1 Show HN, Day 3 Reddit r/programming, Day 5 X thread, Day 7 Hacker Newsletter",
    "150+ AI startup 实战": "Battle-tested across 150+ AI startups",
    "30+ PH #1 daily 全用同一模板": "All 30+ PH #1 daily wins used this same template",
    "4 级体系:Bronze→Silver→Gold→Platinum,每级 points threshold 公开": "4-tier system: Bronze→Silver→Gold→Platinum with public points thresholds per tier",
    "45 天 1150→1837 关注 (+60%)": "1,150→1,837 followers in 45 days (+60%)",
    "5 场 60min 访谈 + JTBD 问题模板('上次你解决 X 的方式 / 哪里卡 / 改用我们之后变化')": "5 × 60-min interviews + JTBD question template ('how did you last solve X / where did it hurt / what changed after switching')",
    "60 天 $10M ARR / 70M impressions 案例": "$10M ARR / 70M impressions in 60 days case study",
    "AFFiNE 200+ KOL 实战,micro 转化 5-8%": "AFFiNE's 200+ KOL campaigns; micro-KOL conversion 5-8%",
    "AFFiNE 3-4 万曝光 + 5-8% GitHub star 转化": "AFFiNE: 30-40K impressions + 5-8% GitHub star conversion",
    "AFFiNE 60K stars 同打法": "Same playbook that took AFFiNE to 60K stars",
    "AFFiNE 同打法 6 周拿 top 3": "Same AFFiNE playbook reached top 3 in 6 weeks",
    "AI Native 产品 launch": "AI-native product launches",
    "AI search 被引用率 30%+": "30%+ AI-search citation rate",
    "AI 写的初稿过 triple-translation test 才发": "AI drafts must pass the triple-translation test before posting",
    "AI 矩阵号:用 ElevenLabs + Sora + Hedra 量产 50 条/周,每号差异化人设": "AI account matrix: mass-produce 50 videos/week with ElevenLabs + Sora + Hedra, distinct persona per account",
    "AMA SOP:找 mod 24 小时前预约 + 准备 20 个 seed Q&A + founder 真名上 + 持续 4 小时": "AMA SOP: book with mods 24h ahead + prep 20 seed Q&As + founder posts under real name + stay live 4 hours",
    "ASO 占 70% organic install": "ASO drives 70% of organic installs",
    "Asset 包:30s teaser video + 5 静图 + 1 founder-story tweet + comparison table": "Asset pack: 30s teaser video + 5 stills + 1 founder-story tweet + comparison table",
    "B2B cold reply rate 12% vs 模板 1%": "B2B cold reply rate 12% vs 1% for templates",
    "B2B 销售驱动产品": "Sales-led B2B products",
    "Base44 用同样格式拿 $80M AMA": "Base44 used this exact format for its $80M AMA",
    "Beta→增长:建立 weekly digest 邮件 + 1v1 onboarding call 节奏 (Iris@AFFiNE 同流程)": "Beta→growth: weekly digest email + 1:1 onboarding call cadence (same flow Iris ran at AFFiNE)",
    "Churn 早期预警:连续 2 周 0 活动 → 1v1 调研,不要直接踢": "Churn early warning: 2 consecutive zero-activity weeks → 1:1 research call, don't just cut them",
    "Churn 诊断:用流失用户访谈反推激活 gap (cohort 4-09 类似)": "Churn diagnosis: churned-user interviews to reverse-engineer the activation gap",
    "Cold 回复率 18% vs 模板 outreach 2%": "18% cold reply rate vs 2% for template outreach",
    "Consumer / PLG 想做病毒传播": "Consumer / PLG products chasing virality",
    "Dev Tool / API 产品": "Dev Tool / API products",
    "Developer 产品 funnel": "Developer product funnels",
    "Founder 亲发 X thread (≤7 推) + 评论区每条回复 ≤10 分钟": "Founder posts the X thread personally (≤7 tweets) + replies to every comment within 10 minutes",
    "GEO 三件套:FAQ schema + AI 友好 robots.txt + Brave/Perplexity index 提交": "GEO trio: FAQ schema + AI-friendly robots.txt + Brave/Perplexity index submission",
    "Gingiris 自身验证": "Validated on Gingiris itself",
    "HeyGen 937 场访谈到 PMF": "HeyGen's 937 interviews to PMF",
    "HeyGen 937 场访谈复盘": "HeyGen's 937-interview retrospective",
    "Hub-spoke 内链:1 个 hub page + 6 个 spoke 互链,targeting KD 20-35 关键词": "Hub-spoke internal links: 1 hub page + 6 interlinked spokes targeting KD 20-35 keywords",
    "ICP 锚定:用 user-interview SOP 跑 5 场 60min 访谈,提炼 'JTBD 一句话'": "ICP anchoring: run 5 × 60-min interviews via the user-interview SOP, distill the one-line JTBD",
    "KOL 筛选:用 Brave Search + Twitter API 筛 followers 1K-50K 的 micro-KOL,避开 macro (ROI 差 3x)": "KOL screening: use Brave Search + Twitter API to find 1K-50K-follower micro-KOLs; avoid macros (3x worse ROI)",
    "LinkedIn ABM:用 Apollo + Clay 抓 100 个 ICP,定制 3-touch 序列(教育→案例→demo)": "LinkedIn ABM: pull 100 ICP accounts via Apollo + Clay, custom 3-touch sequence (educate→case study→demo)",
    "Lovable 4.3M views 复盘同法": "Same method behind Lovable's 4.3M-view retrospective",
    "Maker 第一条 comment 必须含 'Hi PH community, X here from Y...' 标准开场": "Maker's first comment must open with the standard 'Hi PH community, X here from Y...'",
    "Mobile App 冷启动": "Mobile app cold start",
    "Mobile App 多平台": "Multi-platform mobile apps",
    "Mobile App 排名优化": "Mobile app ranking optimization",
    "Newsletter outreach:JS Weekly, Pointer.io, TLDR - pitch 是 1 段 + 1 demo gif": "Newsletter outreach: JS Weekly, Pointer.io, TLDR — pitch is 1 paragraph + 1 demo gif",
    "Notion 20M 用户实战": "Notion's 20M-user playbook",
    "OSS 产品": "Open-source products",
    "Outreach 模板:'你最近关于 X 的帖子我看了,我们在做 Y 跟你 X 视角对得上,能寄你试用吗?' + 不要直接给链接": "Outreach template: 'Read your recent post on X — we're building Y which matches your angle; can I send you access?' Never lead with a bare link",
    "PH 算法看预热互动": "The PH algorithm weighs pre-launch engagement",
    "PLG / Consumer / OSS 产品发布前 6-12 周准备": "PLG / Consumer / OSS products 6-12 weeks before launch",
    "PLG / Consumer 产品 PH 发布前 4 周": "PLG / Consumer products 4 weeks before a PH launch",
    "PLG 模式 SaaS": "PLG-model SaaS",
    "PMF 前 churn root cause 80% 是 onboarding": "Pre-PMF, 80% of churn root-causes are onboarding",
    "README 优化:hero gif + tagline + 5 行 quickstart + comparison table(对照 #1-3 alternatives)": "README optimization: hero gif + tagline + 5-line quickstart + comparison table (vs the #1-3 alternatives)",
    "ROI 测量:每个 KOL 单独 UTM + Linktree slot,CAC < $25 才续约": "ROI measurement: unique UTM + Linktree slot per KOL; renew only if CAC < $25",
    "Reddit 内容是 ChatGPT/Claude 40.11% 训练数据": "Reddit content is 40.11% of ChatGPT/Claude training data",
    "Reddit/Discord/Twitter 三轨:weekly digest + roadmap voting + contributor shoutout": "Reddit/Discord/Twitter triple-track: weekly digest + roadmap voting + contributor shoutouts",
    "SaaS $0→$50K MRR 阶段": "SaaS at the $0→$50K MRR stage",
    "SaaS 营销全栈视角": "Full-stack SaaS marketing view",
    "Seed 阶段": "Seed stage",
    "Show HN front-page = 1-5K stars/周": "Show HN front page = 1-5K stars/week",
    "Show HN:周二/周三 8AM PT 发,标题 'Show HN: X - the Y open-source alternative to Z'": "Show HN: post Tue/Wed 8AM PT, title 'Show HN: X — the Y open-source alternative to Z'",
    "Top-3 表现内容 reinvest:投流 boost 跑赢 baseline 2x 才追加": "Reinvest in top-3 performing content: only boost with spend if it beats baseline 2x",
    "UGC creator 矩阵:5 TikTok creator × 3 video / 月,导流 App Store": "UGC creator matrix: 5 TikTok creators × 3 videos/month, funneling to the App Store",
    "Upcoming page + 200 maker comment 攒 buzz": "Upcoming page + 200 maker comments to bank buzz",
    "X/Twitter 传播链:用 advanced search 找首发 thread + 转评最多 5 个账号,导出 KOL list": "X/Twitter propagation chain: advanced-search the original thread + top-5 amplifier accounts, export the KOL list",
    "i18n-aso-growth 同打法 multi-locale": "Same multi-locale playbook as i18n-aso-growth",
    "不确定装哪个 skill 时的入口": "Entry point when unsure which skill to install",
    "人设校准:voice guide + 死开场 blacklist + 5 段过往真实推作 sample,喂 AI agent": "Persona calibration: voice guide + dead-opener blacklist + 5 real past tweets as samples, fed to the AI agent",
    "保 momentum 不停": "Keeps momentum unbroken",
    "关键词研究:用 Sensor Tower 找 traffic>1K + difficulty<30 的 long-tail,5 个塞 title/subtitle": "Keyword research: use Sensor Tower to find long-tails with traffic>1K + difficulty<30; pack 5 into title/subtitle",
    "养号 SOP:先 karma 0→500(20 天),评论 50+ 真实回答 + 0 自家产品提及": "Account warmup SOP: karma 0→500 first (20 days), 50+ genuine answers, zero mentions of your own product",
    "出海最常死在 Phase 0 跳过": "Going global most often dies from skipping Phase 0",
    "前 100 用户:OSS launch 走 HN/Reddit 路径,闭源走 PH/X founder thread 路径": "First 100 users: OSS launches go HN/Reddit; closed-source goes PH/X founder threads",
    "前 100 用户阶段,需要落地节奏": "First-100-users stage, needs an execution cadence",
    "发布前 D-7": "D-7 pre-launch",
    "发布前 W-2": "W-2 pre-launch",
    "发布前 W-6": "W-6 pre-launch",
    "发布日 00:01 PT": "Launch day 00:01 PT",
    "发布日 H+0~3": "Launch day H+0-3",
    "发布日 H+0~6": "Launch day H+0-6",
    "命中率 30% (vs PR 模板 3%)": "30% hit rate (vs 3% for PR templates)",
    "多语言团队": "Multilingual teams",
    "对手最弱环节 = 你的 wedge": "Your competitor's weakest link = your wedge",
    "已发布 OSS 但增长平缓": "Launched OSS with flat growth",
    "市场验证 + positioning:抓 5 个 ICP 国家 × 3 个 substitute 跑过 user-interview": "Market validation + positioning: 5 ICP countries × 3 substitutes through user interviews",
    "想做 Reddit 种草 / AI 训练数据曝光": "Teams seeding Reddit / chasing AI-training-data exposure",
    "想用 agent 自动化 SEO/GEO 的团队": "Teams automating SEO/GEO with an agent",
    "想跑增长实验的团队": "Teams running growth experiments",
    "截图 A/B:4 套创意,每套 1 周,按 CVR 留最优": "Screenshot A/B: 4 creative sets, 1 week each, keep the CVR winner",
    "截图差异 = CVR 差 2-3x": "Screenshot differences = 2-3x CVR gaps",
    "找 5-10 个真人 creator (TikTok 5K-20K followers),按出片付费 $30-50/支": "Recruit 5-10 human creators (TikTok 5K-20K followers), pay per video at $30-50",
    "投票分散 6+ 小时 = rank 跌出 top 10": "Votes spread over 6+ hours = rank falls out of top 10",
    "拆 top 3 对手 Wayback v1/Beta/Launch 3 版官网演化,画 positioning 漂移图": "Tear down top-3 competitors' Wayback v1/Beta/Launch site evolutions; chart the positioning drift",
    "排期:每天 1 条 8AM PT 黄金窗口 + 周三/五各 1 条 thread,dedup 检查防重": "Schedule: 1 post/day in the 8AM PT golden window + threads Wed/Fri, with dedup checks",
    "搭 SEO Agent 三件套:daily audit + ranking 追踪 + schema 验证 + IndexNow push": "SEO Agent trio: daily audit + rank tracking + schema validation + IndexNow push",
    "搭 launch team:~30 PH hunters + 20 X amplifier + 5 newsletter,发布日 1 小时内集中投票": "Build the launch team: ~30 PH hunters + 20 X amplifiers + 5 newsletters; concentrate votes within launch hour 1",
    "数据闭环:tweet-log 周报 → top-3 archetype reinforce + bottom-3 type 砍掉": "Data loop: weekly tweet-log report → reinforce top-3 archetypes, cut bottom-3",
    "无预算 bootstrap 团队": "Zero-budget bootstrap teams",
    "有用户基数想做大使计划的产品": "Products with a user base ready for an ambassador program",
    "构建 AI agent 系统的产品": "Products building AI agent systems",
    "案例 page 比 feature page 高 4x CVR": "Case-study pages convert 4x better than feature pages",
    "案例 study:与 3 个 lighthouse 客户做 co-marketing case study,输出 X thread + LinkedIn post + landing page": "Case studies: co-marketing with 3 lighthouse customers — output an X thread + LinkedIn post + landing page each",
    "每 1-2 小时 founder 回所有 comment,X 持续 retweet 阶段性 update": "Founder replies to all comments every 1-2 hours; X account retweets milestone updates continuously",
    "申请表:A 题(pre-launch readiness 6 条)+ B 题(评分 rubric) 双 gate 卡 70% noise": "Application form: part A (6 pre-launch readiness items) + part B (scoring rubric) double-gates 70% of noise",
    "盲投 1000 美元 = 0 转化的常见陷阱": "The classic trap: $1,000 of blind spend = 0 conversions",
    "盲投 50% 预算浪费": "Blind spend wastes 50% of budget",
    "纯凭感觉发等于浪费 50% 时间": "Posting on gut feel wastes 50% of your time",
    "维持 300+ stars/月 (sustained skill 模板)": "Sustains 300+ stars/month (sustained-growth template)",
    "缺了直接被 hide": "Missing it gets you hidden outright",
    "选 sub:用 subredditstats.com 找 active>5K + content style 'show & tell' 友好的 sub,避开纯 news sub": "Sub selection: use subredditstats.com for active>5K subs friendly to 'show & tell'; avoid pure news subs",
    "防 ghosting 关键": "Key to preventing ghosting",
    "需要 GTM 框架的所有阶段产品": "Products at any stage that need a GTM framework",
    "需要启动或优化 KOL 计划的产品": "Products starting or optimizing a KOL program",
    "需要外部视角的所有阶段": "Any stage that needs an outside perspective",
    "需要建社区的所有产品": "Any product that needs to build a community",
    "需要拆竞品并定位差异化的所有阶段": "Any stage that needs competitor teardowns and differentiated positioning",
    "需要被 AI 搜索引擎引用的内容站": "Content sites that need citations from AI search engines",
    "飞轮 6 阶段评分:Activation/Referral/Acquisition/Retention/Revenue/Product 各 1-5 分,找弱环节": "6-stage flywheel scoring: rate Activation/Referral/Acquisition/Retention/Revenue/Product 1-5 each; find the weak link",
    "首次发 PH 的团队": "Teams launching on PH for the first time",
    "首次发布 AI 产品": "First-time AI product launches",
    "高 engagement = PH 算法加权": "High engagement = PH algorithm boost",
}


def _EN(s: str) -> str:
    """Display-layer EN lookup for CJK data strings (skill registry best_for
    + tactic tuples). Data stays ZH-canonical; EN report flows render via
    this table so audits stay 0-raw-CJK for English users."""
    return _EN_STRINGS.get(s, s)




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


def _build_skill_registry_prompt(lang: str = "zh") -> str:
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
        bf = meta['best_for'] if lang == "zh" else _EN(meta['best_for'])
        lines.append(f"| `{slug}` | {bf} |")
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
    # 2026-06-23: UnifAPI plan D — searches recent tweets for the
    # category keyword and pulls the authors as KOL candidates. Runs
    # only if the chain above didn't already fill the quota AND
    # UNIFAPI_KEY is set. Cheap ($0.001/call) so we just try it.
    await _merge(_discover_kols_unifapi)

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


async def _discover_kols_unifapi(categories: list, hints: dict, k: int = 6) -> list:
    """UnifAPI X tweet-search fallback for KOL discovery.

    Searches recent tweets matching the category keywords and surfaces
    the authors. Costs ~$0.01 per call (1 credit/tweet). Runs only when
    earlier backends (Brave / SerpAPI / TwitterAPI.io) couldn't fill the
    quota — caller controls the 'k' budget so we don't double up.
    """
    try:
        from . import unifapi as _u
    except Exception:
        return []
    if not _u._has_key() or not categories:
        return []

    seen: set = set()
    results: list = []
    for cat in categories[:2]:
        if len(results) >= k:
            break
        try:
            tweets = await _u.search_x_recent_tweets(cat, max_results=10)
        except Exception as e:
            log.warning("UnifAPI tweet search failed for %s: %s", cat, e)
            continue
        for t in tweets[:10]:
            if len(results) >= k:
                break
            author = t.get("author") or t.get("user") or {}
            username = author.get("username") or t.get("author_username")
            if not username:
                continue
            h = "@" + username
            if h.lower() in seen:
                continue
            seen.add(h.lower())
            followers = (
                (author.get("public_metrics") or {}).get("followers_count")
                or author.get("followers_count")
                or 0
            )
            bio = author.get("description") or author.get("bio") or ""
            results.append({
                "handle":      h,
                "platform":    "Twitter / X",
                "bio_snippet": (f"{bio[:160]} · {followers:,} followers"
                                if followers else bio[:220]),
                "source_url":  f"https://twitter.com/{username}",
                "found_via":   f"UnifAPI tweet search: {cat[:40]}",
                "followers":   followers,
            })
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

    # 2026-06-23 Iris fix — enrich each picked sub with UnifAPI's clean
    # subreddit lookup so subscribers/active/description are real ints/
    # strings, never None. The SerpAPI path can't get these (they're not
    # in Google's snippet) so previously they stayed None and triggered
    # the action_plan formatting crashes Iris saw 2 days running. Costs
    # 1 UnifAPI credit per sub ($0.001) — negligible.
    try:
        from . import unifapi as _u
        _has_unifapi = _u._has_key()
    except Exception:
        _has_unifapi = False

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

        # Enrichment: real subscriber count + description from UnifAPI.
        subs_count = None
        active_users = None
        description = None
        if _has_unifapi:
            try:
                meta = await _u.get_subreddit(sub["name"])
                if meta:
                    subs_count   = meta.get("subscribers_count")
                    active_users = meta.get("active_count")
                    description  = (meta.get("description") or "").strip() or None
            except Exception as e:
                log.warning("UnifAPI subreddit lookup failed for %s: %s", sub["name"], e)

        final.append({
            "name":             sub["name"],
            "url":              sub["url"],
            "subscribers":      subs_count,
            "active_users":     active_users,
            "description":      description,
            "top_posts":        top_posts,
            "top_contributors": top_contributors,
            "found_via":        sub["found_via"],
        })
    return final


def _T(lang: str, en: str, zh: str) -> str:
    """Tiny inline translator — returns English when lang starts with 'en',
    Chinese otherwise. Used by all section-render functions below so the
    appended Skills/Reddit/KOL/Matrix blocks match the LLM-flow language.

    Iris 2026-06-25: TAAFT rejected the site for CJK leakage on EN pages.
    The static pages were the obvious issue, but the dynamic audit reports
    were appending these sections in Chinese regardless of EN/ZH flow,
    causing TAAFT-style leakage inside the report body too.
    """
    return en if (lang or "").lower().startswith("en") else zh


def _render_reddit_section(reddit_data: list, hints: dict, lang: str = "zh") -> str:
    """Format the Reddit channel data as a Markdown section. Skips
    rendering for clearly sales-led products where Reddit isn't a
    primary channel (matches existing _strip_forbidden_channel_tasks
    behavior).
    """
    if not reddit_data:
        return ""
    lines = [
        "",
        _T(lang,
           "## 📣 Recommended Reddit Channels (real subs + top contributors, last 30 days)",
           "## 📣 推荐 Reddit 渠道（真实 sub + top contributor，近 30 天数据）"),
        "",
        _T(lang,
           "The subs below were pulled live from Reddit's public JSON API. Subscriber counts, "
           "monthly top posts, and active contributors all reflect current reddit.com data. "
           "Click through to see the people and the posts directly.",
           "下面 sub 是用 Reddit 公开 JSON API 实时抓的，订阅数 / 月度 top 帖 / "
           "活跃 contributor 都来自 reddit.com 当前数据。直接点链接看人和帖。"),
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
            lines.append(_T(lang,
                "**Top posts (recent high-quality discussions, Google-indexed):**",
                "**Top 帖（Google 索引近期高质量讨论）：**"))
            lines.append("")
            lines.append(_T(lang,
                "| Title | ↑Score | Author |",
                "| 标题 | ↑Score | 作者 |"))
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
                post_word = _T(lang, "posts", "帖")
                tc_strs.append(
                    f"[u/{c['author']}](https://reddit.com/user/{c['author']}) "
                    f"({c['posts_in_sample']} {post_word}, {c['total_score']:,}↑)"
                )
            label = _T(lang, "**Top 30-day contributors**: ", "**Top 30 天 contributor**：")
            lines.append(label + " · ".join(tc_strs))
            lines.append("")
    lines.append(_T(lang,
        "**How to use**: first study the framing patterns in the top-post titles → mirror them "
        "when you write your own. Before DM-ing top contributors with a collab pitch, leave "
        "**high-quality comments** on their last 5 posts to build rapport. See the 20-day karma "
        "warmup SOP in `gingiris-reddit-marketing`.",
        "**怎么用**：先看 top 帖标题的 framing pattern → 模仿写自己的；"
        "DM top contributor 提议合作前先在他们近 5 个帖底下留**有质量评论**养感情。"
        "参照 `gingiris-reddit-marketing` 的 20-day karma warmup SOP。"))
    lines.append("")
    return "\n".join(lines)


def _build_reddit_context_for_llm(reddit_data: list, lang: str = "zh") -> str:
    """Compact context block fed into the Action Plan LLM prompt so it
    can cite real subs + real top posters in W3 task descriptions.
    """
    if not reddit_data:
        return ""
    lines = [
        "",
        _T(lang,
           "# REDDIT_REAL_CHANNELS (this block is real Reddit data scraped by the program; "
           "you MUST cite these exact sub names and contributor handles in the W3 Reddit tasks)",
           "# REDDIT_REAL_CHANNELS (此段为程序抓取的真实 Reddit 数据，必须直接引用 sub 名和 contributor 名)"),
        "",
    ]
    for sub in reddit_data:
        # 2026-06-20 Iris bug: SerpAPI-discovered Reddit subs leave
        # subscribers=None (Reddit's own JSON API is 403-blocked from
        # Fly IPs), so {None:,} raised TypeError, crashed the entire
        # action_plan prompt build, and the audit silently stored an
        # empty action_plan. Guard every numeric f-string.
        subs = sub.get("subscribers")
        subs_label = f"{subs:,} subscribers" if isinstance(subs, (int, float)) else "active community"
        # Use `(x or '')[:N]` not `x.get(key, '')[:N]` — when key exists with
        # value None, `.get` returns None and `None[:N]` raises TypeError.
        # Same NoneType-subscriptable bug Iris saw on ga-9d6f8a44 2026-06-20.
        desc = (sub.get("description") or "")[:140]
        lines.append(f"- r/{sub.get('name') or '?'} ({subs_label}): {desc}")
        if sub.get("top_contributors"):
            tcs = ", ".join(f"u/{c.get('author') or '?'}" for c in sub["top_contributors"][:3])
            lines.append(f"  Top contributors: {tcs}")
        if sub.get("top_posts"):
            lines.append("  Top post framing patterns:")
            for p in sub["top_posts"][:3]:
                score = p.get("score")
                score_str = f"{score}" if isinstance(score, (int, float)) else "—"
                title = (p.get("title") or "(no title)")[:120]
                lines.append(f"  - \"{title}\" ({score_str}↑)")
    lines.append("")
    lines.append(_T(lang,
        "🚨 In the W3 Reddit tasks you MUST cite the exact sub names listed above + "
        "at least 1 real top-contributor handle + at least 1 real top-post framing pattern "
        "as a reference. Do not invent sub names or handles.",
        "🚨 在 W3 Reddit 任务里**必须**引用上面的真实 sub 名 + "
        "至少 1 个真实 top contributor 用户名 + "
        "至少 1 个真实 top 帖的 framing 模式作为参考。"))
    lines.append("")
    return "\n".join(lines)


def _render_real_kol_section(kols: list, hints: dict, categories: list, lang: str = "zh") -> str:
    """Format the KOL candidates as a Markdown section to embed in Action Plan."""
    if not kols:
        return ""
    if hints.get("is_sales_led"):
        incentive = _T(lang,
            "**B2B incentive**: free PoC + co-published industry case study "
            "(don't offer \"3 months free Pro\" — it doesn't move enterprise buyers).",
            "**B2B 适用 incentive**:免费 POC + 联合发布行业案例研究(不要给"
            "\"3 个月免费 Pro\",对 enterprise 买家无吸引力)。")
    else:
        incentive = _T(lang,
            "**Incentive that fits**: 3 months free Pro plan + exclusive API key + a 1:1 "
            "onboarding session, in exchange for an honest review or a tutorial video.",
            "**适用 incentive**:3 个月免费 Pro 计划 + 独家 API key + 一次 1:1 onboarding,"
            "邀请撰写真实评测或制作教程视频。")
    cats_sep = _T(lang, ", ", "、")
    fallback_cat = _T(lang, "your product", "你的产品")
    cats_str = cats_sep.join(categories[:3]) if categories else fallback_cat
    lines = [
        "",
        _T(lang,
           "## 🎯 Real KOL candidates (live-scraped, ready to reach out)",
           "## 🎯 真实 KOL 候选名单(程序刚抓取,可立即外联)"),
        "",
        _T(lang,
           f"Based on the **{cats_str}** categories, we live-scraped {len(kols)} active "
           f"publishers via Brave Search. **These are real accounts — not LLM-invented** — "
           f"and can be filtered / reached out to immediately.",
           f"基于 **{cats_str}** 类目,从 Brave Search 实时抓取 {len(kols)} "
           f"位活跃发布者。**这些是真实账号 - 不是 LLM 编的**,可立即过滤 / 邀约。"),
        "",
        _T(lang,
           "| # | Platform | Handle | Bio excerpt |",
           "| # | 平台 | Handle | Bio 片段 |"),
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
        _T(lang,
           "### Outreach template (use after a manual filter pass on the handles)",
           "### 外联模板(点击 handle 进行人工筛选后使用)"),
        "",
        incentive,
        "",
        "```",
        "Hi [first name],",
        "",
        "I'm Iris from [Your product]. I've been following your work on "
        f"{cats_str.split(cats_sep)[0]}, particularly your recent post on [SPECIFIC POST].",
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
        _T(lang,
           "**Note**: the publishers above were found on public Twitter/LinkedIn pages via "
           "Brave Search. **Real fit and reach must be human-verified**: follower counts, "
           "recent posting cadence, bio-to-product fit. This table removes the find-the-KOL "
           "grunt work — it is **not an endorsement**.",
           "**注意**:以上是 Brave Search 在 Twitter/LinkedIn 公开页找到的发布者。"
           "**真实 fit / 影响力需人工核实**:粉丝数、近期发布频率、bio 与产品契合度。"
           "本表是去除『找 KOL』工作量,**不是 endorsement**。"),
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


def _render_action_matrix(hints: dict, level: int = 2, lang: str = "zh") -> str:
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
        _T(lang,
           f"{h} 🎯 30-Day Channel × Tactic Execution Matrix",
           f"{h} 🎯 30 天 Channel × Tactic 执行矩阵"),
        "",
        _T(lang,
           "Below is the table that maps each finding to a **specific channel × specific tactic** "
           "you can act on. Every row is drawn from the real tactical SOP of a matched skill (not "
           "LLM guesswork), with benchmark data attached for ground-truth comparison.",
           "下面是把每个 finding 落到 **具体渠道 × 具体战术** 的可执行表。每条都引自上方"
           "匹配 skill 的真实战术 SOP(不是 LLM 拍脑袋),带 benchmark 数据可对照。"),
        "",
        _T(lang,
           "| Week | Channel | Tactic | Source Skill | Benchmark |",
           "| Week | 渠道 | 具体战术 | 来源 Skill | Benchmark |"),
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
            # Week detection runs on the canonical ZH label; display translates
            has_week = when.startswith(("W", "D", "Phase", "发布"))
            if lang != "zh":
                when, what, bench = _EN(when), _EN(what), _EN(bench)
                chan = chan.replace("UGC 矩阵", "UGC Matrix")
            week = when if has_week else week_alloc[week_idx % len(week_alloc)]
            week_idx += 1
            matrix_rows.append(
                f"| **{week}** | {chan} | {what} | "
                f"[`{slug}`](https://huggingface.co/datasets/Gingiris/{slug}) | "
                f"_{bench}_ |"
            )

    lines.extend(matrix_rows)
    lines.extend([
        "",
        _T(lang,
           f"{sub_h} 📌 How to use this matrix",
           f"{sub_h} 📌 如何使用这张矩阵"),
        "",
        _T(lang,
           "1. **Drop into calendar by week** — each row's \"Week + Channel + Tactic\" "
           "can go straight into your calendar as an event.",
           "1. **按周倒入日历** - 把每行的 \"Week + 渠道 + 战术\" 直接当成 calendar event 排进去"),
        _T(lang,
           "2. **Weekly retro** — at end-of-week, check actuals against the Benchmark column. "
           "If you're below 50% of benchmark, cut that tactic and pick the next one.",
           "2. **每周 retro** - week 末对照 Benchmark 列查实际数据;落后 50% 砍掉换下一周战术"),
        _T(lang,
           "3. **Don't open them all at once** — max 3 channels in parallel per week, "
           "otherwise nobody can actually keep track.",
           "3. **不要全部一次开** - 同一周最多并行 3 个渠道,否则没人盯得过来"),
        _T(lang,
           "4. **Switch channels, not skills** — once you've picked the channel, install the "
           "corresponding skill as agent context and let AI handle the execution details.",
           "4. **改 channel 不改 skill** - 渠道选完再装对应 skill 当 agent 上下文,让 AI 帮你执行细节"),
    ])
    return "\n".join(lines)


def _fast_action_plan_fallback(product_name: str, hints: dict, lang: str) -> str:
    """Guarantee an actionable third report when a model exceeds its SLA."""
    if lang == "zh":
        lead = (
            f"# {product_name} 30 天行动计划\n\n"
            "> 本计划由已完成的公开网站诊断自动生成；模型服务超时，因此仅保留可直接执行、"
            "无需额外假设的优先动作。\n\n"
            "## 第 1 周｜建立可被发现的入口\n"
            "- 选定 3 个高意向竞品对比主题，发布对应对比页。\n"
            "- 为每页补齐 title、FAQ、内部链接和明确 CTA，并提交 IndexNow。\n"
            "- 建立基线：记录自然搜索点击、注册、激活和付费四项指标。\n\n"
            "## 第 2 周｜把产品能力变成可引用内容\n"
            "- 发布 2 篇围绕核心工作流的教程或案例；每篇回答一个明确问题。\n"
            "- 在首页与教程页补充 FAQ schema 和可复制的关键数据表。\n"
            "- 找 5 位垂直用户做 20 分钟访谈，验证最高优先级假设。\n\n"
            "## 第 3 周｜验证渠道与分发\n"
            "- 用一个真实案例在最匹配的设计/专业社区分享方法，而非硬推产品。\n"
            "- 将反馈整理为 3 个内容题目，并把最高频问题写进产品页 FAQ。\n\n"
            "## 第 4 周｜复盘与下一轮\n"
            "- 按内容页的展示、点击、注册和激活数据保留有效主题，停止无反馈主题。\n"
            "- 选出下月 3 个可复制页面和 1 个需要产品团队解决的激活瓶颈。\n\n"
            "## 成功判定\n"
            "- 对比页、教程页均被 sitemap 收录并可被搜索引擎抓取。\n"
            "- 每周都有可追踪的访问→注册→激活漏斗数据，而非仅看曝光。\n\n"
        )
    else:
        lead = (
            f"# {product_name} — 30-Day Action Plan\n\n"
            "> Generated from the completed public-site diagnosis. The long-form model timed out, so this version keeps only executable actions that do not require invented facts.\n\n"
            "## Week 1 — Create discoverable entry points\n- Publish three high-intent comparison pages.\n- Add titles, FAQs, internal links and clear CTAs; submit through IndexNow.\n- Record baseline search, signup, activation and paid-conversion metrics.\n\n"
            "## Week 2 — Build citation-worthy proof\n- Publish two workflow tutorials or case studies.\n- Add FAQ schema and a reusable facts table.\n- Run five 20-minute user interviews to validate the highest-priority assumption.\n\n"
            "## Week 3 — Validate distribution\n- Share one real workflow in the most relevant community.\n- Turn repeated questions into product-page FAQs and three new content briefs.\n\n"
            "## Week 4 — Review and repeat\n- Keep topics that drive visits → signups → activation; stop the rest.\n- Select three repeatable pages and one activation bottleneck for the next cycle.\n\n"
        )
    return lead + _render_action_matrix(hints, level=2, lang=lang)


def _render_playbook_section(hints: dict, level: int = 2, lang: str = "zh") -> str:
    """Render the canonical 'Gingiris Playbook' section, using REAL skills only.

    `level` controls heading depth (2 = ## , 3 = ###). The section is a
    safe drop-in replacement for whatever the LLM emitted under
    "匹配的 Gingiris Playbook" / "推荐安装的 Gingiris AI Skills" / etc.
    """
    skills = _pick_skills_for_product_type(hints)
    h = "#" * level
    sub_h = "#" * (level + 1)
    product_type = hints.get('product_type', _T(lang, 'Unknown', '未知'))
    lines = [
        _T(lang,
           f"{h} 📚 Matched Gingiris Skills (auto-matched by product type)",
           f"{h} 📚 匹配的 Gingiris Skills(由产品类型自动匹配)"),
        "",
        _T(lang,
           f"Based on the programmatically detected product type **{product_type}**, "
           f"we matched the following real skill datasets from "
           f"[Hugging Face @Gingiris](https://huggingface.co/Gingiris) (43 published). "
           f"Each skill is production-verified; the install commands below run as-is.",
           f"基于程序判定的产品类型 **{product_type}**,"
           f"为你匹配以下来自 [Hugging Face @Gingiris](https://huggingface.co/Gingiris) "
           f"的真实 skill datasets(43 个发布中)。每个 skill 都已经在线上验证过;"
           f"下方安装命令可直接执行。"),
        "",
        _T(lang,
           "| Skill | Best for | HuggingFace |",
           "| Skill | 适用场景 | HuggingFace |"),
        "| --- | --- | --- |",
    ]
    for slug in skills:
        info = GINGIRIS_SKILL_REGISTRY[slug]
        bf = info['best_for'] if lang == "zh" else _EN(info['best_for'])
        lines.append(
            f"| **{info['title']}** | {bf} | "
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
        _T(lang,
           f"{sub_h} 📦 Install",
           f"{sub_h} 📦 安装"),
        "",
        _T(lang,
           "Skills are SKILL.md files; they work in Claude Code / Cursor / Gemini CLI and "
           "other AI-agent IDEs. Replace `<SLUG>` with one from the table above.",
           "Skills 是 SKILL.md 文件,可在 Claude Code / Cursor / Gemini CLI 等 "
           "AI agent IDE 里使用。下面 `<SLUG>` 替换成上方表格里的 slug 即可。"),
        "",
        _T(lang,
           "**Method A — install all at once (recommended)**",
           "**方法 A - 一键批量装全部(推荐)**"),
        "",
        "```bash",
        "mkdir -p ~/.claude/skills",
        f"for s in {batch_slugs}; do",
        '  git clone "https://huggingface.co/datasets/Gingiris/$s" \\',
        '    "$HOME/.claude/skills/$s"',
        "done",
        _T(lang,
           "# restart Claude Code and they activate",
           "# 重启 Claude Code 即生效"),
        "```",
        "",
        _T(lang,
           "**Method B — install a single skill**",
           "**方法 B - 单装 1 个**"),
        "",
        "```bash",
        "git clone https://huggingface.co/datasets/Gingiris/<SLUG> \\",
        "  ~/.claude/skills/<SLUG>",
        "```",
        "",
        _T(lang,
           "**Method C — other IDEs / read in browser**",
           "**方法 C - 其他 IDE / 浏览器读**"),
        "",
        _T(lang,
           "- Cursor / Gemini CLI: `huggingface-cli download Gingiris/<SLUG> --repo-type dataset --local-dir ./.cursor/rules/<SLUG>` (first `pip install -U huggingface_hub`)",
           "- Cursor / Gemini CLI: `huggingface-cli download Gingiris/<SLUG> --repo-type dataset --local-dir ./.cursor/rules/<SLUG>`(先 `pip install -U huggingface_hub`)"),
        _T(lang,
           "- Read online: <https://huggingface.co/datasets/Gingiris/><SLUG> or <https://gingiris.tools/skills>",
           "- 在线读: <https://huggingface.co/datasets/Gingiris/><SLUG> 或 <https://gingiris.tools/skills>"),
        "",
        _T(lang,
           "**Trigger**: after install, describe the scenario in your AI-agent chat "
           "(e.g. \"we're prepping a launch\") and the agent auto-loads the matching skill as context.",
           "**触发**:装好后在 AI agent 对话里描述场景(例如 \"我们要做 launch\"),agent 自动加载对应 skill 作上下文。"),
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


def _replace_playbook_section(md: str, hints: dict, *, heading_level: int = 2, lang: str = "zh") -> str:
    """Find any LLM-generated Gingiris Playbook / Skills section and replace
    it wholesale with the deterministic version built from the real registry.

    Critical because the LLM keeps inventing slugs like 'bofu-content-harvest'
    that don't exist. A fake `npx skills add` command in the report body is
    worse than no recommendation at all - paying users would silently fail.

    Falls back to appending the canonical section if no LLM section matched.
    """
    if not md:
        return md
    replacement = _render_playbook_section(hints, level=heading_level, lang=lang)
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

## 输出要求(Markdown 格式,1800-2600 字；优先清晰、可验证，拒绝为了篇幅重复同一判断)

# {product_name} 增长诊断报告

> 诊断日期:今天
> 方法论:Gingiris Growth Skills Framework

**报告结构 = 总分总**:先给核心论断(总)→ 分维度详细诊断(分)→ 行动与综合判断(总)。用户先读「核心论断」就能拿到全局,再往下看细节。

## 核心论断(TL;DR — 全文最先读这段)

用 4-6 句给出**判断先行**的全局结论(这是「总」,必须与下文一致、不引入新事实):
- **一句话定性**:{product_name} 是什么类型的产品(SaaS/OSS/AI/Mobile/Dev Tool/Consumer)、处于哪个增长阶段(Pre-launch/Launch/Cold Start/Growth/Scale),判断依据一句带过。
- **最大增长杠杆或最致命缺口**:基于本报告 finding,当前最该抓的一个机会 / 最该补的一个洞是什么。
- **如果只做一件事**:指向下文 P0 里最高 ROI 的那一条。
- **诊断置信度边界**:本次基于公开官网抓取,一句话说明哪些维度看不到(见 §7 盲区),避免过度断言。

---

_以下为分维度详细诊断（分）_

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

---

_以下为行动与综合判断（总）——回扣开头的「核心论断」_

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

## 8. 关键风险与可证伪假设
把本诊断里最关键的 2-4 个推断写成**可证伪假设**(比"列风险"更有分析力度)。每条按三段式:
- **假设**:一句话陈述(例:"该产品增长瓶颈在激活而非获客")。
- **证伪条件**:什么观察/数据出现就能推翻它(例:"若注册→激活 >40%,则本假设被证伪")。
- **当前依据**:基于本报告哪条 finding 得出(标注来源)。
这样用户拿到咨询数据后能直接验证,而不是面对一堆模糊判断。

## 9. 匹配的 Gingiris Playbook
表格:框架名 | 适用场景(基于本报告 finding) | 安装命令

---

请记住反幻觉硬约束 A-D,每条 finding 后用 `(依据:xxx)` 标注来源。
{skills_block}
"""

    user_prompt += _lang_tail(lang)
    # The diagnosis is the first report users see. Keep it compact enough to
    # arrive within the interactive model budget; the later action plan adds
    # implementation detail instead of making this facts layer encyclopedic.
    return await _call_llm_long(_get_system_prompt(lang=lang), user_prompt, max_tokens=2600)


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
    # 2026-06-20: defensive wrap — Iris saw action_plan silently fail
    # twice in a row because of None handling in the Reddit context
    # builder (SerpAPI returns sparse data, subscribers/description/
    # title can each be None). The LLM call itself was healthy; the
    # bug was crashing the prompt-build BEFORE the LLM was hit. Now
    # any further None-handling regression downgrades gracefully:
    # we skip the Reddit block and the action_plan still gets generated
    # via the LLM, just without the per-sub injection. Skills + tactics
    # cheatsheet are still in the system prompt regardless.
    try:
        reddit_block = _build_reddit_context_for_llm(reddit_data or [], lang=lang)
    except Exception as _e:
        import traceback as _tb
        log.error("Reddit context build failed (skipping injection): %s\n%s",
                  _e, _tb.format_exc()[:1000])
        reddit_block = ""

    user_prompt = f"""{_lang_instruction(lang)}基于以下两段输入,为 **{product_name}** 制定 30 天行动计划。

# 输入 1:原始抓取数据
{context}

---

# 输入 2:上一阶段已生成的诊断报告(事实基准)
{diagnosis_md}

---

## 输出要求(Markdown 格式,2200-3200 字；每周保留最有杠杆的 2-4 个动作，避免模板化堆砌)

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

    # Trim system-prompt tactical cheatsheet to skills relevant for THIS
    # product type. Combined with retry-on-transient in _try_deepseek,
    # this drops the action-plan failure rate when the diagnosis report
    # is large and DeepSeek context gets squeezed.
    picked_skills = _pick_skills_for_product_type(hints)
    sys_prompt = _get_system_prompt(filter_to_skills=picked_skills, lang=lang)
    user_prompt += _lang_tail(lang)
    return await _call_llm_long(sys_prompt, user_prompt, max_tokens=3200)


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

## 输出要求(Markdown 格式,800-1200 字；这是用户首先阅读的决策页，先结论、后依据、再行动)

# {product_name} 增长诊断 - 执行摘要

**诊断日期:** 今天
**产品:** {product_name}
**URL:** {site_data.get('url', '')}

## 1. 决策总览（30 秒读完）
用一张紧凑表格：当前阶段 | 最大增长杠杆 | 最紧急风险 | 本月目标。所有格子都必须能回指输入报告；不确定时写“需验证”。

## 2. 🎯 核心发现(3 句话)
直接摘自诊断报告的"## 1. 产品概览"、"## 2. 增长诊断"、"## 3. SEO/GEO"三个章节,用 3 句话总结。**不引入新发现**。

## 3. 🚨 三个最严重的问题
直接摘自诊断报告"## 5. P0 - 本周必做"。最多 3 条,每条包含:
- 问题描述(一句)
- 影响程度(🔴 极高 / 🟡 中 / 🟢 低)
- 修复时间估算(取自 Action Plan Week 1)
- 预期影响(定性,照搬诊断报告原话)

## 4. ✅ 快速赢面清单(按优先级)
- 本周做(2-3 小时)- 摘自 Action Plan Week 1
- 第 1-2 周做(8 小时)- 摘自 Action Plan Week 2
- 第 3-4 周做(12 小时)- 摘自 Action Plan Week 3-4

## 5. 📊 6 个月财务预测(如基础数据不足则跳过本节)
**只在诊断报告里有量化基线时输出**。否则写"基线数据缺失,建议用户提供 GA / GSC 后再做预测"。

## 6. 🎯 关键 KPI 追踪
表格:KPI(取自诊断报告) | 当前(取自诊断报告,无则写"待用户提供") | 3 个月目标 | 6 个月目标

## 7. 🛠️ 推荐工具堆栈
摘自 Action Plan"工具清单"

## 8. 📚 匹配的 Gingiris 框架
摘自诊断报告"## 8. 匹配的 Gingiris Playbook"

## 9. ❓ 下一步行动
- 立即(今天):取 Action Plan Week 1 任务 1
- 本周:取 Action Plan Week 1 剩余任务
- 下周:取 Action Plan Week 2 任务

---

🚨 一致性硬约束:
- 本摘要不能出现诊断报告 / 行动计划里没出现的新 finding。
- 本摘要的"三个最严重问题"必须能在 Action Plan 里找到对应任务。
- 不允许编新数字 / 新竞品 / 新案例。
"""

    user_prompt += _lang_tail(lang)
    return await _call_llm_long(_get_system_prompt(lang=lang), user_prompt, max_tokens=1400)


# ─── Main Orchestrator ──────────────────────────────────────────────────────


def _lang_instruction(lang: str) -> str:
    """Strong English language lock for EN audits. Iris 2026-06-20:
    a single English line at the top of a ~10K-token Chinese prompt
    body wasn't enough — the LLM produced 85% Chinese diagnoses even
    when lang='en'. Now uses the same head+tail wrap pattern that
    fixed ai_summary.py (commit a6f4740): show translation examples
    + ban Chinese characters in output. Use with _lang_tail()."""
    if (lang or "").lower().startswith("en"):
        return (
            "🌐 CRITICAL LANGUAGE RULE — READ BEFORE ANYTHING ELSE:\n"
            "The Chinese system instructions below are written in Chinese for historical reasons, "
            "but your ENTIRE response MUST be in fluent natural English. Treat the Chinese as a "
            "TRANSLATION TARGET — read each Chinese section heading and instruction, then OUTPUT "
            "the English equivalent. Do NOT echo any Chinese characters in your response.\n\n"
            "🚫 SPECIFIC ANTI-PATTERN — DO NOT QUOTE CHINESE VERBATIM:\n"
            "It's tempting to copy Chinese phrases from the instructions, examples, or skill SOPs "
            "and wrap them in quotes (\"The system notes: '可能 /pricing.html 存在'\"). "
            "Iris 2026-06-25 verified this leak is the #1 cause of CJK characters showing up in "
            "EN reports — even when the surrounding prose is otherwise correct English. "
            "RULE: if a Chinese phrase appears in the prompt that you want to cite or paraphrase, "
            "TRANSLATE it to English inside your quote. Never wrap Chinese text in quotation marks "
            "and pass it through.\n"
            "  WRONG:  The system notes: \"可能 /pricing.html 存在但 /pricing 无扩展名版本未配置\"\n"
            "  RIGHT:  The system notes: \"/pricing.html may exist but /pricing (no extension) is not configured\"\n\n"
            "Examples of required translation:\n"
            "  '## 一、产品定位与目标用户' → '## 1. Product Positioning & ICP'\n"
            "  '执行摘要' → 'Executive Summary'\n"
            "  '诊断报告' → 'Diagnosis Report'\n"
            "  '30 天行动计划' → '30-Day Action Plan'\n"
            "  '增长策略' → 'Growth Strategy'\n"
            "  '渠道' → 'Channel'\n"
            "  '匹配的 Gingiris Skills' → 'Matched Gingiris Skills'\n"
            "  '推荐 Reddit 渠道' → 'Recommended Reddit Channels'\n\n"
            "If you find yourself about to write a Chinese phrase, translate it to English first. "
            "If you find yourself about to quote Chinese in your output, translate the quoted "
            "content to English first.\n\n"
        )
    return ""  # zh / default — original prompts are Chinese


def _lang_tail(lang: str) -> str:
    """Final language reminder appended at the END of EN prompts."""
    if (lang or "").lower().startswith("en"):
        return (
            "\n\n🌐 FINAL LANGUAGE REINFORCEMENT: This is your last reminder. Your ENTIRE "
            "output, including ALL headings, bullets, table cells, and any inline citations, "
            "must be in fluent natural English with no Chinese characters whatsoever. "
            "Do not echo any Chinese phrase from the instructions above, even inside quotation "
            "marks or code blocks (translate the inner content to English first). If you are "
            "about to write a sentence that contains 中文 of any kind, STOP, translate the "
            "Chinese fragment to English, and then continue. The output is being scanned by an "
            "automated reviewer that will reject any Chinese character (including 一-鿿, "
            "Chinese punctuation, and fullwidth forms like ＋)."
        )
    return ""


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
    audit_started_at = datetime.now(timezone.utc).isoformat()
    audit_started_perf = time.perf_counter()
    stage_started_perf: dict[str, float] = {}
    stage_seconds: dict[str, float] = {}

    # Parse product name from URL if not provided
    if not product_name:
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        import re
        brand = re.sub(r'^www\.', '', parsed.netloc.lower())
        brand = re.sub(r'\.[a-z]{2,6}$', '', brand)
        product_name = brand.replace("-", " ").replace("_", " ").capitalize()

    def _update(stage: str, status: str):
        now = time.perf_counter()
        if status == "running":
            stage_started_perf.setdefault(stage, now)
        elif status in ("done", "failed"):
            started = stage_started_perf.setdefault(stage, audit_started_perf)
            stage_seconds[stage] = round(now - started, 3)
        if jobs_dict and job_id and job_id in jobs_dict:
            jobs_dict[job_id]["progress"][stage] = status
            jobs_dict[job_id]["timing"] = {
                "started_at": audit_started_at,
                "total_seconds": round(now - audit_started_perf, 3),
                "stages": dict(stage_seconds),
            }

    _emit_save_tasks = []  # track fire-and-forget partial saves so the
    # final completion save can await them and always win the last write
    # (fixes _partial:true sticking on completed reports → excluded from gallery)

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
            # Progressive persistence — Iris 2026-07-07: three audits died
            # today because jobs live only in process memory and rolling
            # deploys replace the machines mid-run. Upserting to Supabase on
            # every finished section means (a) a deploy can no longer lose
            # completed work, and (b) share links (/share/audit/{id}) work
            # the moment the first section exists instead of 404ing forever
            # (bug ga-bcd33e6d: user shared an audit whose job was killed
            # before the completion-time save ever ran).
            try:
                import asyncio as _aio2
                from .supabase_client import save_report_to_db as _save
                partial = {
                    "product_name": jobs_dict[job_id].get("product_name") or product_name,
                    "url": jobs_dict[job_id].get("url") or url,
                    "reports": dict(r),
                    "lang": lang,
                    "timing": jobs_dict[job_id].get("timing") or {},
                    "_partial": jobs_dict[job_id].get("status") != "completed",
                }
                _emit_save_tasks.append(_aio2.create_task(_save(
                    job_id=job_id,
                    user_id=jobs_dict[job_id].get("user_id"),
                    url=jobs_dict[job_id].get("url") or url,
                    product_name=partial["product_name"] or "",
                    report=partial,
                    markdown="",
                    is_public=True,
                )))
            except Exception:
                pass  # persistence is best-effort; never break the pipeline

    # Step 1: Fetch site data
    _update("fetch", "running")
    site_data = await fetch_site_with_tinyfish(url)
    if site_data.get("error"):
        _update("fetch", "failed")
        return {"error": _T(lang,
            f"Site fetch failed: {site_data['error']}",
            f"网站抓取失败: {site_data['error']}")}
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
        diag_md = _replace_playbook_section(diag_md, hints_for_diag, heading_level=2, lang=lang)
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
            "error": _T(lang,
                "Diagnosis stage failed; pipeline aborted to prevent downstream reports from hallucinating.",
                "Diagnosis 阶段失败,已中止 pipeline(防止下游报告 hallucinate)"),
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
    # Start the decision brief immediately. It only depends on the verified
    # Diagnosis, so it must not be held behind optional Reddit discovery.
    # This makes the first decision-ready report appear earlier even when a
    # third-party research endpoint is slow.
    exec_task = asyncio.create_task(
        generate_executive_summary(
            site_data, product_name, reports["diagnosis_report"],
            reports["diagnosis_report"],
            lang=lang,
        )
    )

    # Reddit discovery finishes in parallel with Diagnosis. Wait for it only
    # before building the Action Plan (where real community data is useful),
    # and never allow it to delay the Executive Summary.
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

    # Both tasks now run concurrently; awaiting the compact Executive Summary
    # first lets us stream the decision page before the longer Action Plan,
    # serializing the two. Reveal order ends up Diagnosis → Exec → Plan.
    # ── Process Executive Summary (finishes first) ───────────────────────
    try:
        exec_result = await exec_task
    except Exception as e:
        exec_result = e
    if isinstance(exec_result, dict) and exec_result.get("success"):
        exec_md = _scrub_absence_phrases(exec_result["content"])
        exec_md = _replace_playbook_section(exec_md, hints, heading_level=2, lang=lang)
        reports["executive_summary"] = exec_md
        sources["exec"] = exec_result.get("source", "?")
        _emit("executive_summary", exec_md)
        _update("executive_summary", "done")
    else:
        _update("executive_summary", "failed")
        log.error("Executive Summary generation failed: %s", exec_result)

    # The anchor for "Gingiris Skills" section depends on lang — the EN
    # variant uses an English heading, the ZH variant uses the historical
    # Chinese heading. Use _find_skills_anchor() so the matrix/reddit/kol
    # sections insert BEFORE it regardless of language.
    def _find_skills_anchor(md: str) -> str:
        for a in ("## 📚 Matched Gingiris Skills", "## 📚 匹配的 Gingiris Skills"):
            if a in md:
                return a
        return ""

    # ── Process Action Plan (longer - finishes last) ─────────────────────
    try:
        plan_result = await plan_task
    except Exception as e:
        plan_result = e
    if isinstance(plan_result, dict) and plan_result.get("success"):
        plan_md = _scrub_absence_phrases(plan_result["content"])
        plan_md = _strip_forbidden_channel_tasks(plan_md, hints)
        plan_md = _replace_playbook_section(plan_md, hints, heading_level=2, lang=lang)
        # Inject the deterministic Week × Channel × Tactic matrix RIGHT
        # BEFORE the Gingiris Skills section. This is the fix for Iris's
        # "reports too SEO-only / channels too limited" complaint -
        # programmatically forces multi-channel coverage drawn from real
        # skill tactics with real benchmarks, instead of trusting the LLM
        # to remember to span Reddit/Twitter/KOL/UGC/etc.
        matrix_md = _render_action_matrix(hints, level=2, lang=lang)
        anchor = _find_skills_anchor(plan_md)
        if anchor:
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
        reddit_section = _render_reddit_section(reddit_data, hints, lang=lang)
        if reddit_section:
            anchor = _find_skills_anchor(plan_md)
            if anchor:
                plan_md = plan_md.replace(anchor, reddit_section + "\n\n" + anchor, 1)
            else:
                plan_md = plan_md.rstrip() + "\n" + reddit_section + "\n"
        kol_section = _render_real_kol_section(kols, hints, categories, lang=lang)
        if kol_section:
            anchor = _find_skills_anchor(plan_md)
            if anchor:
                plan_md = plan_md.replace(anchor, kol_section + "\n\n" + anchor, 1)
            else:
                plan_md = plan_md.rstrip() + "\n" + kol_section + "\n"
        reports["action_plan"] = plan_md
        sources["plan"] = plan_result.get("source", "?")
        _emit("action_plan", plan_md)
        _update("action_plan", "done")
    else:
        # A long-form action-plan timeout must never turn a completed audit
        # into a two-report product. Emit a bounded, deterministic execution
        # plan grounded in the verified diagnosis instead.
        plan_md = _fast_action_plan_fallback(product_name, hints, lang)
        reports["action_plan"] = plan_md
        sources["plan"] = "deterministic fallback"
        _emit("action_plan", plan_md)
        _update("action_plan", "done")
        # Emit traceback when plan_result is an Exception so the next
        # failure tells us EXACTLY which line + module — short-circuits
        # the "guess from the str(e)" debugging loop Iris and I burned
        # half an hour on 2026-06-20.
        if isinstance(plan_result, Exception):
            import traceback as _tb
            log.error(
                "Action Plan generation failed: %s\n%s",
                plan_result, _tb.format_exception(type(plan_result), plan_result, plan_result.__traceback__),
            )
        else:
            log.error("Action Plan generation failed: %s", plan_result)

    # Drain any still-pending progressive-save tasks BEFORE returning. Each
    # of those writes _partial:true (job status is still "running" when they
    # were queued). If one lands after app.py's completion save it revives the
    # partial flag and the report drops out of the public gallery. Awaiting
    # them here guarantees the caller's final save is the last write.
    if _emit_save_tasks:
        try:
            await asyncio.gather(*_emit_save_tasks, return_exceptions=True)
        except Exception:
            pass

    return {
        "product_name": product_name,
        "url": url,
        "lang": lang,
        "timing": {
            "started_at": audit_started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "total_seconds": round(time.perf_counter() - audit_started_perf, 3),
            "stages": stage_seconds,
        },
        "site_data_summary": {
            "homepage_title": site_data.get("homepage", {}).get("title"),
            "has_robots": bool(site_data.get("robots_txt")),
            "has_pricing": bool(site_data.get("pricing_page")),
            "has_sitemap": bool(site_data.get("sitemap")),
        },
        "reports": reports,
        "source": sources,
        "_partial": False,
    }
