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


def _build_site_context(site_data: dict) -> str:
    """将抓取数据组织成 LLM 可读的上下文。"""
    parts = []
    url = site_data.get("url", "")
    domain = site_data.get("domain", "")

    parts.append(f"## 目标产品网站：{url}（域名：{domain}）\n")

    # Homepage
    hp = site_data.get("homepage", {})
    if hp:
        parts.append("### 首页信息")
        if hp.get("title"):
            parts.append(f"- Title: {hp['title']}")
        if hp.get("description"):
            parts.append(f"- Meta Description: {hp['description']}")
        if hp.get("text"):
            parts.append(f"\n#### 首页内容（截取）：\n{hp['text'][:8000]}")
        if hp.get("links"):
            internal_links = [l for l in hp["links"] if domain in l][:20]
            external_links = [l for l in hp["links"] if domain not in l][:10]
            if internal_links:
                parts.append(f"\n#### 站内链接（{len(internal_links)} 条）：")
                parts.append("\n".join(f"  - {l}" for l in internal_links))
            if external_links:
                parts.append(f"\n#### 外部链接（{len(external_links)} 条）：")
                parts.append("\n".join(f"  - {l}" for l in external_links))

    # Robots.txt
    robots = site_data.get("robots_txt")
    if robots:
        parts.append(f"\n### robots.txt\n```\n{robots[:1500]}\n```")

    # Pricing
    pricing = site_data.get("pricing_page")
    if pricing and isinstance(pricing, dict):
        parts.append(f"\n### 定价页面")
        if pricing.get("title"):
            parts.append(f"- Title: {pricing['title']}")
        if pricing.get("text"):
            parts.append(f"\n{pricing['text'][:4000]}")
    elif pricing is None:
        parts.append("\n### 定价页面\n无公开定价页（/pricing 返回 404）")

    # Sitemap
    sitemap = site_data.get("sitemap")
    if sitemap and isinstance(sitemap, str):
        parts.append(f"\n### Sitemap\n```\n{sitemap[:2000]}\n```")
    elif sitemap is None:
        parts.append("\n### Sitemap\n无 sitemap.xml")

    return "\n".join(parts)


async def generate_executive_summary(site_data: dict, product_name: str) -> dict:
    """生成 Executive Summary（~2000 字）"""
    context = _build_site_context(site_data)

    user_prompt = f"""基于以下抓取的产品网站数据，为 **{product_name}** 生成一份增长诊断执行摘要（Executive Summary）。

{context}

---

## 输出要求（Markdown 格式）：

# {product_name} 增长诊断 — 执行摘要

**诊断日期：** 今天
**产品：** {product_name}
**URL：** {site_data.get('url', '')}

## 🎯 核心发现（3 句话）
用 3 句话总结最关键的发现。

## 🚨 三个最严重的问题
每个问题包含：
- 问题描述
- 影响程度（🔴 极高 / 🟡 中 / 🟢 低）
- 修复时间估算
- 预期影响

## ✅ 快速赢面清单（按优先级）
- 本周做（2-3 小时）
- 第 1-2 周做（8 小时）
- 第 3-4 周做（12 小时）

## 📊 6 个月财务预测
保守场景 vs 激进场景（带前提假设）

## 🎯 关键 KPI 追踪
表格：KPI | 当前 | 3个月目标 | 6个月目标

## 🛠️ 推荐工具堆栈
按类别推荐

## 📚 匹配的 Gingiris 框架
列出最匹配的 2-3 个 Gingiris Playbook，说明为什么匹配

## ❓ 下一步行动
立即 / 本周 / 下周 的具体行动

---

注意：每条结论必须基于抓取数据。数据不足则标注。不编造数字。"""

    return await _call_llm_long(GINGIRIS_SKILLS_CONTEXT, user_prompt, max_tokens=4000)


