"""竞品调研 MVP 工具 — FastAPI 后端"""
import asyncio
import json as _json
import logging
import os
import time
import uuid

log = logging.getLogger(__name__)
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
from urllib.parse import urlparse

from modules.website import analyze_website
from modules.social import analyze_social, run_launch_propagation
from modules.growth_analysis import analyze_growth_deep
from modules.traffic import analyze_traffic, fetch_seoreviewtools, merge_seo_data
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
from modules.growth_audit import run_growth_audit
from modules.supabase_client import (
    verify_token_and_get_user, deduct_credit,
    get_user_profile, save_report_to_db, list_user_reports,
)
from modules.polar_payment import (
    create_checkout, handle_webhook_event, PRODUCTS, PLAN_CREDITS,
    verify_webhook_signature, mark_event_seen,
)

# Propagate the MCP sub-app's lifespan (StreamableHTTPSessionManager.run())
# through FastAPI's own lifespan — Starlette Mount does NOT call sub-app
# lifespans automatically, so without this the MCP endpoint raises
# "Task group is not initialized" on the first request.
from contextlib import asynccontextmanager as _asynccontextmanager

@_asynccontextmanager
async def _analook_lifespan(app_):
    try:
        from modules.mcp_app import mcp as _mcp
        async with _mcp.session_manager.run():
            yield
    except Exception as _mcp_lifespan_err:
        import logging as _log
        _log.getLogger(__name__).warning(
            "MCP lifespan not started (%s) — MCP endpoint will be unavailable, HTTP API unaffected",
            _mcp_lifespan_err,
        )
        yield

app = FastAPI(title="Analook — 竞品情报分析", lifespan=_analook_lifespan)


# ── apex → www canonical redirect ────────────────────────────────────────
# Single-hop 301 from analook.com → www.analook.com for SEO canonicalization.
# Fly.io (and Railway before it) terminate TLS at the edge, so request.url
# reports scheme="http" even when the client used HTTPS. We honor the
# `X-Forwarded-Proto` header (set by the edge proxy) to rebuild the URL
# with the correct scheme — otherwise Google sees a 2-hop redirect chain
# (https://apex → http://www → https://www) which dilutes link equity.
@app.middleware("http")
async def apex_to_www_redirect(request: Request, call_next):
    host = (request.headers.get("host") or "").lower().split(":")[0]
    if host == "analook.com":
        scheme = request.headers.get("x-forwarded-proto", "https").split(",")[0].strip() or "https"
        path = request.url.path
        query = f"?{request.url.query}" if request.url.query else ""
        url = f"{scheme}://www.analook.com{path}{query}"
        return JSONResponse(
            content=None,
            status_code=301,
            headers={"Location": url, "Cache-Control": "public, max-age=86400"},
        )
    return await call_next(request)


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


def _service_degraded_response() -> JSONResponse | None:
    """Return a 503 if Supabase is supposed to be configured but isn't.
    Use this at the top of any endpoint that needs Supabase to function —
    avoids returning a misleading 401 when the actual issue is server-side.
    Returns None when service is healthy or in dev mode."""
    from modules.supabase_client import get_supabase, supabase_required
    if supabase_required() and get_supabase() is None:
        return JSONResponse(
            {
                "error": "服务暂时不可用：Supabase 未正确配置",
                "code": "SERVICE_DEGRADED",
                "hint": "Backend cannot reach Supabase. Check SUPABASE_URL / SUPABASE_SERVICE_KEY.",
            },
            status_code=503,
        )
    return None


async def _require_credits(request: Request):
    """
    检查用户积分。返回 (user, error_response)。
    - user = None & error = None         → Supabase NOT configured (dev mode), 放行
    - user = dict & error = None         → 验证成功，积分已扣减
    - user = None & error = JSONResponse → 拦截
        - 503 if Supabase IS supposed to be configured but client init failed
              (this used to silently fall to dev mode and drop reports/credits)
        - 401 if Supabase OK but user not authenticated
        - 402 if user authenticated but out of credits
    """
    user = await _extract_user(request)

    from modules.supabase_client import get_supabase, supabase_required
    sb = get_supabase()

    if not sb:
        # Branch 1: dev mode (no SUPABASE_URL in env) → allow anonymous use.
        # Branch 2: SUPABASE_URL is set but client init failed → REFUSE.
        # The old code merged these two branches → reports for real users
        # were silently dropped during prod misconfig (the bug we just hit).
        if supabase_required():
            return None, JSONResponse(
                {
                    "error": "服务暂时不可用：Supabase 未正确配置",
                    "code": "SERVICE_DEGRADED",
                    "hint": "Backend cannot reach Supabase. Reports cannot be saved. "
                            "Check SUPABASE_URL / SUPABASE_SERVICE_KEY env vars.",
                },
                status_code=503,
            )
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


@app.get("/api/health")
async def health_check():
    """Service health for monitoring + frontend banner.

    Returns 200 with status='ok' when Supabase auth/persistence is wired up.
    Returns 503 with status='degraded' when Supabase is supposed to be
    configured (SUPABASE_URL is set) but the client failed to initialize —
    in that state user reports get dropped. Frontends should show a red
    banner so users know the service is degraded.
    """
    from modules.supabase_client import get_supabase, supabase_required

    keys = {
        "OPENROUTER_API_KEY":  bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
        "DEEPSEEK_API_KEY": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
        "TWITTERAPI_IO_KEY": bool(os.environ.get("TWITTERAPI_IO_KEY", "").strip()),
        "SERPAPI_KEY": bool(os.environ.get("SERPAPI_KEY", "").strip()),
        "DATAFORSEO_B64": bool(os.environ.get("DATAFORSEO_B64", "").strip()),
        "BRAVE_SEARCH_API_KEY": bool(os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()),
        "APIFY_API_TOKEN": bool(os.environ.get("APIFY_API_TOKEN", "").strip()),
        "SEOREVIEWTOOLS_KEY": bool(os.environ.get("SEOREVIEWTOOLS_KEY", "").strip()),
        "PRODUCTHUNT_TOKEN": bool(os.environ.get("PRODUCTHUNT_TOKEN", "").strip()),
        "SUPABASE_URL": bool(os.environ.get("SUPABASE_URL", "").strip()),
        "POLAR_ACCESS_TOKEN": bool(os.environ.get("POLAR_ACCESS_TOKEN", "").strip()),
        "TINYFISH_API_KEY": bool(os.environ.get("TINYFISH_API_KEY", "").strip()),
    }

    supabase_ok = get_supabase() is not None
    degraded = supabase_required() and not supabase_ok

    body = {
        "status": "degraded" if degraded else "ok",
        "supabase_ok": supabase_ok,
        "supabase_required": supabase_required(),
        "keys_configured": sum(1 for v in keys.values() if v),
        "keys": keys,
    }

    # Cache stats — surface cache_hit_rate so we can verify the TTL cache
    # is actually saving DataForSEO bills. Cheap call (one COUNT/SUM query).
    try:
        from modules.audit_cache import stats as _cache_stats
        body["audit_cache"] = await _cache_stats()
    except Exception:
        body["audit_cache"] = {"sources": {}, "available": False}
    if degraded:
        body["warning"] = (
            "SUPABASE_URL is set but client failed to initialize — "
            "reports & credits cannot be persisted. Check SUPABASE_SERVICE_KEY."
        )
    # NOTE: always return HTTP 200. Railway's platform healthcheck may be
    # pointed at this endpoint and would restart the container on 503,
    # creating a redeploy loop. Frontend / monitoring should read body.status
    # for degradation. Use /api/health/strict if you want HTTP-status-based
    # alerting from a tool that supports it.
    return body


