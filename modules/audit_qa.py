"""Audit Q&A — answers follow-up questions about a Growth Audit report.

Grounded in the report's own three sections + site_data_summary so DeepSeek
can't drift into generic SaaS marketing platitudes — every answer must
quote or cite a specific section. If the question is out-of-scope of the
report, the LLM is instructed to say so rather than improvise.

Pipeline per question:
  1. fetch_audit_context(job_id) → 3 reports + site_data_summary
  2. build_prompt(question, history, context)
  3. _call_deepseek(prompt) → answer
  4. _detect_cited_section(answer) → 'exec'|'diag'|'plan'|'mixed'|None
  5. persist to audit_qa table (best-effort, doesn't block the response)

Cost per question: ~3-5K input tokens + ~300 output. DeepSeek-chat at
$0.27/M input + $1.10/M output ≈ $0.0015 per Q. Cheap enough that the
$29 Pro tier with 50 questions still leaves >$28 margin.
"""
import asyncio
import json as _json
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)


# Rate limits — per visitor_id per hour, before charging credits.
RATE_LIMIT_ANON_HOUR = 3      # share-page viewer with no login
RATE_LIMIT_FREE_HOUR = 5      # logged-in free
RATE_LIMIT_PRO_HOUR  = 50
RATE_LIMIT_TEAM_HOUR = 200


# ─── Context fetch ───────────────────────────────────────────────────────────


async def fetch_audit_context(job_id: str, jobs_dict: Optional[dict] = None) -> Optional[dict]:
    """Pull the audit's three reports + site_data_summary by job_id.

    Order of precedence matches /api/share/audit/{job_id}:
      1. In-memory jobs_dict (warm cache during the same process lifetime)
      2. Supabase `reports` table (column `id` = job_id, `report` JSON column)

    Returns None if the audit doesn't exist or hasn't completed.
    """
    if jobs_dict is not None:
        job = jobs_dict.get(job_id)
        if job and job.get("status") == "completed" and job.get("reports"):
            return {
                "product_name":      job.get("product_name") or "the product",
                "url":               job.get("url"),
                "reports":           job["reports"],
                "site_data_summary": job.get("site_data_summary") or {},
            }

    try:
        from .supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return None
        result = sb.table("reports").select(
            "id,product_name,url,report,status"
        ).eq("id", job_id).limit(1).execute()
        rows = result.data or []
        if not rows:
            return None
        row = rows[0]
        if row.get("status") and row["status"] != "completed":
            return None
        payload = row.get("report") or {}
        if isinstance(payload, str):
            try:
                payload = _json.loads(payload)
            except Exception:
                payload = {}
        reports = payload.get("reports") or {}
        if not reports:
            return None
        return {
            "product_name":      row.get("product_name") or "the product",
            "url":               row.get("url"),
            "reports":           reports,
            "site_data_summary": payload.get("site_data_summary") or {},
        }
    except Exception as e:
        log.warning("fetch_audit_context supabase error: %s", e)
        return None


# ─── Prompt construction ─────────────────────────────────────────────────────


_SYSTEM_PROMPT_EN = """You are an expert growth advisor answering follow-up questions about a Growth Audit report that has already been delivered to the user.

🌐 LANGUAGE RULE — CRITICAL:
- Detect the user's question language and ALWAYS answer in that language ONLY.
- If the question is in English → answer 100% in English. Translate every Chinese phrase you cite from the report into natural English. Do NOT leave Chinese characters in your reply.
- If the question is in Chinese → answer 100% in Chinese. Translate any English fragment from the report into Chinese.
- NEVER mix Chinese and English in the same answer. This is the single most important rule.
- Section labels: use the user's language too. "Executive Summary" / "Diagnosis" / "30-Day Action Plan" in English; "执行摘要 / 诊断报告 / 30 天行动计划" in Chinese.

YOUR JOB:
- Answer the user's question SPECIFICALLY using the report below as ground truth.
- Quote the section evidence in the user's language (translate the report excerpt if needed).
- If the question asks about something NOT covered by the report, say so plainly. Don't fabricate findings.
- Keep answers under 200 words unless the user explicitly asks for depth.
- Voice: founder-to-founder, concise, no marketing fluff, no emojis.
- If the user is challenging a finding ("are you sure about X?"), acknowledge their concern, name the data source we used, and explain confidence.

WHAT THE REPORT CONTAINS:
- Executive Summary (high-level findings)
- Diagnosis Report (full breakdown of issues, channels, SEO/GEO state)
- 30-Day Action Plan (prioritized recommendations)
- Site-data summary (homepage text, traffic stats, pricing, social, GitHub presence)

WHEN ANSWERING, ALWAYS:
1. Reference which section supports your answer (in the user's language).
2. If the report and the user's claim conflict, name the source we used.
3. If a number isn't in the report, say "not in this audit" / "审计中没有覆盖" — never guess.

NEVER:
- Invent metrics or rankings not in the report.
- Recommend specific tools/vendors not mentioned in the report unless the user asked.
- Speculate about competitor pricing / revenue / team size beyond what the report contains.
- Mix languages in one answer."""