async def generate_diagnosis_report(site_data: dict, product_name: str) -> dict:
    """生成完整诊断报告（~8000 字）"""
    context = _build_site_context(site_data)

    user_prompt = f"""基于以下抓取的产品网站数据，为 **{product_name}** 生成一份完整的增长诊断报告。

{context}

---

## 输出要求（Markdown 格式，8000 字以上）：

# {product_name} 增长诊断报告

> 诊断日期：今天
> 方法论：Gingiris Growth Skills Framework

## 1. 产品概览
- 产品定义与核心价值主张
- 核心功能（基于首页抓取）
- 目标用户（ICP）
- 商业模式推断
- 定价分析（基于定价页数据，无则推断）

## 2. 增长诊断（三维度）
### 2.1 产品类型分类
### 2.2 增长阶段判定（附诊断依据）
### 2.3 主要渠道缺口（表格：渠道 | 现状 | 严重程度）

## 3. SEO/GEO 现状审计
- robots.txt 分析（AI 爬虫是否开放）
- Sitemap 完整度
- 内容资产盘点
- 结构化数据
- GEO 就绪度评估

## 4. 竞品定位分析
- 市场定位推断
- 可能的竞品（基于产品类型和功能）
- 差异化建议

## 5. 增长策略推荐（P0/P1/P2 优先级）
### P0 — 本周必做（最高 ROI）
### P1 — 2 周内完成
### P2 — 30 天内完成

## 6. 渠道策略详解
逐渠道分析：内容/SEO、社区、KOL、付费、产品内增长

## 7. 风险与假设
列出诊断的局限性和假设

## 8. 匹配的 Gingiris Playbook
表格：框架名 | 应用方式 | 安装命令

---

注意：数据不足的维度基于产品类型做合理推断但必须标注"推断"。"""

    return await _call_llm_long(GINGIRIS_SKILLS_CONTEXT, user_prompt, max_tokens=8000)


async def generate_action_plan(site_data: dict, product_name: str) -> dict:
    """生成 30 天行动计划（~6000 字）"""
    context = _build_site_context(site_data)

    user_prompt = f"""基于以下抓取的产品网站数据，为 **{product_name}** 生成一份 30 天行动计划。

{context}

---

## 输出要求（Markdown 格式，6000 字以上）：

# {product_name} — 30 天行动计划

> 从当前状态到"有增长动力"的快速实施指南
> 预计投入：估算总工时

## Week 1: Day 1-7 — 基础设施修复

每个任务包含：
- 目的
- 当前问题
- 修复方案（含代码/配置示例）
- 验证方法
- 预期影响

任务 1: 修复 robots.txt（如需）
任务 2: 添加结构化数据（JSON-LD）
任务 3: 创建/优化 定价页
任务 4: 基础 SEO 修复

## Week 2: Day 8-14 — 内容引擎启动

- 竞品对比页 x3（含具体标题、结构、关键词）
- FAQ Schema 添加
- 首篇方法论博客

## Week 3: Day 15-21 — 渠道拓展

- KOL 合作启动（含 outreach 模板）
- 社区种草策略（Reddit/HN/Discord）
- 邮件序列设计

## Week 4: Day 22-30 — 加速与验证

- 付费实验设计（如适用）
- PLG 优化
- 复盘与调整框架

## 每周 KPI 追踪模板

表格：周 | 指标 | 目标 | 实际

## 工具清单

按任务推荐具体工具

## 推荐安装的 Gingiris AI Skills

```bash
npx skills add Gingiris-1031/xxx
```

---

注意：每个任务必须具体到"今天就能开始执行"。包含代码示例、配置模板、文案模板。"""

    return await _call_llm_long(GINGIRIS_SKILLS_CONTEXT, user_prompt, max_tokens=8000)


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

    # Step 2: Generate reports in parallel
    _update("executive_summary", "running")
    _update("diagnosis", "running")
    _update("action_plan", "running")

    exec_task = generate_executive_summary(site_data, product_name)
    diag_task = generate_diagnosis_report(site_data, product_name)
    plan_task = generate_action_plan(site_data, product_name)

    exec_result, diag_result, plan_result = await asyncio.gather(
        exec_task, diag_task, plan_task, return_exceptions=True
    )

    # Process results
    reports = {}

    if isinstance(exec_result, dict) and exec_result.get("success"):
        reports["executive_summary"] = exec_result["content"]
        _update("executive_summary", "done")
    else:
        reports["executive_summary"] = None
        _update("executive_summary", "failed")
        log.error("Executive Summary generation failed: %s", exec_result)

    if isinstance(diag_result, dict) and diag_result.get("success"):
        reports["diagnosis_report"] = diag_result["content"]
        _update("diagnosis", "done")
    else:
        reports["diagnosis_report"] = None
        _update("diagnosis", "failed")
        log.error("Diagnosis Report generation failed: %s", diag_result)

    if isinstance(plan_result, dict) and plan_result.get("success"):
        reports["action_plan"] = plan_result["content"]
        _update("action_plan", "done")
    else:
        reports["action_plan"] = None
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
        "source": {
            "exec": exec_result.get("source") if isinstance(exec_result, dict) else "error",
            "diag": diag_result.get("source") if isinstance(diag_result, dict) else "error",
            "plan": plan_result.get("source") if isinstance(plan_result, dict) else "error",
        },
    }
