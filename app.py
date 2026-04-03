"""竞品调研 MVP 工具 — FastAPI 后端"""
import asyncio
import json as _json
import os
import time
import uuid
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
from urllib.parse import urlparse

from modules.website import analyze_website
from modules.social import analyze_social, run_launch_propagation
from modules.growth_analysis import analyze_growth_deep
from modules.traffic import analyze_traffic
from modules.dataforseo import analyze_domain
from modules.producthunt import analyze_producthunt
from modules.ai_summary import generate_ai_summary, generate_ai_summary_from_text
from modules.report import generate_report, report_to_markdown
from modules.traffic_peaks import analyze_traffic_peaks
from modules.growth_strategy import recommend_playbooks, build_qa_playbook_context
from modules.pricing import analyze_pricing
from modules.github_oss import analyze_github_oss
from modules.pr_news import analyze_pr_news
from modules.funding import analyze_funding
from modules.bizmodel import analyze_bizmodel
from modules.supabase_client import (
    verify_token_and_get_user, deduct_credit,
    get_user_profile, save_report_to_db,
)

app = FastAPI(title="Analook — 竞品情报分析")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

async def _extract_user(request: Request) -> dict | None:
    """从 Authorization: Bearer <token> 提取并验证用户，失败返回 None。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    return await verify_token_and_get_user(token)


async def _require_credits(request: Request):
    """
    检查用户积分。返回 (user, error_response)。
    - user = None & error = None  → Supabase 未配置，放行（开发模式）
    - user = dict & error = None  → 验证成功，积分已扣减
    - user = None & error = JSONResponse → 拦截，直接返回给客户端
    """
    user = await _extract_user(request)

    # Supabase 未配置（本地开发） → 放行
    from modules.supabase_client import get_supabase
    if not get_supabase():
        return None, None

    # 未登录 → 要求登录
    if not user:
        return None, JSONResponse(
            {"error": "请先登录", "code": "AUTH_REQUIRED"},
            status_code=401,
        )

    # 扣减积分（原子操作，余额不足时返回 False）
    ok = await deduct_credit(user["id"])
    if not ok:
        return None, JSONResponse(
            {"error": "积分不足，请升级套餐或等待下月重置", "code": "CREDITS_EXHAUSTED"},
            status_code=402,
        )

    return user, None

# In-memory store for analysis jobs
jobs: dict = {}

# ---------------------------------------------------------------------------
# Domain-level result cache (in-memory, single-instance)
# key = domain string, value = {"timestamp": float, "job": dict}
# ---------------------------------------------------------------------------
DOMAIN_CACHE_TTL = 30 * 60  # 30 minutes
_domain_cache: dict = {}

JOB_TIMEOUT = 5 * 60  # 5 minutes max per analysis job


class AnalyzeRequest(BaseModel):
    url: str
    product_name: Optional[str] = None


class TextAnalyzeRequest(BaseModel):
    text: str
    product_name: Optional[str] = "产品"


@app.post("/api/analyze")
async def start_analysis(req: AnalyzeRequest, bg: BackgroundTasks, request: Request):
    # ── 积分检查（Auth 中间件）──────────────────────────────────────────────
    user, err = await _require_credits(request)
    if err:
        return err

    job_id = str(uuid.uuid4())[:8]

    # Auto-detect product name from domain if not provided
    domain = urlparse(req.url if req.url.startswith("http") else f"https://{req.url}").netloc
    if not domain:
        domain = req.url.replace("https://", "").replace("http://", "").split("/")[0]
    import re as _re
    _brand = _re.sub(r'^www\.', '', domain.lower())
    _brand = _re.sub(r'\.[a-z]{2,6}$', '', _brand)   # strip any TLD (.pro, .com, .io, .ai, .dev…)
    product_name = req.product_name or _brand.replace("-", " ").replace("_", " ").capitalize()

    # --- Domain cache: return cached result if available and fresh ---
    cache_key = domain.lower().replace("www.", "")
    cached = _domain_cache.get(cache_key)
    if cached and (time.time() - cached["timestamp"]) < DOMAIN_CACHE_TTL:
        cached_job = cached["job"]
        jobs[job_id] = {
            "status": "completed",
            "product_name": product_name,
            "url": req.url if req.url.startswith("http") else f"https://{req.url}",
            "progress": {k: "done" for k in cached_job.get("progress", {})},
            "results": cached_job.get("results", {}),
            "report": cached_job.get("report"),
            "markdown": cached_job.get("markdown"),
            "_cached": True,
        }
        _persist_report(job_id, jobs[job_id])
        return {"job_id": job_id, "status": "started", "cached": True}
    
    jobs[job_id] = {
        "status": "running",
        "product_name": product_name,
        "url": req.url if req.url.startswith("http") else f"https://{req.url}",
        "user_id": user["id"] if user else None,       # ← 记录报告归属人
        "cancelled": False,
        "progress": {
            "website": "pending",
            "social": "pending",
            "propagation": "pending",
            "traffic": "pending",
            "pricing": "pending",
            "traffic_peaks": "pending",
            "growth_analysis": "pending",
            "report": "pending",
            "pr_news": "pending",
        },
        "results": {},
        "report": None,
        "markdown": None,
    }

    bg.add_task(_run_analysis_with_timeout, job_id)
    return {"job_id": job_id, "status": "started"}


@app.post("/api/analyze-text")
async def start_text_analysis(req: TextAnalyzeRequest, bg: BackgroundTasks):
    """分析用户提供的文字描述（无需网站 URL）"""
    job_id = str(uuid.uuid4())[:8]
    name = (req.product_name or "产品").strip()
    jobs[job_id] = {
        "status": "running",
        "product_name": name,
        "url": "—",
        "mode": "text",
        "cancelled": False,
        "progress": {
            "website": "done",
            "social": "done",
            "propagation": "done",
            "traffic": "done",
            "traffic_peaks": "done",
            "growth_analysis": "done",
            "report": "pending",
        },
        "results": {},
        "report": None,
        "markdown": None,
    }
    bg.add_task(_run_text_analysis, job_id, req.text)
    return {"job_id": job_id, "status": "started"}


@app.post("/api/analyze-pdf")
async def start_pdf_analysis(
    file: UploadFile = File(...),
    product_name: str = Form(default="产品"),
):
    """分析上传的 PDF 文件（pitch deck、产品文档等）"""
    job_id = str(uuid.uuid4())[:8]
    name = (product_name or file.filename or "产品").strip()

    # Extract text from PDF
    try:
        pdf_bytes = await file.read()
        text = _extract_pdf_text(pdf_bytes)
    except Exception as e:
        return JSONResponse({"error": f"PDF 解析失败: {str(e)[:100]}"}, status_code=400)

    if not text.strip():
        return JSONResponse({"error": "PDF 内容为空，无法解析"}, status_code=400)

    jobs[job_id] = {
        "status": "running",
        "product_name": name,
        "url": "—",
        "mode": "pdf",
        "cancelled": False,
        "progress": {
            "website": "done",
            "social": "done",
            "propagation": "done",
            "traffic": "done",
            "traffic_peaks": "done",
            "growth_analysis": "done",
            "report": "pending",
        },
        "results": {"pdf_pages": text.count("\n")},
        "report": None,
        "markdown": None,
    }
    asyncio.create_task(_run_text_analysis(job_id, text))
    return {"job_id": job_id, "status": "started"}


@app.post("/api/cancel/{job_id}")
async def cancel_job(job_id: str):
    """取消正在进行的分析任务"""
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    if job["status"] == "running":
        job["cancelled"] = True
        job["status"] = "cancelled"
        # Mark all pending/running steps as done so frontend stops spinning
        for k in job["progress"]:
            if job["progress"][k] in ("pending", "running"):
                job["progress"][k] = "done"
    return {"status": job["status"]}


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes. Uses pypdf if available, else falls back to raw extraction."""
    try:
        import io
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages[:50]:  # max 50 pages
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
        return "\n\n".join(pages)
    except Exception as e:
        raise ValueError(f"无法解析 PDF: {e}")