@app.get("/api/health/strict")
async def health_check_strict():
    """Like /api/health, but returns HTTP 503 when degraded.

    Use this from external monitors (Pingdom / UptimeRobot / Healthchecks.io)
    that page on non-2xx. Do NOT point Railway's container healthcheck here
    or a misconfigured Supabase will restart the service in a loop.
    """
    body = await health_check()
    if isinstance(body, dict) and body.get("status") == "degraded":
        return JSONResponse(body, status_code=503)
    return body


@app.get("/api/health/live")
async def health_check_live():
    """Liveness probe — process is up. Always 200. Use this for Railway's
    container healthcheck if you want one."""
    return {"status": "live"}


@app.get("/api/test-llm")
async def test_llm():
    """Debug: direct LLM test to diagnose AI failure."""
    from modules.ai_summary import _call_llm
    result = await _call_llm("Reply with exactly: PONG")
    return result


@app.get("/api/test-llm-full")
async def test_llm_full():
    """Debug: test full generate_ai_summary with minimal data."""
    try:
        from modules.ai_summary import generate_ai_summary
        result = await generate_ai_summary(
            "TestProduct", "https://test.com",
            {"domain": "test.com", "current_site": {"slogan": "Test product"}},
            {"channels": {}}, {}, {},
        )
        return {"ai_success": result.get("success"), "ai_source": result.get("source"),
                "ai_len": len(result.get("content", "")), "ai_note": result.get("note", "")[:200]}
    except Exception as e:
        return {"error": str(e)[:200]}


# =========================================================================
# Payment endpoints — Polar.sh
# =========================================================================

@app.get("/api/pricing")
async def get_pricing():
    """Return pricing plans for the frontend."""
    return {
        "plans": [
            {"key": "free", "name": "Free", "price": 0, "period": "month", "credits": 2, "features": ["2 reports/month", "Basic analysis"]},
            {"key": "pro", "name": "Pro", "price": 29, "period": "month", "credits": 30, "features": ["30 reports/month", "Full analysis", "AI insights", "Export"]},
            {"key": "team", "name": "Team", "price": 99, "period": "month", "credits": 999999, "features": ["Unlimited reports", "Full analysis", "AI insights", "Export", "Priority support"]},
            {"key": "single_report", "name": "Single Report", "price": 5, "period": "once", "credits": 1, "features": ["1 full analysis report"]},
            # Growth Audit is a CREDIT-PRICED tool (10 credits / use). It's not a
            # standalone purchase tier — to run it you buy Pro ($29/mo → 3 audits/mo)
            # or Team. No standalone Polar product exists for it; if a one-time
            # tier is re-added later, also wire POLAR_PRODUCT_GROWTH + the
            # add_credits branch in modules/polar_payment.py.
            {"key": "autopilot", "name": "Growth Autopilot", "price": 49, "period": "month", "credits": 30, "features": [
                "10 tracked products (weekly audit + diff)",
                "Competitive Lens: 3 competitors as benchmark per product",
                "Weekly email digest with progress timeline",
                "30 audit credits (covers Pro audit usage too)",
                "Full /api/autopilot access",
            ]},
            {"key": "autopilot_team", "name": "Autopilot Team", "price": 149, "period": "month", "credits": 999999, "features": [
                "30 tracked products (daily audit + diff)",
                "20 competitors / product",
                "Daily digest + Slack/Discord webhook",
                "PDF history export",
                "Priority support",
            ]},
        ],
    }


@app.post("/api/checkout")
async def create_checkout_session(request: Request):
    """Create a Polar checkout session."""
    body = await request.json()
    plan = body.get("plan", "")
    if plan not in PRODUCTS:
        return JSONResponse({"error": f"Invalid plan: {plan}"}, status_code=400)

    # Get user info if authenticated
    user_email = ""
    user_id = ""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        user = await verify_token_and_get_user(auth[7:])
        if user:
            user_email = user.get("email", "")
            user_id = user.get("id", "")

    success_url = body.get("success_url", "https://www.analook.com/?payment=success")
    cancel_url = body.get("cancel_url", "https://www.analook.com/pricing.html?payment=canceled")

    result = await create_checkout(
        plan,
        user_email=user_email,
        success_url=success_url,
        user_id=user_id,
        cancel_url=cancel_url,
    )
    if result.get("error"):
        return JSONResponse({"error": result["error"]}, status_code=500)

    return result


@app.post("/api/webhook/polar")
async def polar_webhook(request: Request):
    """Handle Polar webhook events (payment confirmations, subscription changes).

    Security: verifies Standard Webhooks signature via POLAR_WEBHOOK_SECRET.
    Idempotent: repeated webhook-id is acknowledged without re-processing, so
    Polar's retry-on-failure doesn't double-credit users.
    """
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    # --- Signature verification (production) ---
    secret = os.environ.get("POLAR_WEBHOOK_SECRET", "").strip()
    if secret:
        if not verify_webhook_signature(body, headers, secret):
            log.warning("Polar webhook: invalid signature, id=%s", headers.get("webhook-id", ""))
            return JSONResponse({"error": "Invalid signature"}, status_code=401)
    else:
        # Missing secret in prod is a severe misconfig — log loudly but don't 500
        # (so Polar keeps retrying while we fix env vars rather than giving up).
        log.warning("Polar webhook: POLAR_WEBHOOK_SECRET not set — signature NOT verified")

    # --- Idempotency (Polar retries on non-2xx; Standard Webhooks id is unique) ---
    event_id = headers.get("webhook-id", "")
    if not mark_event_seen(event_id):
        log.info("Polar webhook: duplicate event_id=%s, skipping", event_id)
        return {"received": True, "duplicate": True}

    # --- Parse event ---
    try:
        import json as _json_wb
        event = _json_wb.loads(body)
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # --- Process ---
    result = await handle_webhook_event(event)
    return {"received": True, **result}