_SYSTEM_PROMPT_ZH = """你是一名增长顾问，正在回答一份已经交付给用户的 Growth Audit 报告的追问。

🌐 语言规则 — 最重要：
- 检测用户问题的语言，**只用那一种语言**回答。
- 问题是中文 → 100% 中文回答。报告里的英文片段必须翻译成自然中文。**不允许夹杂英文**。
- 问题是英文 → 100% 英文回答。报告里的中文必须翻译成自然英文。
- 同一条回答里**禁止中英混杂**。这是最重要的规则。
- 章节名也用用户语言：中文用 "执行摘要 / 诊断报告 / 30 天行动计划"，英文用 "Executive Summary / Diagnosis / 30-Day Action Plan"。

任务：
- 用下面的报告作为唯一事实基准回答用户问题。
- 引用证据时，按用户语言把报告片段翻译过去（不直接粘原文）。
- 报告里没覆盖的问题，直说"审计中没有覆盖"，不允许编。
- 控制在 200 字以内，除非用户明确要详细。
- 语气：founder 对 founder，简洁，不用营销话术，不用 emoji。
- 用户挑战某个结论时（"你确定吗？"），承认顾虑、指出我们用的数据源、解释置信度。

报告包含：
- 执行摘要（高层发现）
- 诊断报告（问题、渠道、SEO/GEO 全面拆解）
- 30 天行动计划（优先级排序的建议）
- 抓站数据摘要（homepage、traffic、定价、社交、GitHub）

回答时必须：
1. 指明引自哪个章节（用用户语言）。
2. 报告和用户说法冲突时，指明我们用的数据源。
3. 报告里没有的数字直说"审计中没有覆盖"，**不要猜**。

禁止：
- 编报告里没有的指标。
- 推荐报告里没提的工具/厂商，除非用户主动问。
- 推测竞品定价/营收/团队规模超过报告内容。
- 同一回答中英混杂。"""


def _detect_question_lang(text: str) -> str:
    """Crude but effective: count CJK chars vs ASCII letters. CJK majority
    → Chinese, else English. Mixed short prompts (like 'PMF 怎么验证')
    that have any CJK get Chinese — that matches user intent better than
    falling through to English."""
    if not text:
        return "en"
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    if cjk >= 2:
        return "zh"
    return "en"


def _shrink_md(md: Optional[str], cap: int = 3000) -> str:
    """Trim a markdown section to cap chars, preserving structure."""
    if not md:
        return "(not available)"
    md = md.strip()
    if len(md) <= cap:
        return md
    # Try to cut on a paragraph break near the cap.
    cut = md.rfind("\n\n", 0, cap)
    if cut < cap * 0.7:
        cut = cap
    return md[:cut].rstrip() + "\n\n…(truncated for length — full section available in the report viewer above)"