async def _run_analysis_with_timeout(job_id: str):
    """Run analysis with a global 5-minute timeout. Returns partial results on timeout."""
    try:
        await asyncio.wait_for(_run_analysis(job_id), timeout=JOB_TIMEOUT)
    except asyncio.TimeoutError:
        job = jobs.get(job_id)
        if job:
            job["status"] = "completed"
            # Mark any still-pending steps as timed out
            for k in job["progress"]:
                if job["progress"][k] in ("pending", "running"):
                    job["progress"][k] = "done"
            # If no report yet, build a partial one
            if not job.get("report"):
                product_name = job["product_name"]
                url = job["url"]
                try:
                    from modules.report import generate_report, report_to_markdown
                    report = generate_report(
                        product_name, url,
                        job["results"].get("website", {}),
                        job["results"].get("social", {}),
                        job["results"].get("traffic", {}),
                        job["results"].get("producthunt", {}),
                        job["results"].get("ai_summary", {"success": False, "content": "⏱️ 分析超时，此模块未能完成。", "source": "timeout"}),
                    )
                    job["report"] = report
                    job["markdown"] = report_to_markdown(report)
                except Exception:
                    job["report"] = {"meta": {"product_name": product_name, "url": url, "note": "partial"}, "sections": job["results"]}
                    job["markdown"] = f"# {product_name} 竞品调研报告（部分）\n\n> 分析超时，以下为已完成模块的数据。\n"
            _persist_report(job_id, job)