# =========================================================================
# Public API v1 — for agents (Claude Code, MCP, external integrations)
# Auth: Bearer API key or Supabase JWT
# =========================================================================

@app.post("/api/v1/analyze")
async def api_v1_analyze(request: Request):
    """Agent API: Submit a competitor analysis. Returns job_id for polling.

    Auth: Bearer token (Supabase JWT or API key)
    Body: {"url": "example.com", "product_name": "Example"} (product_name optional)

    Usage from Claude Code MCP:
      curl -X POST https://www.analook.com/api/v1/analyze
        -H "Authorization: Bearer <token>"
        -H "Content-Type: application/json"
        -d '{"url": "notion.so"}'
    """
    # Auth
    auth = request.headers.get("Authorization", "")
    user = None
    if auth.startswith("Bearer "):
        user = await verify_token_and_get_user(auth[7:])

    # Parse body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"error": "Missing 'url' field"}, status_code=400)

    product_name = body.get("product_name") or None

    # Credit check (if authenticated)
    if user:
        has_credit = await deduct_credit(user["id"])
        if not has_credit:
            return JSONResponse({
                "error": "Insufficient credits",
                "upgrade_url": "https://www.analook.com/pricing.html",
            }, status_code=402)

    # Create job (reuse existing analyze logic)
    job_id = uuid.uuid4().hex[:8]
    if not url.startswith("http"):
        url = f"https://{url}"

    domain = urlparse(url).netloc
    if not domain:
        return JSONResponse({"error": f"Invalid URL: {url}"}, status_code=400)

    import re as _re_api
    _brand = _re_api.sub(r'^www\.', '', domain.lower())
    _brand = _re_api.sub(r'\.[a-z]{2,6}$', '', _brand)
    name = product_name or _brand.replace("-", " ").replace("_", " ").capitalize()

    jobs[job_id] = {
        "status": "running",
        "product_name": name,
        "url": url,
        "progress": {
            "website": "pending", "social": "pending", "propagation": "pending",
            "traffic": "pending", "pricing": "pending", "traffic_peaks": "pending",
            "growth_analysis": "pending", "report": "pending", "pr_news": "pending",
        },
        "results": {},
        "report": None,
        "markdown": None,
        "user_id": user["id"] if user else None,
    }

    background_tasks = BackgroundTasks()
    background_tasks.add_task(_run_analysis, job_id)
    return JSONResponse(
        {"job_id": job_id, "status": "started", "poll_url": f"/api/v1/status/{job_id}"},
        background=background_tasks,
    )


@app.get("/api/v1/status/{job_id}")
async def api_v1_status(job_id: str):
    """Agent API: Poll analysis status."""
    job = jobs.get(job_id)
    if not job:
        # Try persisted report
        report = _load_persisted_report(job_id)
        if report:
            return {"status": "completed", "report_url": f"/api/v1/report/{job_id}"}
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return {
        "status": job["status"],
        "progress": job.get("progress", {}),
        "product_name": job.get("product_name", ""),
    }


@app.get("/api/v1/report/{job_id}")
async def api_v1_report(job_id: str):
    """Agent API: Get the full analysis report as JSON."""
    job = jobs.get(job_id)
    if job and job.get("report"):
        return job["report"]
    # Try persisted
    report = _load_persisted_report(job_id)
    if report:
        return report
    return JSONResponse({"error": "Report not found"}, status_code=404)


@app.get("/api/v1/report/{job_id}/markdown")
async def api_v1_report_markdown(job_id: str):
    """Agent API: Get the analysis report as Markdown text."""
    job = jobs.get(job_id)
    if job and job.get("markdown"):
        return PlainTextResponse(job["markdown"])
    return JSONResponse({"error": "Markdown not found"}, status_code=404)


@app.get("/api/v1/reports")
async def api_v1_list_reports(request: Request):
    """
    List current user's recent reports (server-side history).
    Requires Bearer token. Returns [{id, url, product_name, created_at, status}].
    """
    if (degraded := _service_degraded_response()):
        return degraded
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)
    rows = await list_user_reports(user["id"], limit=50)
    return {"reports": rows}