def build_prompt(question: str, history: list, context: dict) -> list:
    """Compose the OpenAI-style messages array for DeepSeek.

    history is a list of [{role:'user'|'assistant', content:str}] up to ~6 turns.
    """
    reports = context.get("reports") or {}
    sd      = context.get("site_data_summary") or {}

    # Compact site data — keep only the diff-relevant fields.
    sd_str = _json.dumps({
        "url":           context.get("url"),
        "product_name":  context.get("product_name"),
        "homepage_title":    (sd.get("homepage") or {}).get("title"),
        "homepage_text_excerpt": ((sd.get("homepage") or {}).get("text") or "")[:1500],
        "traffic":       sd.get("traffic") or sd.get("traffic_stats"),
        "pricing":       sd.get("pricing") or sd.get("pricing_page"),
        "social":        sd.get("social"),
        "github":        sd.get("github_oss") or sd.get("github"),
        "producthunt":   sd.get("producthunt"),
    }, ensure_ascii=False, default=str)[:2500]

    report_block = (
        f"## Executive Summary\n{_shrink_md(reports.get('executive_summary'), 1800)}\n\n"
        f"## Diagnosis Report\n{_shrink_md(reports.get('diagnosis_report'), 3500)}\n\n"
        f"## 30-Day Action Plan\n{_shrink_md(reports.get('action_plan'), 2500)}\n\n"
        f"## Site Data Summary (raw)\n{sd_str}"
    )

    lang = _detect_question_lang(question)
    sys_prompt = _SYSTEM_PROMPT_ZH if lang == "zh" else _SYSTEM_PROMPT_EN
    # Append a final reinforcement line so the model can't forget mid-answer.
    lang_lock = (
        "\n\n🌐 提醒：用户问题判定为**中文**，整段回答必须 100% 中文，不允许夹任何英文单词或短语。"
        if lang == "zh"
        else "\n\n🌐 Reminder: question detected as **English**, answer must be 100% English — translate any Chinese phrase from the report, do not leave CJK characters."
    )
    messages = [
        {"role": "system", "content": sys_prompt + "\n\n=== REPORT START ===\n" + report_block + "\n=== REPORT END ===" + lang_lock},
    ]

    # Trim history to last 6 turns to keep context budget reasonable.
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:2000]})

    messages.append({"role": "user", "content": question[:1000]})
    return messages


_SECTION_HINTS = {
    "exec": ["executive summary", "exec summary", "tl;dr", "headline"],
    "diag": ["diagnosis", "channel mix", "seo audit", "issues identified"],
    "plan": ["action plan", "30-day plan", "task 1", "task 2", "next steps"],
}


def _detect_cited_section(answer: str) -> Optional[str]:
    a = (answer or "").lower()
    hits = []
    for key, needles in _SECTION_HINTS.items():
        if any(n in a for n in needles):
            hits.append(key)
    if not hits:
        return None
    if len(hits) > 1:
        return "mixed"
    return hits[0]


# ─── DeepSeek call ───────────────────────────────────────────────────────────


async def _call_deepseek(messages: list) -> tuple[Optional[str], dict]:
    """Returns (answer_text, meta) where meta has latency_ms, input_tokens, output_tokens."""
    # Plan 0: OrcaRouter free tier (same deepseek-v4-flash, $0) — falls through
    # to the paid DeepSeek-direct call below on any failure.
    from .orcarouter import try_orca
    t0 = time.monotonic()
    orca = await try_orca(messages, max_tokens=500, temperature=0.3, title="Analook Audit QA")
    if orca and orca.get("content"):
        return orca["content"].strip(), {
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "source": orca.get("source"),
        }
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return None, {"error": "DEEPSEEK_API_KEY not configured"}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model":       os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                    "messages":    messages,
                    "temperature": 0.3,   # low — we want grounded, not creative
                    "max_tokens":  500,
                },
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            if r.status_code != 200:
                return None, {"error": f"HTTP {r.status_code}: {r.text[:200]}", "latency_ms": latency_ms}
            data = r.json()
            # `content` is the final answer; DeepSeek V4 puts chain-of-thought in
            # a separate `reasoning_content` field, which we deliberately ignore.
            answer = ((data.get("choices") or [{}])[0].get("message", {}) or {}).get("content")
            if not answer:
                return None, {"error": "empty content", "latency_ms": latency_ms}
            usage  = data.get("usage") or {}
            return answer.strip(), {
                "latency_ms":     latency_ms,
                "input_tokens":   usage.get("prompt_tokens"),
                "output_tokens":  usage.get("completion_tokens"),
            }
    except Exception as e:
        return None, {"error": str(e)[:200], "latency_ms": int((time.monotonic() - t0) * 1000)}


# ─── Rate-limiting ──────────────────────────────────────────────────────────