async def _run_analysis(job_id: str):
    job = jobs[job_id]
    url = job["url"]
    domain = urlparse(url).netloc
    product_name = job["product_name"]

    def _cancelled():
        return job.get("cancelled", False)

    # ================================================================
    # Phase 1: Website + Traffic/SEO + ProductHunt + Social (all parallel)
    # ================================================================
    job["progress"]["website"] = "running"
    job["progress"]["social"] = "running"
    job["progress"]["traffic"] = "running"

    async def _t(coro, timeout):
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            return {"error": f"timeout after {timeout}s", "_timed_out": True}

    # Phase 1: all modules run in parallel
    job["progress"]["pr_news"] = "running"
    results_phase1 = await asyncio.gather(
        _t(analyze_website(url), 40),
        _t(analyze_domain(domain), 20),
        _t(analyze_producthunt(domain, product_name), 25),
        _t(analyze_social(domain, product_name, website_social_links={}), 22),  # was 35s
        _t(analyze_pricing(url, product_name), 20),
        _t(analyze_github_oss(domain, product_name, {}), 25),                  # Phase 1, no website hints
        _t(analyze_pr_news(domain, product_name), 18),
        _t(analyze_funding(domain, product_name), 15),
        return_exceptions=True,
    )

    if _cancelled(): return

    job["results"]["website"] = results_phase1[0] if not isinstance(results_phase1[0], Exception) else {"error": str(results_phase1[0])}
    job["progress"]["website"] = "error" if isinstance(results_phase1[0], Exception) else "done"

    job["results"]["traffic"] = results_phase1[1] if not isinstance(results_phase1[1], Exception) else {"error": str(results_phase1[1])}
    job["progress"]["traffic"] = "error" if isinstance(results_phase1[1], Exception) else "done"

    job["results"]["producthunt"] = results_phase1[2] if not isinstance(results_phase1[2], Exception) else {"error": str(results_phase1[2])}

    job["results"]["social"] = results_phase1[3] if not isinstance(results_phase1[3], Exception) else {"error": str(results_phase1[3])}
    job["progress"]["social"] = "error" if isinstance(results_phase1[3], Exception) else "done"

    job["results"]["pricing"] = results_phase1[4] if not isinstance(results_phase1[4], Exception) else {"error": str(results_phase1[4])}
    job["progress"]["pricing"] = "error" if isinstance(results_phase1[4], Exception) else "done"

    job["results"]["github_oss"] = results_phase1[5] if isinstance(results_phase1[5], dict) else {}
    job["results"]["pr_news"]   = results_phase1[6] if isinstance(results_phase1[6], dict) else {}
    job["progress"]["pr_news"]  = "done"
    job["results"]["funding"]   = results_phase1[7] if isinstance(results_phase1[7], dict) else {}

    # Refine product_name from page title (preserves correct casing e.g. AFFiNE, Linear, Notion)
    _website_res = job["results"].get("website", {})
    _page_title = (_website_res.get("current_site", {}).get("title") or "").strip()
    if _page_title:
        import re as _re2
        # Extract first segment before " - " / " | " / " — " / " · "
        _first_seg = _re2.split(r'\s*[-|—·]\s*', _page_title)[0].strip()
        # Use it only if it's plausibly just the brand name (1-4 words, ≤40 chars)
        if _first_seg and len(_first_seg) <= 40 and len(_first_seg.split()) <= 4:
            # Check it resembles the domain brand (case-insensitive match)
            _brand_lower = product_name.lower().replace(" ", "")
            if _brand_lower in _first_seg.lower().replace(" ", ""):
                product_name = _first_seg
                job["product_name"] = product_name

    # Prepare for Phase 1.5 parallel tasks
    _gh_result = job["results"].get("github_oss", {})
    _ws_social = (_website_res.get("current_site", {}) or {}).get("social_links", {})
    import re as _re3
    _brand_lower = _re3.sub(r'\.[a-z]{2,6}$', '', domain.lower().replace("www.", ""))
    _gh_org = _gh_result.get("owner", "")
    _tiktok_hint  = job["results"].get("social", {}).get("_tiktok_hint")
    _facebook_hint = job["results"].get("social", {}).get("_facebook_hint")

    # Phase 1.5: Slow Apify channels (TikTok 55s + Facebook 65s) run in parallel with
    # conditional retries for github_oss and funding — total bounded by 65s
    from modules.social import _deep_tiktok_apify, _deep_facebook_apify

    async def _slow_tiktok():
        try:
            res = await asyncio.wait_for(
                _deep_tiktok_apify(_brand_lower, product_name, handle_hint=_tiktok_hint), timeout=55
            )
            soc = job["results"].setdefault("social", {})
            soc.setdefault("channels", {})["tiktok"] = res if isinstance(res, dict) else {"platform": "TikTok", "detected": False}
        except Exception:
            pass

    async def _slow_facebook():
        try:
            res = await asyncio.wait_for(
                _deep_facebook_apify(_brand_lower, product_name, handle_hint=_facebook_hint), timeout=65
            )
            soc = job["results"].setdefault("social", {})
            soc.setdefault("channels", {})["facebook"] = res if isinstance(res, dict) else {"platform": "Facebook", "detected": False}
        except Exception:
            pass

    async def _retry_github():
        if not _gh_result.get("found"):
            try:
                _gh_retry = await asyncio.wait_for(
                    analyze_github_oss(domain, product_name, _ws_social or {}), timeout=20
                )
                if isinstance(_gh_retry, dict) and _gh_retry.get("found"):
                    job["results"]["github_oss"] = _gh_retry
            except Exception:
                pass

    async def _retry_funding():
        if (not job["results"].get("funding", {}).get("found")
                and _gh_org and _gh_org.lower() != _brand_lower):
            try:
                _fund_retry = await asyncio.wait_for(
                    analyze_funding(domain, _gh_org), timeout=12
                )
                if isinstance(_fund_retry, dict) and _fund_retry.get("found"):
                    job["results"]["funding"] = _fund_retry
            except Exception:
                pass

    await asyncio.gather(
        _slow_tiktok(), _slow_facebook(), _retry_github(), _retry_funding(),
        return_exceptions=True,
    )

    # Phase 1.7: Reconcile social handles — update website social_links with
    # Brave/Apify-verified handles from the social module (fixes handle mismatches)
    _soc_channels = job["results"].get("social", {}).get("channels", {})
    _ws_cur = (_website_res.get("current_site") or {})
    _ws_social_links = _ws_cur.get("social_links") or {}
    for _platform in ("twitter", "youtube", "instagram", "tiktok", "facebook"):
        _ch = _soc_channels.get(_platform, {})
        if _ch.get("detected") and _ch.get("handle") and _ws_social_links.get(_platform):
            _verified_handle = _ch["handle"].lstrip("@")
            _ws_social_links[_platform]["handle"] = _verified_handle
            if _ch.get("url"):
                _ws_social_links[_platform]["url"] = _ch["url"]
            _ws_social_links[_platform]["verified"] = True

    # ================================================================
    # Phase 2: Propagation + Traffic Peaks (parallel, ~10s)
    # ================================================================
    async def _run_propagation():
        job["progress"]["propagation"] = "running"
        propagation = {}

        # Primary: Twitter-based propagation (requires API data)
        if job["results"].get("social", {}).get("_propagation_available"):
            propagation = await run_launch_propagation(job["results"]["social"])

        # Fallback: if Twitter data is empty/unavailable, build lightweight summary
        # from ProductHunt, GitHub, and Reddit signals
        if not propagation or propagation.get("data_mode") == "empty":
            ph  = job["results"].get("producthunt", {})
            gh  = job["results"].get("github_oss", {})
            soc = job["results"].get("social", {})
            reddit = soc.get("channels", {}).get("reddit", {})

            signals = []
            ph_votes = ph.get("votes") or ph.get("upvotes") or 0
            ph_comments = ph.get("comments", 0)
            ph_date = ph.get("featured_date") or ph.get("launch_date") or ""
            if ph_votes:
                signals.append(f"Product Hunt 上线：{ph_votes} 票，{ph_comments} 评论" + (f"（{ph_date}）" if ph_date else ""))

            gh_stars = gh.get("stars", 0)
            gh_growth = (gh.get("insights") or {}).get("peak_growth_rate") or ""
            if gh_stars:
                signals.append(f"GitHub Stars：{gh_stars:,}" + (f"，峰值增速 {gh_growth}" if gh_growth else ""))

            reddit_posts = len(reddit.get("top_posts", []))
            reddit_members = reddit.get("subreddit_members", 0)
            if reddit_posts:
                signals.append(f"Reddit 提及：{reddit_posts} 条帖子" + (f"，社区 {reddit_members:,} 成员" if reddit_members else ""))

            propagation = {
                "data_mode": "multi_channel_fallback",
                "note": "⚠️ Twitter API 不可用，以下为多渠道综合传播信号",
                "signals": signals,
                "producthunt": {"votes": ph_votes, "comments": ph_comments, "date": ph_date},
                "github": {"stars": gh_stars},
                "reddit": {"posts": reddit_posts, "members": reddit_members},
                "errors": ["Twitter top_tweets 为空，无法进行 Twitter 传播分析"],
            }

        job["results"]["propagation"] = propagation
        job["progress"]["propagation"] = "done"

    async def _run_traffic_peaks():
        job["progress"]["traffic_peaks"] = "running"
        # Pass first_seen from website analysis to filter HN results before product launch
        website_first_seen = job["results"].get("website", {}).get("first_seen", "")
        peaks = await analyze_traffic_peaks(
            product_name, domain,
            producthunt=job["results"].get("producthunt", {}),
            social=job["results"].get("social", {}),
            first_seen=website_first_seen,
        )
        job["results"]["traffic_peaks"] = peaks
        job["progress"]["traffic_peaks"] = "done"

    if _cancelled(): return

    phase2_results = await asyncio.gather(
        _run_propagation(), _run_traffic_peaks(),
        return_exceptions=True,
    )
    if isinstance(phase2_results[0], Exception):
        job["results"]["propagation"] = {"error": str(phase2_results[0])}
        job["progress"]["propagation"] = "error"
    if isinstance(phase2_results[1], Exception):
        job["results"]["traffic_peaks"] = {"error": str(phase2_results[1])}
        job["progress"]["traffic_peaks"] = "error"

    if _cancelled(): return

    # ================================================================
    # Phase 3: Growth analysis + AI summary
    # ================================================================
    # Bizmodel is synchronous — runs instantly using already-collected data
    try:
        job["results"]["bizmodel"] = analyze_bizmodel(
            domain, product_name,
            pricing=job["results"].get("pricing", {}),
            traffic=job["results"].get("traffic", {}),
            github_oss=job["results"].get("github_oss", {}),
            producthunt=job["results"].get("producthunt", {}),
            funding=job["results"].get("funding", {}),
        )
    except Exception:
        job["results"]["bizmodel"] = {"found": False}

    job["progress"]["growth_analysis"] = "running"
    try:
        growth_deep = analyze_growth_deep(
            product_name, url,
            job["results"].get("website", {}),
            job["results"].get("social", {}),
            job["results"].get("traffic", {}),
            job["results"].get("producthunt", {}),
            propagation=job["results"].get("propagation", {}),
        )
        job["results"]["growth_analysis"] = growth_deep
        job["progress"]["growth_analysis"] = "done"
    except Exception as growth_err:
        job["results"]["growth_analysis"] = {"error": str(growth_err)}
        job["progress"]["growth_analysis"] = "error"

    try:
        early_strategy = recommend_playbooks({
            "sections": {
                "website_analysis": job["results"].get("website", {}),
                "social_media": job["results"].get("social", {}),
                "traffic_analysis": job["results"].get("traffic", {}),
                "producthunt": job["results"].get("producthunt", {}),
                "growth_analysis": job["results"].get("growth_analysis", {}),
                "traffic_peaks": job["results"].get("traffic_peaks", {}),
            },
            "meta": {"product_name": product_name, "url": url},
        })
        job["results"]["growth_strategy"] = early_strategy
    except Exception:
        early_strategy = {}
        job["results"]["growth_strategy"] = {}

    if _cancelled(): return

    try:
        ai = await generate_ai_summary(
            product_name, url,
            job["results"].get("website", {}),
            job["results"].get("social", {}),
            job["results"].get("traffic", {}),
            job["results"].get("producthunt", {}),
            growth_strategy=early_strategy,
            growth_analysis=job["results"].get("growth_analysis", {}),
            traffic_peaks=job["results"].get("traffic_peaks", {}),
            pricing=job["results"].get("pricing", {}),
            github_oss=job["results"].get("github_oss", {}),
        )
        job["results"]["ai_summary"] = ai
    except Exception as ai_err:
        ai = {"success": False, "content": "", "note": f"AI 分析异常: {str(ai_err)[:100]}", "source": "error"}
        job["results"]["ai_summary"] = ai

    # ================================================================
    # Phase 4: Report generation
    # ================================================================
    job["progress"]["report"] = "running"
    try:
        report = generate_report(
            product_name, url,
            job["results"].get("website", {}),
            job["results"].get("social", {}),
            job["results"].get("traffic", {}),
            job["results"].get("producthunt", {}),
            ai,
            growth_deep=job["results"].get("growth_analysis", {}),
            traffic_peaks=job["results"].get("traffic_peaks", {}),
            propagation=job["results"].get("propagation", {}),
        )

        growth_strategy = job["results"].get("growth_strategy", {})
        report["sections"]["growth_strategy"] = growth_strategy
        report["sections"]["pricing"] = job["results"].get("pricing", {})
        report["sections"]["github_oss"] = job["results"].get("github_oss", {})
        report["sections"]["pr_news"]    = job["results"].get("pr_news", {})
        report["sections"]["funding"]    = job["results"].get("funding", {})
        report["sections"]["bizmodel"]   = job["results"].get("bizmodel", {})

        job["report"] = report
        try:
            job["markdown"] = report_to_markdown(report)
        except Exception:
            job["markdown"] = f"# {product_name} 竞品调研报告\n\n> Markdown 导出出错，请查看在线报告。\n"
        job["progress"]["report"] = "done"
    except Exception as e:
        job["progress"]["report"] = "error"

    job["status"] = "completed"

    _persist_report(job_id, job)

    cache_key = domain.lower().replace("www.", "")
    _domain_cache[cache_key] = {"timestamp": time.time(), "job": job}