def _load_persisted_report(job_id: str) -> dict | None:
    """Load report from disk → Supabase (survives Railway restarts)."""
    # Disk
    _reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    path = os.path.join(_reports_dir, f"{job_id}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = _json.load(f)
            return data.get("report")
        except Exception:
            pass
    # Supabase
    try:
        from modules.supabase_client import get_supabase
        sb = get_supabase()
        if sb:
            result = sb.table("reports").select("report").eq("id", job_id).limit(1).execute()
            if result.data and result.data[0].get("report"):
                return result.data[0]["report"]
    except Exception:
        pass
    return None


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

    # --- Domain cache: return cached result if available, fresh, and AI succeeded ---
    cache_key = domain.lower().replace("www.", "")
    cached = _domain_cache.get(cache_key)
    if cached and (time.time() - cached["timestamp"]) < DOMAIN_CACHE_TTL:
        cached_job = cached["job"]
        # Only use cache if AI summary succeeded — skip cache if AI failed
        cached_ai = cached_job.get("results", {}).get("ai_summary", {})
        ai_ok = isinstance(cached_ai, dict) and cached_ai.get("success")
        if ai_ok:
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


# =========================================================================
# Growth Audit — Premium feature ($49 one-time or 10 credits)
# =========================================================================

# Growth Audit jobs (separate from regular analysis jobs)
_growth_audit_jobs: dict = {}

GROWTH_AUDIT_CREDITS = 10  # Pro $29/mo (30 credits) = exactly 3 audits/month


@app.post("/api/growth-audit")
async def start_growth_audit(request: Request, bg: BackgroundTasks):
    """Start a Growth Audit: produces 3 reports (Executive Summary + Diagnosis + Action Plan).
    
    Costs 10 credits or requires growth_audit product purchase.
    Body: {"url": "example.com", "product_name": "Example"}
    """
    # Auth check
    user = await _extract_user(request)
    from modules.supabase_client import get_supabase, supabase_required
    sb = get_supabase()

    if sb:
        if not user:
            return JSONResponse(
                {"error": "请先登录", "code": "AUTH_REQUIRED"},
                status_code=401,
            )
        # Deduct 10 credits
        from modules.supabase_client import deduct_credit
        credits_ok = True
        for _ in range(GROWTH_AUDIT_CREDITS):
            ok = await deduct_credit(user["id"])
            if not ok:
                credits_ok = False
                break
        if not credits_ok:
            return JSONResponse(
                {
                    "error": f"积分不足（Growth Audit 需要 {GROWTH_AUDIT_CREDITS} 积分）",
                    "code": "CREDITS_EXHAUSTED",
                    "required_credits": GROWTH_AUDIT_CREDITS,
                    "upgrade_url": "https://www.analook.com/pricing.html",
                },
                status_code=402,
            )

    # Parse body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"error": "Missing 'url' field"}, status_code=400)

    if not url.startswith("http"):
        url = f"https://{url}"

    product_name = body.get("product_name") or None

    job_id = f"ga-{uuid.uuid4().hex[:8]}"
    _growth_audit_jobs[job_id] = {
        "status": "running",
        "product_name": product_name or url,
        "url": url,
        "user_id": user["id"] if user else None,
        "progress": {
            "fetch": "pending",
            "executive_summary": "pending",
            "diagnosis": "pending",
            "action_plan": "pending",
        },
        "reports": None,
    }

    bg.add_task(_run_growth_audit, job_id, url, product_name)
    return {"job_id": job_id, "status": "started"}


@app.get("/api/growth-audit/{job_id}")
async def get_growth_audit_status(job_id: str):
    """Poll Growth Audit job status and get results."""
    job = _growth_audit_jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    response = {
        "status": job["status"],
        "product_name": job.get("product_name"),
        "url": job.get("url"),
        "progress": job.get("progress"),
    }

    # Return whatever reports exist so far (not only when completed) so the
    # frontend can progressively render Diagnosis the moment it's ready, then
    # Exec/Plan as they stream in — instead of waiting for the full pipeline.
    if job.get("reports"):
        response["reports"] = job["reports"]
        response["site_data_summary"] = job.get("site_data_summary")

    if job["status"] == "failed":
        response["error"] = job.get("error", "Unknown error")

    return response


# ─── Growth Audit public share ─────────────────────────────────────────────
# Phase 2: lets a user share their completed audit at /share/audit/<job_id>.
# No auth required to read; the share URL is unguessable (full uuid hex).
@app.get("/api/share/audit/{job_id}")
async def get_growth_audit_share(job_id: str):
    """Public read-only view of a completed Growth Audit (no auth).

    Looks first in the in-memory jobs dict (warm cache), then falls back to
    Supabase `reports` table where _run_growth_audit persists completed
    audits when the user is authenticated.
    """
    # In-memory hit
    job = _growth_audit_jobs.get(job_id)
    if job and job.get("status") == "completed" and job.get("reports"):
        return {
            "product_name": job.get("product_name") or "Growth Audit",
            "url": job.get("url"),
            "reports": job["reports"],
            "site_data_summary": job.get("site_data_summary"),
            "shared_at": "now",
        }

    # Supabase fallback (audit was persisted on completion)
    try:
        from modules.supabase_client import get_supabase
        sb = get_supabase()
        if sb:
            # NOTE: the `reports` table uses `id` (not `job_id`) as PK —
            # save_report_to_db writes the audit's job_id into the `id`
            # column. The earlier query targeted a column that doesn't
            # exist, so the share endpoint silently 404'd for every
            # audit completed before the in-memory cache went away.
            result = sb.table("reports").select(
                "id,product_name,url,report,created_at,is_public,status"
            ).eq("id", job_id).limit(1).execute()
            rows = result.data or []
            if rows:
                row = rows[0]
                # Still-processing audits shouldn't render as 404s
                if row.get("status") and row["status"] != "completed":
                    return JSONResponse(
                        {"error": "Audit is still processing — try again in a moment."},
                        status_code=202,
                    )
                # Respect explicit opt-out (default for audits is is_public=true)
                if row.get("is_public") is False:
                    return JSONResponse(
                        {"error": "This audit is private."},
                        status_code=403,
                    )
                report_payload = row.get("report") or {}
                if isinstance(report_payload, str):
                    try:
                        report_payload = _json.loads(report_payload)
                    except Exception:
                        report_payload = {}
                reports = report_payload.get("reports") or {}
                if reports:
                    return {
                        "product_name": row.get("product_name") or "Growth Audit",
                        "url": row.get("url"),
                        "reports": reports,
                        "site_data_summary": report_payload.get("site_data_summary"),
                        "shared_at": row.get("created_at"),
                    }
    except Exception as e:
        log.error("Share fetch from Supabase failed: %s", e)

    return JSONResponse(
        {"error": "Audit not found or not yet completed."},
        status_code=404,
    )


@app.get("/share/audit/{job_id}")
async def share_audit_page(job_id: str):
    """Public, link-only share page. Serves the cream/Instrument-Serif themed
    static viewer which fetches /api/share/audit/{job_id} client-side."""
    return FileResponse("static/share-audit.html")


# ─── Growth Autopilot endpoints ────────────────────────────────────────────
# Phase 1 (today): CRUD on subscriptions + dashboard query. Cron worker and
# email digest land in Phase 2.

@app.get("/api/autopilot/subscriptions")
async def autopilot_list(request: Request):
    """List the current user's autopilot subscriptions."""
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "请先登录", "code": "AUTH_REQUIRED"}, status_code=401)
    from modules import autopilot
    return {"subscriptions": autopilot.list_user_subscriptions(user["id"])}


@app.post("/api/autopilot/subscriptions")
async def autopilot_subscribe(request: Request):
    """Create a new Growth Autopilot subscription for the authenticated user.

    Body: {"target_url": "...", "product_name": "...", "frequency": "weekly",
           "competitor_urls": ["..."]}
    """
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "请先登录", "code": "AUTH_REQUIRED"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    target_url = (body.get("target_url") or "").strip()
    if not target_url:
        return JSONResponse({"error": "缺少 target_url"}, status_code=400)

    from modules import autopilot
    try:
        row = autopilot.create_subscription(
            user_id=user["id"],
            target_url=target_url,
            product_name=body.get("product_name") or None,
            frequency=body.get("frequency") or "weekly",
            competitor_urls=body.get("competitor_urls") or [],
        )
        return {"subscription": row}
    except ValueError as e:
        return JSONResponse(
            {"error": str(e), "code": "TIER_LIMIT_OR_DUPLICATE"},
            status_code=402,
        )
    except Exception as e:
        log.error("autopilot subscribe failed: %s", e)
        return JSONResponse({"error": "服务器错误，请稍后再试"}, status_code=500)


@app.patch("/api/autopilot/subscriptions/{sub_id}")
async def autopilot_update(sub_id: str, request: Request):
    """Update product_name / frequency / competitor_urls / status."""
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "请先登录", "code": "AUTH_REQUIRED"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    from modules import autopilot
    row = autopilot.update_subscription(user["id"], sub_id, body)
    if not row:
        return JSONResponse({"error": "Not found or no valid fields"}, status_code=404)
    return {"subscription": row}