def _hourly_limit_for(plan: Optional[str], has_user: bool) -> int:
    if not has_user:
        return RATE_LIMIT_ANON_HOUR
    p = (plan or "free").lower()
    if p in ("pro", "autopilot"):
        return RATE_LIMIT_PRO_HOUR
    if p in ("team", "autopilot_team", "enterprise"):
        return RATE_LIMIT_TEAM_HOUR
    return RATE_LIMIT_FREE_HOUR


async def check_and_count_rate(visitor_id: str, user_id: Optional[str], plan: Optional[str]) -> tuple[bool, int, int]:
    """Returns (allowed, used_this_hour, limit). Persists nothing — counter
    is read from audit_qa.created_at scope.
    """
    limit = _hourly_limit_for(plan, has_user=bool(user_id))
    try:
        from .supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return True, 0, limit
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        q = sb.table("audit_qa").select("id", count="exact").gte("created_at", cutoff)
        if user_id:
            q = q.eq("user_id", user_id)
        else:
            q = q.eq("visitor_id", visitor_id or "").is_("user_id", "null")
        result = q.execute()
        used = result.count if result.count is not None else len(result.data or [])
        return (used < limit), used, limit
    except Exception as e:
        log.warning("rate check failed (failing open): %s", e)
        return True, 0, limit


# ─── Persistence ─────────────────────────────────────────────────────────────


def persist_qa(
    *, audit_job_id: str, user_id: Optional[str], visitor_id: Optional[str],
    question: str, answer: str, cited_section: Optional[str],
    latency_ms: Optional[int], input_tokens: Optional[int], output_tokens: Optional[int],
    refused: bool = False, refused_reason: Optional[str] = None,
) -> None:
    """Best-effort persist. Failures here don't break the user's response."""
    try:
        from .supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return
        sb.table("audit_qa").insert({
            "audit_job_id":  audit_job_id,
            "user_id":       user_id,
            "visitor_id":    visitor_id,
            "question":      question[:2000],
            "answer":        (answer or "")[:5000],
            "cited_section": cited_section,
            "latency_ms":    latency_ms,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "refused":       refused,
            "refused_reason":refused_reason,
        }).execute()
    except Exception as e:
        log.warning("audit_qa persist failed (continuing): %s", e)


# ─── Top-level orchestrator ──────────────────────────────────────────────────


async def answer_question(
    *,
    job_id: str,
    question: str,
    history: Optional[list] = None,
    user_id: Optional[str] = None,
    visitor_id: Optional[str] = None,
    plan: Optional[str] = None,
    jobs_dict: Optional[dict] = None,
) -> dict:
    """Returns the JSON payload sent back to the client."""
    question = (question or "").strip()
    if not question:
        return {"error": "Question is empty.", "status": "empty"}
    if len(question) > 1000:
        question = question[:1000]

    # Rate gate
    allowed, used, limit = await check_and_count_rate(visitor_id or "", user_id, plan)
    if not allowed:
        persist_qa(
            audit_job_id=job_id, user_id=user_id, visitor_id=visitor_id,
            question=question, answer="", cited_section=None,
            latency_ms=None, input_tokens=None, output_tokens=None,
            refused=True, refused_reason="rate_limit",
        )
        return {
            "error":  f"You've used {used}/{limit} questions this hour. Free tier resets hourly; upgrade for higher limits.",
            "status": "rate_limited",
            "used":   used,
            "limit":  limit,
        }

    # Context
    ctx = await fetch_audit_context(job_id, jobs_dict)
    if not ctx:
        return {"error": "Couldn't find that audit, or it's still processing.", "status": "not_found"}

    # LLM
    messages = build_prompt(question, history or [], ctx)
    answer, meta = await _call_deepseek(messages)
    if not answer:
        return {"error": meta.get("error") or "Language model unavailable.", "status": "llm_error"}

    cited = _detect_cited_section(answer)
    persist_qa(
        audit_job_id=job_id, user_id=user_id, visitor_id=visitor_id,
        question=question, answer=answer, cited_section=cited,
        latency_ms=meta.get("latency_ms"),
        input_tokens=meta.get("input_tokens"),
        output_tokens=meta.get("output_tokens"),
    )

    return {
        "answer":         answer,
        "cited_section":  cited,
        "latency_ms":     meta.get("latency_ms"),
        "used":           used + 1,
        "limit":          limit,
        "status":         "ok",
    }