async def _run_text_analysis(job_id: str, text: str):
    """AI-only analysis from text description (no URL scraping)"""
    job = jobs[job_id]
    product_name = job["product_name"]
    job["progress"]["report"] = "running"
    try:
        ai = await generate_ai_summary_from_text(product_name, text)
        job["results"]["ai_summary"] = ai

        report = {
            "meta": {"product_name": product_name, "url": "—", "mode": job.get("mode", "text"), "generated_at": time.strftime("%Y-%m-%d")},
            "sections": {
                "ai_summary": ai,
                "website_analysis": {},
                "traffic_analysis": {},
                "social_media": {},
                "producthunt": {},
                "growth_analysis": {},
                "traffic_peaks": {},
                "growth_strategy": {},
            },
        }
        job["report"] = report
        job["markdown"] = f"# {product_name} 产品分析报告\n\n> 基于用户提供的描述材料生成\n\n---\n\n{ai.get('content', '')}"
        job["progress"]["report"] = "done"
    except Exception as e:
        job["progress"]["report"] = "error"
        job["results"]["ai_summary"] = {"success": False, "content": "", "note": str(e)[:200], "source": "error"}
        job["report"] = {"meta": {"product_name": product_name, "url": "—"}, "sections": {}}
        job["markdown"] = f"# {product_name}\n\n> 分析失败: {str(e)[:100]}\n"

    job["status"] = "completed"
    _persist_report(job_id, job)


REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


def _persist_report(job_id: str, job: dict):
    """Save completed report to disk (JSON) and async-sync to Supabase."""
    # 1. 本地 JSON（保持原有行为）
    try:
        data = {
            "job_id": job_id,
            "product_name": job.get("product_name", ""),
            "url": job.get("url", ""),
            "report": job.get("report"),
            "markdown": job.get("markdown"),
        }
        path = os.path.join(REPORTS_DIR, f"{job_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, default=str)
    except Exception:
        pass

    # 2. 同步写入 Supabase reports 表（异步，不阻塞返回）
    report = job.get("report")
    if report:
        user_id = job.get("user_id")
        # Free 套餐强制 is_public=True；Pro/Business 默认也先 public（Stripe 接好后再开关）
        asyncio.create_task(save_report_to_db(
            job_id=job_id,
            user_id=user_id,
            url=job.get("url", ""),
            product_name=job.get("product_name", ""),
            report=report,
            markdown=job.get("markdown", ""),
            is_public=True,
        ))


@app.get("/api/me")
async def get_me(request: Request):
    """返回当前登录用户的 profile（积分余额、套餐类型等）。未登录返回 401。"""
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "未登录", "code": "AUTH_REQUIRED"}, status_code=401)
    profile = await get_user_profile(user["id"])
    if not profile:
        # profile 不存在（极少数情况，触发器可能延迟）
        return JSONResponse({
            "id": user["id"],
            "email": user["email"],
            "plan_type": "free",
            "credits_balance": 0,
        })
    return profile


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return {
        "status": job["status"],
        "progress": job["progress"],
        "product_name": job["product_name"],
        "mode": job.get("mode", "url"),
    }