@app.delete("/api/autopilot/subscriptions/{sub_id}")
async def autopilot_cancel(sub_id: str, request: Request):
    """Cancel (soft-delete) a subscription."""
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "请先登录", "code": "AUTH_REQUIRED"}, status_code=401)
    from modules import autopilot
    if autopilot.cancel_subscription(user["id"], sub_id):
        return {"ok": True}
    return JSONResponse({"error": "Not found"}, status_code=404)


@app.get("/api/autopilot/subscriptions/{sub_id}/dashboard")
async def autopilot_dashboard(sub_id: str, request: Request):
    """Return the progress timeline for one subscription: latest snapshot,
    latest diff, last 8 diffs as a trend strip."""
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "请先登录", "code": "AUTH_REQUIRED"}, status_code=401)

    from modules.supabase_client import get_supabase
    from modules import autopilot
    sb = get_supabase()
    if not sb:
        return JSONResponse({"error": "Supabase not configured"}, status_code=503)

    sub_rows = sb.table("autopilot_subscriptions").select("*").eq(
        "id", sub_id
    ).eq("user_id", user["id"]).execute()
    if not sub_rows.data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    sub = sub_rows.data[0]

    snaps = autopilot.latest_two_snapshots(sub_id)
    last_diffs = sb.table("autopilot_diffs").select(
        "id,progress_score,resolved_findings,new_findings,persistent_findings,summary_md,created_at"
    ).eq("subscription_id", sub_id).order(
        "created_at", desc=True
    ).limit(8).execute()
    last_digests = sb.table("autopilot_digests").select(
        "id,resend_email_id,recipient,last_event,sent_at"
    ).eq("subscription_id", sub_id).order(
        "sent_at", desc=True
    ).limit(8).execute()

    return {
        "subscription":  sub,
        "latest_snapshot": snaps[0] if snaps else None,
        "diffs":         last_diffs.data or [],
        "digests":       last_digests.data or [],
    }