@app.get("/api/report/{job_id}")
async def get_report(job_id: str):
    job = jobs.get(job_id)
    if job and job.get("report"):
        return job["report"]
    path = os.path.join(REPORTS_DIR, f"{job_id}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if data.get("report"):
            return data["report"]
    if job and not job.get("report"):
        return JSONResponse({"error": "Report not ready", "status": job["status"]}, status_code=202)
    return JSONResponse({"error": "Job not found"}, status_code=404)


@app.get("/api/export/{job_id}")
async def export_markdown(job_id: str):
    job = jobs.get(job_id)
    markdown = None
    product_name = "report"
    if job and job.get("markdown"):
        markdown = job["markdown"]
        product_name = job.get("product_name", "report")
    else:
        path = os.path.join(REPORTS_DIR, f"{job_id}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            markdown = data.get("markdown")
            product_name = data.get("product_name", "report")
    if not markdown:
        return JSONResponse({"error": "Report not ready"}, status_code=202)
    from urllib.parse import quote
    safe_name = quote(f"{product_name}_竞品调研.md")
    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )


@app.get("/api/share/{job_id}")
async def get_share_info(job_id: str):
    job = jobs.get(job_id)
    product_name = None
    url = None
    if job:
        product_name = job.get("product_name")
        url = job.get("url")
    else:
        path = os.path.join(REPORTS_DIR, f"{job_id}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            product_name = data.get("product_name")
            url = data.get("url")
    if not product_name:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    from urllib.parse import quote_plus
    base_url = f"/report/{job_id}"
    utm = f"utm_source=gingiris_tool&utm_medium=share&utm_campaign=competitive_analysis&utm_content={quote_plus(product_name)}"
    share_url = f"{base_url}?{utm}"

    return {
        "job_id": job_id,
        "product_name": product_name,
        "share_url": share_url,
        "utm_params": utm,
        "share_text": f"🔍 {product_name} 竞品调研报告 — Powered by Analook",
    }


@app.get("/report/{job_id}")
async def shared_report_page(job_id: str):
    return FileResponse("static/index.html")


class QARequest(BaseModel):
    job_id: str
    question: str


@app.post("/api/qa")
async def ask_question(req: QARequest):
    job = jobs.get(req.job_id)
    if not job or not job["report"]:
        return JSONResponse({"error": "Report not ready"}, status_code=202)

    from modules.ai_summary import _build_context, _call_llm
    from modules.web_search import search_and_summarize

    context = _build_context(
        job["product_name"], job["url"],
        job["results"].get("website", {}),
        job["results"].get("social", {}),
        job["results"].get("traffic", {}),
        job["results"].get("producthunt", {}),
    )
    prev_insights = job["results"].get("ai_summary", {}).get("content", "")

    triggers = ["复盘", "怎么做", "如何", "案例", "策略", "时间线", "历史", "故事", "经历", "方法", "用户", "interview", "100", "决策", "做对", "为什么", "增长", "渠道", "launch", "发布", "融资", "团队", "创始人", "起步", "早期"]
    needs_search = any(t in req.question for t in triggers)

    web_context = ""
    search_results = []
    if needs_search:
        web_data = await search_and_summarize(f"{job['product_name']} {req.question}")
        if web_data.get("success"):
            search_results = web_data.get("search_results", [])
            pages = web_data.get("fetched_pages", [])
            web_context = "\n\n".join(
                f"### [{p['title']}]({p['url']})\n{p.get('content', p.get('snippet', ''))[:1500]}"
                for p in pages[:3]
            )

    growth_strategy = job["results"].get("growth_strategy", {})
    playbook_context = build_qa_playbook_context(growth_strategy, req.question)

    prompt = f"""你是一位资深的出海产品增长顾问（拥有帮助产品从 0 到 60K GitHub stars 的实战经验）。用户正在分析竞品 **{job['product_name']}** ({job['url']})。

## 已有调研数据
{context}

## 之前的分析总结
{prev_insights[:1500]}
"""
    if web_context:
        prompt += f"""
## 联网搜索结果
{web_context[:4000]}
"""
    if playbook_context:
        prompt += playbook_context

    prompt += f"""

## 用户追问
{req.question}

请基于以上所有数据精准回答。如果引用了搜索结果，标注来源链接。中文回答，简洁直接，有数据支撑。"""

    result = await _call_llm(prompt)
    return {
        "answer": result.get("content", ""),
        "success": result.get("success", False),
        "web_searched": needs_search,
        "sources": [{"title": s["title"], "url": s["url"]} for s in search_results[:5]] if search_results else [],
    }


# Serve static files
app.mount("/js", StaticFiles(directory="static/js"), name="js")
app.mount("/", StaticFiles(directory="static", html=True), name="static")