@app.post("/api/audit/qa")
async def audit_qa(request: Request):
    """Q&A endpoint for the share-audit page. Asks DeepSeek a question
    grounded in the audit's three reports + site_data_summary.

    Auth: optional. Anonymous viewers (no JWT) get a smaller rate-limit.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body."}, status_code=400)

    job_id   = (body.get("job_id") or "").strip()
    question = (body.get("question") or "").strip()
    history  = body.get("history") or []
    if not job_id or not question:
        return JSONResponse({"error": "job_id and question are required."}, status_code=400)

    # Identity — JWT preferred, fallback to a visitor cookie/header.
    user = await _extract_user(request)
    user_id = user["id"] if user else None
    plan    = None
    if user_id:
        try:
            from modules.supabase_client import get_supabase
            sb = get_supabase()
            if sb:
                rs = sb.table("profiles").select("plan_type").eq("id", user_id).execute()
                plan = (rs.data or [{}])[0].get("plan_type")
        except Exception:
            pass

    # Visitor ID for anon rate limiting. We accept a client-supplied id
    # (a hash kept in localStorage); falls back to IP + UA.
    visitor_id = (body.get("visitor_id") or "").strip()
    if not visitor_id:
        ip = (request.headers.get("x-forwarded-for") or request.client.host or "").split(",")[0].strip()
        ua = (request.headers.get("user-agent") or "")[:120]
        import hashlib as _hl
        visitor_id = _hl.sha1((ip + "::" + ua).encode("utf-8")).hexdigest()[:24]

    from modules.audit_qa import answer_question
    result = await answer_question(
        job_id=job_id,
        question=question,
        history=history,
        user_id=user_id,
        visitor_id=visitor_id,
        plan=plan,
        jobs_dict=_growth_audit_jobs,
    )

    if result.get("status") == "rate_limited":
        return JSONResponse(result, status_code=429)
    if result.get("status") == "not_found":
        return JSONResponse(result, status_code=404)
    if result.get("status") in ("llm_error", "empty"):
        return JSONResponse(result, status_code=503 if result.get("status") == "llm_error" else 400)
    return result


@app.get("/api/audit/qa/{job_id}")
async def audit_qa_history(job_id: str, request: Request):
    """Return the most recent Q&A exchanges for an audit so the slide-in
    panel can re-hydrate when a user reloads the share page."""
    try:
        from modules.supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return {"history": []}
        # Identity gate — we return only the caller's own exchanges. For
        # anonymous viewers, this means filtering by their visitor_id which
        # the client passes back. Logged-in users get their own user_id.
        user = await _extract_user(request)
        user_id = user["id"] if user else None
        visitor_id = (request.query_params.get("visitor_id") or "").strip()

        q = sb.table("audit_qa").select(
            "question,answer,cited_section,created_at,refused"
        ).eq("audit_job_id", job_id).order("created_at", desc=False).limit(20)
        if user_id:
            q = q.eq("user_id", user_id)
        elif visitor_id:
            q = q.eq("visitor_id", visitor_id).is_("user_id", "null")
        else:
            return {"history": []}
        rs = q.execute()
        return {"history": rs.data or []}
    except Exception as e:
        log.warning("audit_qa_history failed: %s", e)
        return {"history": []}


@app.get("/api/admin/api-balances")
async def admin_api_balances(request: Request):
    """Return live balance / health for every third-party API the app uses.

    Reuses AUTOPILOT_TICK_TOKEN (single admin token, no need for a separate
    secret). Header: X-Autopilot-Tick-Token.
    """
    expected = (os.environ.get("AUTOPILOT_TICK_TOKEN") or "").strip()
    if not expected:
        return JSONResponse({"error": "AUTOPILOT_TICK_TOKEN not configured"}, status_code=503)
    got = (request.headers.get("X-Autopilot-Tick-Token") or "").strip()
    if got != expected:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    from modules.api_balances import check_all
    from datetime import datetime, timezone
    result = await check_all()
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    return result


@app.post("/api/admin/autopilot/tick")
async def autopilot_tick(request: Request):
    """Cron entry point — runs the autopilot worker for due subscriptions.

    Authed with a static bearer token (env AUTOPILOT_TICK_TOKEN). NOT a
    user-facing endpoint. The GitHub Action workflow calls this hourly.
    """
    expected = (os.environ.get("AUTOPILOT_TICK_TOKEN") or "").strip()
    if not expected:
        return JSONResponse({"error": "AUTOPILOT_TICK_TOKEN not configured"}, status_code=503)
    got = (request.headers.get("X-Autopilot-Tick-Token") or "").strip()
    if got != expected:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    try:
        limit = int(request.query_params.get("limit") or 10)
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 50))

    from modules.autopilot_worker import tick_due
    result = await tick_due(limit=limit)
    return result


async def _run_growth_audit(job_id: str, url: str, product_name: str = None):
    """Background task to run the full growth audit."""
    try:
        result = await run_growth_audit(
            url=url,
            product_name=product_name,
            job_id=job_id,
            jobs_dict=_growth_audit_jobs,
        )

        if result.get("error"):
            _growth_audit_jobs[job_id]["status"] = "failed"
            _growth_audit_jobs[job_id]["error"] = result["error"]
        else:
            _growth_audit_jobs[job_id]["status"] = "completed"
            _growth_audit_jobs[job_id]["product_name"] = result.get("product_name", product_name)
            _growth_audit_jobs[job_id]["reports"] = result.get("reports", {})
            _growth_audit_jobs[job_id]["site_data_summary"] = result.get("site_data_summary")

            # Save to Supabase if user authenticated
            user_id = _growth_audit_jobs[job_id].get("user_id")
            if user_id:
                try:
                    await save_report_to_db(
                        job_id=job_id,
                        user_id=user_id,
                        url=url,
                        product_name=result.get("product_name", ""),
                        report=result,
                        markdown=_json.dumps(result.get("reports", {}), ensure_ascii=False)[:50000],
                    )
                except Exception as e:
                    log.error("Failed to save growth audit to DB: %s", e)

    except Exception as e:
        log.error("Growth audit failed for %s: %s", url, e)
        _growth_audit_jobs[job_id]["status"] = "failed"
        _growth_audit_jobs[job_id]["error"] = str(e)[:200]


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

    # Phase 1: all modules run in parallel (including SEO Review Tools alongside DataForSEO)
    job["progress"]["pr_news"] = "running"
    results_phase1 = await asyncio.gather(
        _t(analyze_website(url), 40),
        _t(analyze_domain(domain), 20),
        _t(analyze_producthunt(domain, product_name), 25),
        _t(analyze_social(domain, product_name, website_social_links={}), 35),  # TwitterAPI.io <3s/handle, total <20s
        _t(analyze_pricing(url, product_name), 20),
        _t(analyze_github_oss(domain, product_name, {}), 25),
        _t(analyze_pr_news(domain, product_name), 18),
        _t(analyze_funding(domain, product_name), 15),
        _t(fetch_seoreviewtools(domain), 15),  # SEO Review Tools: DA + backlinks + traffic fallback
        return_exceptions=True,
    )

    if _cancelled(): return

    job["results"]["website"] = results_phase1[0] if not isinstance(results_phase1[0], Exception) else {"error": str(results_phase1[0])}
    job["progress"]["website"] = "error" if isinstance(results_phase1[0], Exception) else "done"

    _dataforseo_raw = results_phase1[1] if not isinstance(results_phase1[1], Exception) else {"error": str(results_phase1[1])}
    _srt_raw = results_phase1[8] if isinstance(results_phase1[8], dict) else {}
    # Merge DataForSEO + SEO Review Tools: adds DA/Spam Score, fallback traffic/backlinks
    job["results"]["traffic"] = merge_seo_data(_dataforseo_raw, _srt_raw)
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

    # Phase 1.5: Slow Apify channels (TikTok/Facebook) + retries — run in parallel,
    # bounded by 35s (reduced from 65s). Also start Phase 2 + AI summary early.
    from modules.social import _deep_tiktok_apify, _deep_facebook_apify

    async def _slow_tiktok():
        try:
            res = await asyncio.wait_for(
                _deep_tiktok_apify(_brand_lower, product_name, handle_hint=_tiktok_hint), timeout=35
            )
            soc = job["results"].setdefault("social", {})
            soc.setdefault("channels", {})["tiktok"] = res if isinstance(res, dict) else {"platform": "TikTok", "detected": False}
        except Exception:
            pass

    async def _slow_facebook():
        try:
            res = await asyncio.wait_for(
                _deep_facebook_apify(_brand_lower, product_name, handle_hint=_facebook_hint), timeout=35
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
    # Snapshot the site's self-declared Twitter handle BEFORE the reconcile loop
    # below can overwrite it with a (possibly wrong) detected handle. The site's
    # own published handle is ground truth — Phase 1.8 uses it to correct fuzzy
    # mismatches (e.g. @testingcatalog → declared @tiny_fish for tinyfish.ai).
    _declared_tw = ((_ws_social_links.get("twitter") or {}).get("handle") or "").strip()
    # Fallback: the live scrape sometimes returns no social_links at all (JS-rendered
    # footer, anti-bot, timeout). The site's handle often still survives in the
    # Wayback historical snapshots (deep_timeline) — harvest it from there. An
    # archived self-declared handle is still ground truth, far better than a guess.
    if not _declared_tw:
        for _snap in (_website_res.get("deep_timeline") or []):
            _snap_h = (((_snap or {}).get("social_links") or {}).get("twitter") or {}).get("handle")
            if _snap_h and _snap_h.strip():
                _declared_tw = _snap_h.strip()
                break
    for _platform in ("twitter", "youtube", "instagram", "tiktok", "facebook"):
        _ch = _soc_channels.get(_platform, {})
        if _ch.get("detected") and _ch.get("handle") and _ws_social_links.get(_platform):
            _verified_handle = _ch["handle"].lstrip("@")
            _ws_social_links[_platform]["handle"] = _verified_handle
            if _ch.get("url"):
                _ws_social_links[_platform]["url"] = _ch["url"]
            _ws_social_links[_platform]["verified"] = True

    # Phase 1.8: Trust the site's self-declared Twitter handle as authoritative.
    # Re-verify against it when we detected nothing OR detected a handle that
    # disagrees with what the site publishes — a wrong fuzzy match (e.g.
    # @testingcatalog) must not block correction to the declared @tiny_fish.
    _tw_ch = _soc_channels.get("twitter", {})
    _detected_tw = _tw_ch.get("handle") if isinstance(_tw_ch, dict) else None

    def _norm_handle(h):
        return (h or "").lstrip("@").lower().replace("_", "")

    _needs_tw_retry = bool(_declared_tw) and (
        not (isinstance(_tw_ch, dict) and _tw_ch.get("detected"))
        or _norm_handle(_declared_tw) != _norm_handle(_detected_tw)
    )
    if _needs_tw_retry:
        from modules.social import _deep_twitter_caravo
        try:
            _tw_retry = await asyncio.wait_for(
                _deep_twitter_caravo(_brand_lower, product_name, handle_hint=_declared_tw),
                timeout=55,
            )
            if isinstance(_tw_retry, dict) and _tw_retry.get("detected"):
                soc = job["results"].setdefault("social", {})
                soc.setdefault("channels", {})["twitter"] = _tw_retry
                # Keep the website link consistent with the corrected handle
                if isinstance(_ws_social_links.get("twitter"), dict):
                    _ws_social_links["twitter"]["handle"] = _tw_retry["handle"].lstrip("@")
                    _ws_social_links["twitter"]["verified"] = True
        except Exception:
            pass

    # ================================================================
    # Phase 2: Propagation + Traffic Peaks (parallel, ~10s)
    # ================================================================
    def _build_multi_channel_fallback(error_msg: str = "") -> dict:
        """Build propagation summary from PH/GitHub/Reddit when Twitter is unavailable."""
        ph = job["results"].get("producthunt", {})
        if not isinstance(ph, dict): ph = {}
        gh = job["results"].get("github_oss", {})
        if not isinstance(gh, dict): gh = {}
        soc = job["results"].get("social", {})
        if not isinstance(soc, dict): soc = {}
        channels = soc.get("channels", {})
        reddit = channels.get("reddit", {}) if isinstance(channels, dict) else {}
        if not isinstance(reddit, dict): reddit = {}

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

        errors = [error_msg] if error_msg else ["Twitter API 不可用"]
        return {
            "data_mode": "multi_channel_fallback",
            "note": "⚠️ Twitter API 不可用，以下为多渠道综合传播信号",
            "signals": signals,
            "producthunt": {"votes": ph_votes, "comments": ph_comments, "date": ph_date},
            "github": {"stars": gh_stars},
            "reddit": {"posts": reddit_posts, "members": reddit_members},
            "errors": errors,
        }

    async def _run_propagation():
        job["progress"]["propagation"] = "running"
        propagation = {}

        # Primary: Twitter-based propagation
        try:
            if job["results"].get("social", {}).get("_propagation_available"):
                propagation = await run_launch_propagation(job["results"]["social"])
        except Exception as e:
            propagation = {}  # Fall through to multi_channel_fallback

        # Fallback: PH/GitHub/Reddit signals
        if not propagation or (isinstance(propagation, dict) and propagation.get("data_mode") in ("empty", "error", None)):
            err = propagation.get("error", "") if isinstance(propagation, dict) else ""
            propagation = _build_multi_channel_fallback(err or "Twitter 传播分析失败")

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
            github_oss=job["results"].get("github_oss", {}),
        )
        job["results"]["traffic_peaks"] = peaks
        job["progress"]["traffic_peaks"] = "done"

    if _cancelled(): return

    # ================================================================
    # Phase 2: Propagation + Traffic Peaks + AI Summary (ALL PARALLEL)
    # AI summary only needs Phase 1 data, so start it NOW instead of
    # waiting for Phase 2 to complete. This saves 60-90s.
    # ================================================================

    # Sync operations first (instant, <1ms)
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

    # AI summary task — starts NOW, runs in parallel with propagation + peaks
    async def _run_ai_summary():
        job["progress"]["report"] = "running"
        try:
            ai = await generate_ai_summary(
                product_name, url,
                job["results"].get("website", {}),
                job["results"].get("social", {}),
                job["results"].get("traffic", {}),
                job["results"].get("producthunt", {}),
                growth_strategy={},  # Not available yet, will be added post-hoc
                pricing=job["results"].get("pricing", {}),
                github_oss=job["results"].get("github_oss", {}),
            )
            job["results"]["ai_summary"] = ai
            return ai
        except Exception as ai_err:
            ai = {"success": False, "content": "", "note": f"AI 分析异常: {str(ai_err)[:100]}", "source": "error"}
            job["results"]["ai_summary"] = ai
            return ai

    # Run propagation + traffic_peaks + AI summary ALL in parallel
    phase2_results = await asyncio.gather(
        _run_propagation(), _run_traffic_peaks(), _run_ai_summary(),
        return_exceptions=True,
    )
    if isinstance(phase2_results[0], Exception):
        job["results"]["propagation"] = {"error": str(phase2_results[0])}
        job["progress"]["propagation"] = "error"
    if isinstance(phase2_results[1], Exception):
        job["results"]["traffic_peaks"] = {"error": str(phase2_results[1])}
        job["progress"]["traffic_peaks"] = "error"
    ai = phase2_results[2] if isinstance(phase2_results[2], dict) else job["results"].get("ai_summary", {})

    if _cancelled(): return

    # ================================================================
    # Phase 3: Growth analysis + Playbook (sync, instant <1s)
    # These need propagation data from Phase 2, so they run after.
    # ================================================================
    job["progress"]["growth_analysis"] = "running"
    try:
        growth_deep = analyze_growth_deep(
            product_name, url,
            job["results"].get("website", {}),
            job["results"].get("social", {}),
            job["results"].get("traffic", {}),
            job["results"].get("producthunt", {}),
            propagation=job["results"].get("propagation", {}),
            github_oss=job["results"].get("github_oss", {}),
        )
        job["results"]["growth_analysis"] = growth_deep
        job["progress"]["growth_analysis"] = "done"
    except Exception as growth_err:
        job["results"]["growth_analysis"] = {"error": str(growth_err)}
        job["progress"]["growth_analysis"] = "error"

    early_strategy = {}
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
        job["results"]["growth_strategy"] = {}

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

        # Recompute strategy radar now that ALL sections are available
        from modules.report import _compute_strategy_radar
        report["sections"]["strategy_radar"] = _compute_strategy_radar(report["sections"])

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
    if (degraded := _service_degraded_response()):
        return degraded
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

    # ── Free-tier cutover (2026-05-18): new free users get 2 instead of 3
    # The Supabase trigger still defaults to 3 for now. Until that's updated
    # at the DB level, we silently downgrade brand-new free users here on
    # first /api/me hit. Grandfathered for users created BEFORE the cutover.
    try:
        from modules.polar_payment import FREE_TIER_CUTOVER_ISO, PLAN_CREDITS
        if (
            profile.get("plan_type") == "free"
            and profile.get("credits_monthly_quota") == 3
            and profile.get("credits_used", 0) == 0  # don't downgrade users mid-month
            and profile.get("created_at", "") > FREE_TIER_CUTOVER_ISO
        ):
            from modules.supabase_client import get_supabase
            sb = get_supabase()
            if sb:
                new_quota = PLAN_CREDITS["free"]  # 2
                sb.table("profiles").update({
                    "credits_balance": new_quota,
                    "credits_monthly_quota": new_quota,
                }).eq("id", user["id"]).execute()
                profile["credits_balance"] = new_quota
                profile["credits_monthly_quota"] = new_quota
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).debug("free-tier auto-downgrade skipped: %s", e)

    return profile


# ─── Referral-source survey (acquisition attribution) ──────────────────────
# All users hit a one-question modal on first authenticated page hit. The
# modal blocks until they answer. We need this because we have no other
# signal for "where did this user come from" — utm params are flaky and
# direct-paste from Twitter/LinkedIn lose them entirely.

_REFERRAL_SOURCES_ALLOWED = {
    "twitter", "linkedin", "google_search", "geo", "referral", "other",
}


@app.post("/api/profile/referral")
async def submit_referral_source(request: Request):
    """Record where the user heard about Analook.

    Body: {"source": "twitter" | "linkedin" | "google_search" | "geo" |
                     "referral" | "other",
           "other":  "optional free text — required when source='other'"}
    Idempotent: re-submitting overwrites silently. We don't gate that
    because someone might mis-tap; they should be able to fix it via
    UI later if we add an /account page.
    """
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "请先登录", "code": "AUTH_REQUIRED"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    source = (body.get("source") or "").strip().lower()
    other = (body.get("other") or "").strip()[:200] or None

    if source not in _REFERRAL_SOURCES_ALLOWED:
        return JSONResponse({
            "error": "source 取值非法",
            "allowed": sorted(_REFERRAL_SOURCES_ALLOWED),
        }, status_code=400)

    # source='other' requires free-text — otherwise drop the data entirely.
    if source == "other" and not other:
        return JSONResponse({
            "error": "选 'Other' 时请填写来源描述",
        }, status_code=400)

    from modules.supabase_client import get_supabase
    sb = get_supabase()
    if not sb:
        return JSONResponse({"error": "Supabase 未配置"}, status_code=503)

    from datetime import datetime, timezone
    try:
        sb.table("profiles").update({
            "referral_source": source,
            "referral_other":  other,
            "referral_at":     datetime.now(timezone.utc).isoformat(),
        }).eq("id", user["id"]).execute()
    except Exception as e:
        log.error("Failed to save referral_source for %s: %s", user["id"], e)
        return JSONResponse({"error": "保存失败，请重试"}, status_code=500)

    return {"ok": True, "source": source}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    resp = {
        "status": job["status"],
        "progress": job["progress"],
        "product_name": job["product_name"],
        "mode": job.get("mode", "url"),
    }
    # Progressive delivery: include partial results for completed modules
    # so the frontend can render sections as they arrive
    if job.get("results"):
        partial = {}
        for key, prog_key in [
            ("website", "website"), ("social", "social"), ("traffic", "traffic"),
            ("producthunt", "producthunt"), ("pricing", "pricing"),
            ("github_oss", "github_oss"), ("pr_news", "pr_news"),
            ("funding", "funding"),
        ]:
            if job["progress"].get(prog_key or key) == "done" and key in job["results"]:
                partial[key] = job["results"][key]
        if partial:
            resp["partial_results"] = partial
    return resp


@app.get("/api/report/{job_id}")
async def get_report(job_id: str):
    # 1. Memory
    job = jobs.get(job_id)
    if job and job.get("report"):
        return job["report"]
    # 2. Disk
    path = os.path.join(REPORTS_DIR, f"{job_id}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if data.get("report"):
            return data["report"]
    # 3. Supabase (survives Railway restarts)
    try:
        from modules.supabase_client import get_supabase
        sb = get_supabase()
        if sb:
            result = sb.table("reports").select("report").eq("id", job_id).limit(1).execute()
            if result.data and result.data[0].get("report"):
                return result.data[0]["report"]
    except Exception:
        pass
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
    # Mirror get_report's 3-tier lookup (memory → disk → Supabase). Without the
    # Supabase fallback the report page itself loads (get_report has it) but the
    # Share button 404s for any report not in the warm in-memory cache — e.g.
    # after a Railway restart, or when opened from a shared link / history.
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
    # Supabase fallback (survives Railway restarts / cross-instance shares)
    if not product_name:
        try:
            from modules.supabase_client import get_supabase
            sb = get_supabase()
            if sb:
                result = sb.table("reports").select(
                    "product_name,url"
                ).eq("id", job_id).limit(1).execute()
                if result.data:
                    product_name = result.data[0].get("product_name")
                    url = result.data[0].get("url")
        except Exception as e:
            log.error("Share info fetch from Supabase failed: %s", e)
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
# Remote MCP server — mount BEFORE the catch-all static "/" mount.
# Exposes competitor-analysis tools over Streamable HTTP at /mcp for
# Claude Desktop / Cursor / other MCP clients. Auth via Bearer header.
try:
    from modules.mcp_app import build_mcp_app
    app.mount("/mcp", build_mcp_app(), name="mcp")
except Exception as _mcp_err:
    # Non-fatal: if mcp dep is missing or mounting fails, keep HTTP API running.
    import logging as _log
    _log.getLogger(__name__).warning("MCP server not mounted: %s", _mcp_err)

# ─── Extension-less path → .html alias ─────────────────────────────────────
# Starlette's StaticFiles(html=True) maps a DIRECTORY path to its index.html,
# but does NOT map a bare filename ("/pricing") to "/pricing.html". So users
# typing or linking to "/pricing", "/comparison", "/unsubscribe", etc. hit
# 404s even though the file exists. We register lightweight 308-permanent
# redirects for every existing .html file at /static root (and one level
# deep under /docs, /alternatives, /compare, /blog, /research) so the
# extension-less URL is the canonical one.
def _register_html_aliases():
    from fastapi.responses import RedirectResponse
    import os as _os
    seen = set()
    # Walk static/ shallow (root) + the known sub-trees that have .html pages.
    roots = [
        ("", "static"),
        ("docs/", "static/docs"),
        ("compare/", "static/compare"),
        ("alternatives/", "static/alternatives"),
        ("blog/", "static/blog"),
        ("research/", "static/research"),
    ]
    for prefix, dirpath in roots:
        if not _os.path.isdir(dirpath):
            continue
        for fname in _os.listdir(dirpath):
            if not fname.endswith(".html") or fname == "index.html":
                continue
            stem = fname[:-5]  # strip .html
            route = f"/{prefix}{stem}"
            if route in seen:
                continue
            seen.add(route)
            target = f"/{prefix}{fname}"
            # Closure-binding trick so the lambda captures the right target.
            def _make(target_url):
                async def _alias():
                    return RedirectResponse(url=target_url, status_code=308)
                return _alias
            app.add_api_route(route, _make(target), methods=["GET", "HEAD"],
                              include_in_schema=False)
_register_html_aliases()
# ───────────────────────────────────────────────────────────────────────────

app.mount("/zh/js", StaticFiles(directory="static/zh/js"), name="zh-js")
app.mount("/zh", StaticFiles(directory="static/zh", html=True), name="zh-static")
app.mount("/js", StaticFiles(directory="static/js"), name="js")
app.mount("/", StaticFiles(directory="static", html=True), name="static")

