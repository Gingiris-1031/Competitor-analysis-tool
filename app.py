"""竞品调研 MVP 工具 — FastAPI 后端"""
import asyncio
import json as _json
import logging
import os
import time
import uuid

log = logging.getLogger(__name__)
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form, Request, Response
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
from modules.oss_growth_attribution import analyze_oss_growth_attribution
from modules.pr_news import analyze_pr_news
from modules.funding import analyze_funding
from modules.bizmodel import analyze_bizmodel
from modules.growth_audit import run_growth_audit
from modules.supabase_client import (
    verify_token_and_get_user, deduct_credit,
    get_user_profile, save_report_to_db, list_user_reports,
)
from modules.polar_payment import (
    create_checkout as _polar_create_checkout,
    handle_webhook_event as _polar_handle_webhook_event,
    PRODUCTS as POLAR_PRODUCTS,
    PLAN_CREDITS,
    verify_webhook_signature as polar_verify_signature,
    mark_event_seen as polar_mark_seen,
)
from modules.clink_payment import (
    create_checkout as clink_create_checkout,
    handle_webhook_event as clink_handle_webhook_event,
    verify_webhook_signature as clink_verify_signature,
    mark_event_seen as clink_mark_seen,
    CLINK_PRODUCTS,
    PLAN_CREDITS as CLINK_PLAN_CREDITS,
)

# Active payment provider: 'clink' (default) or 'polar' (legacy fallback)
_PAYMENT_PROVIDER = os.environ.get("PAYMENT_PROVIDER", "clink").lower()

# Unified product list for /api/checkout validation
PRODUCTS = CLINK_PRODUCTS if _PAYMENT_PROVIDER == "clink" else POLAR_PRODUCTS

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
    finally:
        # Flush buffered PostHog events on shutdown. Best-effort — a failed
        # flush must never take down the app.
        from modules import posthog_track
        posthog_track.shutdown()

# Interactive API docs + the OpenAPI schema hand an attacker a full map of
# every endpoint/parameter/model. Disable them in production by default; set
# EXPOSE_API_DOCS=1 to re-enable locally when you need the Swagger UI.
_EXPOSE_API_DOCS = os.environ.get("EXPOSE_API_DOCS", "").lower() in ("1", "true", "yes")
app = FastAPI(
    title="Analook — 竞品情报分析",
    lifespan=_analook_lifespan,
    docs_url="/docs" if _EXPOSE_API_DOCS else None,
    redoc_url="/redoc" if _EXPOSE_API_DOCS else None,
    openapi_url="/openapi.json" if _EXPOSE_API_DOCS else None,
)


# ── Security response headers ────────────────────────────────────────────────
# Added on every response (defends clickjacking, MIME sniffing, protocol
# downgrade, referrer leakage). CSP is scoped to frame-ancestors only so it
# can't break inline scripts/styles the site relies on.
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return response


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
            {"error": "积分不足，请购买 credits 或升级套餐", "code": "CREDITS_EXHAUSTED"},
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
        "ORCAROUTER_API_KEY": bool(os.environ.get("ORCAROUTER_API_KEY", "").strip()),
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
        "CLINK_SECRET_KEY": bool(os.environ.get("CLINK_SECRET_KEY", "").strip()),
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
            {"key": "free", "name": "Free", "price": 0, "period": "once", "credits": 2, "features": ["2 free reports", "Basic analysis"]},
            {"key": "pro", "name": "Pro", "price": 19, "period": "month", "credits": 30, "features": ["30 reports/month", "Full analysis", "AI insights", "Export"]},
            {"key": "team", "name": "Team", "price": 79, "period": "month", "credits": 100, "features": ["100 reports/month", "Full analysis", "AI insights", "Export", "Priority support"]},
            {"key": "single_report", "name": "Single Report", "price": 5, "period": "once", "credits": 1, "features": ["1 full analysis report"]},
            # Growth Audit is a CREDIT-PRICED tool (10 credits / use). It's not a
            # standalone purchase tier — to run it you buy Pro ($19/mo → 3 audits/mo)
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
            {"key": "autopilot_team", "name": "Autopilot Team", "price": 149, "period": "month", "credits": 100, "features": [
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
    """Create a checkout session (Clink by default, Polar as legacy fallback)."""
    body = await request.json()
    plan = body.get("plan", "")
    # Validate against active provider's product list
    active_products = CLINK_PRODUCTS if _PAYMENT_PROVIDER == "clink" else POLAR_PRODUCTS
    if plan not in active_products and plan not in CLINK_PLAN_CREDITS:
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

    if _PAYMENT_PROVIDER == "clink":
        result = await clink_create_checkout(
            plan,
            user_email=user_email,
            user_id=user_id,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    else:
        result = await _polar_create_checkout(
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
    """Handle Polar webhook events (kept for legacy subscriptions still on Polar).

    New payments go through Clink (/api/webhook/clink). This endpoint stays
    active until all active Polar subscriptions have churned or been migrated.
    """
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    secret = os.environ.get("POLAR_WEBHOOK_SECRET", "").strip()
    if secret:
        if not polar_verify_signature(body, headers, secret):
            log.warning("Polar webhook: invalid signature, id=%s", headers.get("webhook-id", ""))
            return JSONResponse({"error": "Invalid signature"}, status_code=401)
    else:
        log.warning("Polar webhook: POLAR_WEBHOOK_SECRET not set — signature NOT verified")

    event_id = headers.get("webhook-id", "")
    if not polar_mark_seen(event_id):
        log.info("Polar webhook: duplicate event_id=%s, skipping", event_id)
        return {"received": True, "duplicate": True}

    try:
        import json as _json_wb
        event = _json_wb.loads(body)
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    result = await _polar_handle_webhook_event(event)
    return {"received": True, **result}


@app.post("/api/webhook/clink")
async def clink_webhook(request: Request):
    """Handle Clink webhook events (payment confirmations, subscription changes).

    Security: HMAC-SHA256 over "{X-Clink-Timestamp}.{raw_body}" with
    CLINK_WEBHOOK_SIGNING_KEY (copy from Developers > Webhooks in Clink dashboard).
    Idempotent via in-memory event-id store (Clink retries up to 10× over ~24 h).
    """
    body = await request.body()

    # --- Signature verification ---
    signing_key = os.environ.get("CLINK_WEBHOOK_SIGNING_KEY", "").strip()
    timestamp = request.headers.get("X-Clink-Timestamp", "")
    signature = request.headers.get("X-Clink-Signature", "")

    if signing_key:
        if not clink_verify_signature(body, timestamp, signature, signing_key):
            log.warning("Clink webhook: invalid signature, ts=%s", timestamp)
            return JSONResponse({"error": "Invalid signature"}, status_code=401)
    else:
        log.warning("Clink webhook: CLINK_WEBHOOK_SIGNING_KEY not set — signature NOT verified")

    # --- Idempotency ---
    # Use timestamp + first 32 chars of body hash as event id (Clink doesn't
    # expose a dedicated event-id header like Polar's webhook-id).
    import hashlib as _hs
    event_fingerprint = timestamp + "-" + _hs.sha256(body).hexdigest()[:32]
    if not clink_mark_seen(event_fingerprint):
        log.info("Clink webhook: duplicate fingerprint=%s, skipping", event_fingerprint)
        return {"received": True, "duplicate": True}

    # --- Parse ---
    try:
        import json as _json_cw
        event = _json_cw.loads(body)
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # --- Process ---
    result = await clink_handle_webhook_event(event)
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
    # Parse body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"error": "Missing 'url' field"}, status_code=400)

    product_name = body.get("product_name") or None
    detected_lang = _detect_report_lang(
        body.get("lang"), request.query_params.get("lang"),
        request.headers.get("referer") or request.headers.get("origin"),
        request.headers.get("accept-language"), default="en",
    )

    # ── 鉴权 + 积分检查（统一走 _require_credits；未登录→401，余额不足→402）──
    # 修复前此端点的鉴权是「可选」的（无 token 也照跑），匿名可刷 LLM 额度。
    # 现与 /api/analyze 一致：强制鉴权。扣分放在 url 校验之后，避免无效请求误扣。
    # _extract_user 与原 verify_token_and_get_user 同源，JWT / API key 均兼容。
    user, err = await _require_credits(request)
    if err:
        return err

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
        "lang": detected_lang,
        "cancelled": False,
    }

    background_tasks = BackgroundTasks()
    background_tasks.add_task(_run_analysis, job_id)
    return JSONResponse(
        {"job_id": job_id, "status": "started", "poll_url": f"/api/v1/status/{job_id}", "lang": detected_lang},
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
    """Agent API: Get the analysis report as Markdown text.

    Same live-render semantics as /api/export: prefer regenerating from the
    persisted structured report (survives restarts; immune to stale
    "export failed" stubs), fall back to the in-memory markdown."""
    job = jobs.get(job_id)
    report = (job or {}).get("report") or _load_persisted_report(job_id)
    if report:
        try:
            from modules.report import report_to_markdown
            fresh = report_to_markdown(report)
            if fresh and fresh.strip():
                return PlainTextResponse(fresh)
        except Exception as _e:
            log.error("v1 markdown: report_to_markdown failed for %s: %s", job_id, _e)
    md = (job or {}).get("markdown")
    if md and "export failed" not in md.lower():
        return PlainTextResponse(md)
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


# =========================================================================
# API Key management — long-lived keys for MCP and automation tooling
# Auth: Bearer Supabase JWT (to create/list/revoke keys)
# Usage: pass the returned key as Bearer token for any other endpoint
# =========================================================================

@app.post("/api/keys")
async def create_api_key(request: Request):
    """Generate a new long-lived API key for the authenticated user.

    Returns the raw key ONCE — it is never stored in plain text.
    Body: {"name": "My MCP key"}  (name is optional, defaults to "Default key")
    """
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)

    body = await request.json()
    name = body.get("name", "Default key")

    import secrets, hashlib
    raw_key = "ak_" + secrets.token_urlsafe(36)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]

    from modules.supabase_client import get_supabase
    sb = get_supabase()
    sb.table("api_keys").insert({
        "user_id": user["id"],
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "name": name,
    }).execute()

    return JSONResponse({
        "key": raw_key,
        "prefix": key_prefix,
        "name": name,
        "note": "Save this key — it won't be shown again."
    })


@app.get("/api/keys")
async def list_api_keys(request: Request):
    """List all API keys for the authenticated user (never returns raw keys)."""
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)
    from modules.supabase_client import get_supabase
    sb = get_supabase()
    result = (
        sb.table("api_keys")
        .select("id, key_prefix, name, created_at, last_used_at, revoked_at")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .execute()
    )
    return JSONResponse({"keys": result.data or []})


@app.delete("/api/keys/{key_id}")
async def revoke_api_key(key_id: str, request: Request):
    """Revoke an API key by ID. Only the owning user can revoke their own keys."""
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)
    from modules.supabase_client import get_supabase
    sb = get_supabase()
    sb.table("api_keys").update({"revoked_at": "now()"}).eq("id", key_id).eq("user_id", user["id"]).execute()
    return JSONResponse({"ok": True})
# ---------------------------------------------------------------------------
# MCP API key management — keys are issued by Analook and stored only as
# SHA-256 hashes in InsForge. The raw value is returned once on creation.
# ---------------------------------------------------------------------------
class McpKeyCreateRequest(BaseModel):
    name: str = "MCP key"


async def _extract_mcp_key_owner(request: Request) -> dict | None:
    """Accept InsForge user JWTs first; keep legacy login tokens during migration."""
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        return None
    try:
        from modules.insforge_client import verify_user_token
        user = await verify_user_token(token)
        if user:
            return user
    except Exception:
        pass
    return await verify_token_and_get_user(token)


@app.get("/api/mcp/keys")
async def list_mcp_keys(request: Request):
    owner = await _extract_mcp_key_owner(request)
    if not owner:
        return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)
    from modules.insforge_client import list_mcp_api_keys
    return {"keys": await list_mcp_api_keys(owner["id"])}


@app.post("/api/mcp/keys")
async def create_mcp_key(payload: McpKeyCreateRequest, request: Request):
    owner = await _extract_mcp_key_owner(request)
    if not owner:
        return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)
    from modules.insforge_client import create_mcp_api_key
    created = await create_mcp_api_key(owner["id"], payload.name)
    if not created:
        return JSONResponse({"error": "MCP_KEY_CREATE_FAILED"}, status_code=503)
    return {"key": created["key"], "id": created["id"], "name": created["name"], "shown_once": True}


@app.delete("/api/mcp/keys/{key_id}")
async def revoke_mcp_key(key_id: str, request: Request):
    owner = await _extract_mcp_key_owner(request)
    if not owner:
        return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)
    from modules.insforge_client import revoke_mcp_api_key
    if not await revoke_mcp_api_key(owner["id"], key_id):
        return JSONResponse({"error": "KEY_NOT_FOUND"}, status_code=404)
    return {"revoked": True}


def _load_persisted_report(job_id: str) -> dict | None:
    """Load report from disk → InsForge → legacy Supabase."""
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
    # InsForge (primary for new reports)
    try:
        from modules.insforge_client import get_report_record_sync
        record = get_report_record_sync(job_id)
        if record and record.get("report"):
            return record["report"]
    except Exception:
        pass

    # Legacy Supabase fallback
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
    # None (not "en") so the Referer/Accept-Language fallback in the handler
    # actually runs for API callers that omit lang. Iris 2026-07-07: the old
    # "en" default made the fallback dead code.
    lang: Optional[str] = None  # "en" or "zh"


class TextAnalyzeRequest(BaseModel):
    text: str
    product_name: Optional[str] = "产品"


def _detect_report_lang(explicit=None, query=None, referer=None,
                        accept_language=None, default: str = "en") -> str:
    """Resolve the report language consistently for web and agent APIs."""
    lang = str(explicit or query or "").strip().lower()
    if lang not in {"en", "zh"}:
        ref = str(referer or "").lower()
        accept = str(accept_language or "").lower()
        if "/zh/" in ref or "lang=zh" in ref or accept.startswith("zh"):
            lang = "zh"
        elif accept.startswith("en"):
            lang = "en"
        else:
            lang = default if default in {"en", "zh"} else "en"
    return lang


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

    # Detect report language BEFORE the cache check — the cache is scoped
    # per (domain, lang). Same detection order as /api/growth-audit:
    #   1. explicit body.lang ("en" | "zh")
    #   2. query ?lang=
    #   3. Referer contains /zh/ → zh
    #   4. Accept-Language header
    #   5. default to "en" (most analook organic traffic is English SEO)
    _detected_lang = _detect_report_lang(
        req.lang, request.query_params.get("lang"),
        request.headers.get("referer") or request.headers.get("origin"),
        request.headers.get("accept-language"), default="en",
    )

    # --- Domain cache: return cached result if available, fresh, and AI succeeded ---
    # Iris 2026-07-07 bug (plaud.ai from /zh/ showed an English report): the
    # cache was keyed on domain ONLY, so a ZH request hit the cached EN
    # report wholesale and the lang-aware pipeline never ran. Key by
    # (domain, lang) so each language gets its own cached analysis.
    cache_key = f"{domain.lower().replace('www.', '')}|{_detected_lang}"
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
                "lang": _detected_lang,
                "_cached": True,
            }
            _persist_report(job_id, jobs[job_id])
            return {"job_id": job_id, "status": "started", "cached": True}

    jobs[job_id] = {
        "status": "running",
        "product_name": product_name,
        "url": req.url if req.url.startswith("http") else f"https://{req.url}",
        "user_id": user["id"] if user else None,       # ← 记录报告归属人
        "lang": _detected_lang,                          # ← 报告语言
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
async def start_text_analysis(req: TextAnalyzeRequest, bg: BackgroundTasks, request: Request):
    """分析用户提供的文字描述（无需网站 URL）"""
    # ── 积分检查（与 /api/analyze 一致，防止匿名滥用烧 LLM 额度）──────────────
    user, err = await _require_credits(request)
    if err:
        return err

    job_id = str(uuid.uuid4())[:8]
    name = (req.product_name or "产品").strip()
    # Detect lang the same way /api/growth-audit does.
    _req_lang = (getattr(req, "lang", "") or "").strip().lower()
    if not _req_lang:
        _ref = request.headers.get("referer", "") or request.headers.get("origin", "")
        if "/zh/" in _ref:
            _req_lang = "zh"
        else:
            _al = (request.headers.get("accept-language") or "").lower()
            _req_lang = "en" if _al.startswith("en") else "zh"
    if _req_lang not in ("en", "zh"):
        _req_lang = "zh"
    jobs[job_id] = {
        "status": "running",
        "product_name": name,
        "url": "—",
        "mode": "text",
        "user_id": user["id"] if user else None,
        "lang": _req_lang,
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
    request: Request,
    file: UploadFile = File(...),
    product_name: str = Form(default="产品"),
):
    """分析上传的 PDF 文件（pitch deck、产品文档等）"""
    # ── 积分检查（在解析 PDF 之前，防止匿名滥用烧 LLM 额度）────────────────────
    user, err = await _require_credits(request)
    if err:
        return err

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

    # Detect lang from Referer / Accept-Language for the PDF flow (no body lang).
    _ref = request.headers.get("referer", "") or request.headers.get("origin", "")
    if "/zh/" in _ref:
        _req_lang = "zh"
    else:
        _al = (request.headers.get("accept-language") or "").lower()
        _req_lang = "en" if _al.startswith("en") else "zh"
    jobs[job_id] = {
        "status": "running",
        "product_name": name,
        "url": "—",
        "mode": "pdf",
        "user_id": user["id"] if user else None,
        "lang": _req_lang,
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


def _growth_audit_response(job: dict) -> dict:
    """Return the durable polling shape for an in-memory or restored job."""
    response = {
        "status": job["status"],
        "product_name": job.get("product_name"),
        "url": job.get("url"),
        "progress": job.get("progress"),
    }
    if job.get("reports"):
        response["reports"] = job["reports"]
        response["site_data_summary"] = job.get("site_data_summary")
    if job.get("timing"):
        response["timing"] = job["timing"]
    if job["status"] == "failed":
        response["error"] = job.get("error", "Unknown error")
    return response


async def _checkpoint_growth_audit(job_id: str, job: dict) -> None:
    """Persist enough state to resume an audit after a Fly machine rolls.

    Growth Audit work is deliberately asynchronous, so a rolling deploy can
    otherwise kill the task between poll requests. The completed report already
    uses this table; saving the initial checkpoint makes the unfinished state
    recoverable too.
    """
    try:
        from modules.supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return
        state = {
            "_partial": True,
            "lang": job.get("lang", "zh"),
            "_growth_audit_job": {
                "status": job.get("status", "running"),
                "progress": job.get("progress") or {},
                "timing": job.get("timing") or {},
            },
        }
        sb.table("reports").upsert({
            "id": job_id,
            "user_id": job.get("user_id"),
            "url": job.get("url"),
            "product_name": job.get("product_name") or "Growth Audit",
            "report": state,
            "markdown": "",
            "is_public": True,
            "status": "running",
        }).execute()
    except Exception as exc:
        # The live in-memory path remains available if persistence is briefly
        # unavailable; do not reject an already-paid audit for a checkpoint IO
        # failure.
        log.error("Failed to checkpoint growth audit %s: %s", job_id, exc)


async def _restore_growth_audit(job_id: str) -> dict | None:
    """Load a persisted audit and resume it once when its worker disappeared."""
    try:
        from modules.supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return None
        result = sb.table("reports").select(
            "id,user_id,url,product_name,report,status"
        ).eq("id", job_id).limit(1).execute()
        rows = result.data or []
        if not rows:
            return None
        row = rows[0]
        report = row.get("report") or {}
        if isinstance(report, str):
            report = _json.loads(report)
        if row.get("status") == "completed":
            return {
                "status": "completed",
                "product_name": row.get("product_name"),
                "url": row.get("url"),
                "progress": {k: "done" for k in ("fetch", "executive_summary", "diagnosis", "action_plan")},
                "reports": report.get("reports") or {},
                "site_data_summary": report.get("site_data_summary"),
            }
        state = report.get("_growth_audit_job") or {}
        if row.get("status") != "running" or not state:
            return None

        restored_email = None
        if row.get("user_id"):
            try:
                restored_user = sb.auth.admin.get_user_by_id(row["user_id"])
                restored_email = getattr(getattr(restored_user, "user", None), "email", None)
            except Exception:
                pass

        job = {
            "status": "running",
            "product_name": row.get("product_name") or row.get("url"),
            "url": row.get("url"),
            "lang": report.get("lang") or "zh",
            "user_id": row.get("user_id"),
            "user_email": restored_email,
            "progress": state.get("progress") or {
                "fetch": "pending", "executive_summary": "pending",
                "diagnosis": "pending", "action_plan": "pending",
            },
            "timing": state.get("timing") or {},
            "reports": None,
        }
        _growth_audit_jobs[job_id] = job
        # A resumed audit uses the original paid job ID; no second credit charge.
        asyncio.create_task(_run_growth_audit(
            job_id, job["url"], job["product_name"], job["lang"]
        ))
        log.warning("Resumed interrupted growth audit %s after worker restart", job_id)
        return job
    except Exception as exc:
        log.error("Failed to restore growth audit %s: %s", job_id, exc)
        return None


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

    # Detect report language. Order of precedence:
    #   1. explicit body.lang ("en" | "zh")
    #   2. query param ?lang=
    #   3. Referer contains "/zh/" → zh
    #   4. Accept-Language header parsed for primary language
    #   5. default to "zh" (Iris-base audience)
    lang = (body.get("lang") or request.query_params.get("lang") or "").strip().lower()
    if not lang:
        referer = request.headers.get("referer", "") or request.headers.get("origin", "")
        if "/zh/" in referer or "lang=zh" in referer:
            lang = "zh"
        else:
            al = (request.headers.get("accept-language") or "").lower()
            # English-prefixed = en, Chinese-prefixed = zh, else default zh
            if al.startswith("en"):
                lang = "en"
            elif al.startswith("zh"):
                lang = "zh"
    if lang not in ("en", "zh"):
        lang = "zh"

    job_id = f"ga-{uuid.uuid4().hex[:8]}"
    _growth_audit_jobs[job_id] = {
        "status": "running",
        "product_name": product_name or url,
        "url": url,
        "lang": lang,
        "user_id": user["id"] if user else None,
        "user_email": user.get("email") if user else None,
        "progress": {
            "fetch": "pending",
            "executive_summary": "pending",
            "diagnosis": "pending",
            "action_plan": "pending",
        },
        "timing": {},
        "reports": None,
    }

    await _checkpoint_growth_audit(job_id, _growth_audit_jobs[job_id])
    bg.add_task(_run_growth_audit, job_id, url, product_name, lang)
    return {"job_id": job_id, "status": "started", "lang": lang}


def _fly_replay_if_foreign(request: Request):
    """Ask fly-proxy to replay this request on the sibling machine.

    Iris 2026-07-07 bug (ga-343df106 "stuck at 8%, so slow"): analysis jobs
    live in per-process memory dicts, but the app runs on TWO Fly machines.
    The POST that creates a job lands on machine A; fly-proxy then load-
    balances the polling GETs, and every poll that hits machine B gets a
    404 — the progress bar freezes forever even though the audit is running
    fine on A. Responding with `fly-replay: elsewhere=true` makes the proxy
    transparently retry the request on the other machine.

    Returns a Response to short-circuit with, or None to handle locally.
    Loop guard: replayed requests carry fly-replay-src, so a job missing on
    BOTH machines falls through to the normal 404.
    """
    if request.headers.get("fly-replay-src"):
        return None          # already replayed once — genuinely not found
    if not os.environ.get("FLY_MACHINE_ID"):
        return None          # not running on Fly (local dev)
    return Response(status_code=204, headers={"fly-replay": "elsewhere=true"})


@app.get("/api/growth-audit/{job_id}")
async def get_growth_audit_status(job_id: str, request: Request):
    """Poll Growth Audit job status and get results."""
    job = _growth_audit_jobs.get(job_id)
    if not job:
        replay = _fly_replay_if_foreign(request)
        if replay is not None:
            return replay
        job = await _restore_growth_audit(job_id)
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)
    return _growth_audit_response(job)


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
    static viewer which fetches /api/share/audit/{job_id} client-side.

    Server-side injects the per-audit OG image URL so Twitter / LinkedIn /
    Slack previews show a custom card with the product name instead of
    the generic growth-audit.png. Social-card crawlers don't execute JS,
    so this swap must happen here, not in the client.
    """
    from starlette.responses import HTMLResponse
    import re as _re_inj
    try:
        with open("static/share-audit.html", "r", encoding="utf-8") as f:
            html = f.read()
        og_url = f"https://www.analook.com/api/og/audit/{job_id}.png"
        # Swap both og:image and twitter:image content values
        html = _re_inj.sub(
            r'(<meta[^>]+(?:property="og:image"|name="twitter:image")[^>]+content=")[^"]*"',
            lambda m: m.group(1) + og_url + '"',
            html,
        )
        return HTMLResponse(content=html)
    except Exception as e:
        log.warning("share_audit_page template inject failed: %s", e)
        return FileResponse("static/share-audit.html")


# In-memory OG card cache. Cards rarely change once an audit completes,
# so we cap at 1024 entries (FIFO) — bigger LRU not worth the complexity.
_og_card_cache: dict[str, bytes] = {}
_OG_CACHE_MAX = 1024


@app.get("/api/og/audit/{job_id}.png")
async def og_card_audit(job_id: str):
    """Dynamic OG / Twitter share card for /share/audit/{job_id}.

    Renders 1200×630 PNG with the product name in Instrument Serif —
    so Twitter / LinkedIn / Slack previews show WHAT the audit is about
    instead of the generic homepage card. Cached in-memory.
    """
    from starlette.responses import Response

    if job_id in _og_card_cache:
        return Response(
            content=_og_card_cache[job_id],
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )

    # Pull product name + URL from the same data sources /api/share/audit uses.
    product_name = "your product"
    audit_url = "analook.com"
    score_band = None
    key_stats: list = []
    try:
        job = _growth_audit_jobs.get(job_id) or {}
        if job.get("reports"):
            product_name = job.get("product_name") or product_name
            audit_url = job.get("url") or audit_url
        else:
            from modules.supabase_client import get_supabase
            sb = get_supabase()
            if sb:
                rs = sb.table("reports").select(
                    "product_name,url,report"
                ).eq("id", job_id).limit(1).execute()
                rows = rs.data or []
                if rows:
                    product_name = rows[0].get("product_name") or product_name
                    audit_url = rows[0].get("url") or audit_url
    except Exception as e:
        log.warning("og_card_audit lookup failed for %s: %s", job_id, e)

    # Tasteful default stats line. We could pull real numbers from
    # site_data_summary but that's an extra DB hit and noisy — the static
    # tagline below works for most preview contexts.
    key_stats = ["15 data sources", "60-second teardown", "by Iris @ Gingiris"]

    try:
        from modules.og_card import render_audit_share_card
        png = render_audit_share_card(
            product_name=product_name,
            audit_url=audit_url,
            score_band=score_band,
            key_stats=key_stats,
        )
    except Exception as e:
        log.error("og_card render failed for %s: %s", job_id, e)
        # Fall back to the static homepage card so previews still render
        return FileResponse("static/assets/og/homepage.png")

    # FIFO eviction — drop oldest entry when full
    if len(_og_card_cache) >= _OG_CACHE_MAX:
        try:
            _og_card_cache.pop(next(iter(_og_card_cache)))
        except StopIteration:
            pass
    _og_card_cache[job_id] = png

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


# ─── 评分卡 + 竞品考古时间轴：已抽成独立模块，减少并行改 app.py 的冲突面 ──────
# 改这两个功能请去 modules/scorecard_routes.py / modules/timeline_routes.py。
from modules.scorecard_routes import register as _register_scorecard_routes
from modules.timeline_routes import register as _register_timeline_routes
_register_scorecard_routes(app, _require_credits, _extract_user)
_register_timeline_routes(app)


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


@app.post("/api/admin/provider-alerts/check")
async def admin_provider_alerts_check(request: Request):
    """Run the protected provider-credit monitor.

    Header: X-Autopilot-Tick-Token. ``?dry_run=true`` validates the decision
    path without sending email or changing persistent alert state.
    """
    expected = (os.environ.get("AUTOPILOT_TICK_TOKEN") or "").strip()
    got = (request.headers.get("X-Autopilot-Tick-Token") or "").strip()
    if not expected:
        return JSONResponse({"error": "AUTOPILOT_TICK_TOKEN not configured"}, status_code=503)
    if got != expected:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    dry_run = (request.query_params.get("dry_run") or "").lower() == "true"
    force = (request.query_params.get("force") or "").lower() == "true"
    from modules.provider_alerts import check_and_alert
    return await check_and_alert(force=force, dry_run=dry_run)


@app.get("/api/admin/recent-audits")
async def admin_recent_audits(request: Request):
    """Triage tool — list last N growth-audit rows with section presence/length
    so we can see which audits had a broken action_plan. Gated by
    AUTOPILOT_TICK_TOKEN.
    """
    expected = (os.environ.get("AUTOPILOT_TICK_TOKEN") or "").strip()
    if not expected:
        return JSONResponse({"error": "AUTOPILOT_TICK_TOKEN not configured"}, status_code=503)
    got = (request.headers.get("X-Autopilot-Tick-Token") or "").strip()
    if got != expected:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    try:
        limit_q = int(request.query_params.get("limit") or 10)
    except Exception:
        limit_q = 10
    limit_q = max(1, min(limit_q, 50))
    from modules.supabase_client import get_supabase
    sb = get_supabase()
    if not sb:
        return JSONResponse({"error": "supabase not configured"}, status_code=503)
    rs = sb.table("reports").select(
        "id,product_name,url,status,created_at,report"
    ).like("id", "ga-%").order("created_at", desc=True).limit(limit_q).execute()
    rows = rs.data or []
    out = []
    for r in rows:
        rep = r.get("report") or {}
        if isinstance(rep, str):
            try:
                rep = _json.loads(rep)
            except Exception:
                rep = {}
        reports = (rep or {}).get("reports") or {}
        out.append({
            "id":            r.get("id"),
            "product_name":  r.get("product_name"),
            "url":           r.get("url"),
            "status":        r.get("status"),
            "created_at":    r.get("created_at"),
            "exec_len":      len((reports.get("executive_summary") or "")),
            "diag_len":      len((reports.get("diagnosis_report") or "")),
            "plan_len":      len((reports.get("action_plan") or "")),
            "lang":          (rep or {}).get("lang"),
            "sources":       (rep or {}).get("sources"),
        })
    return {"recent_audits": out}


@app.get("/api/admin/growth-audit-metrics")
async def admin_growth_audit_metrics(request: Request):
    """Observed Growth Audit latency from persisted reports.

    Timing lives in the report JSON so this works without a schema migration
    and lets us calculate the real average/P50/P95 once new runs complete.
    """
    expected = (os.environ.get("AUTOPILOT_TICK_TOKEN") or "").strip()
    if not expected:
        return JSONResponse({"error": "AUTOPILOT_TICK_TOKEN not configured"}, status_code=503)
    if (request.headers.get("X-Autopilot-Tick-Token") or "").strip() != expected:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    try:
        limit_q = int(request.query_params.get("limit") or 100)
    except Exception:
        limit_q = 100
    limit_q = max(1, min(limit_q, 500))
    from modules.supabase_client import get_supabase
    sb = get_supabase()
    if not sb:
        return JSONResponse({"error": "supabase not configured"}, status_code=503)
    try:
        rows = (sb.table("reports").select("id,report").like("id", "ga-%")
                .eq("status", "completed").order("created_at", desc=True)
                .limit(limit_q).execute().data or [])
    except Exception as exc:
        # Supabase occasionally returns a transient upstream 5xx. Metrics
        # must fail closed without turning an admin observation into an app 500.
        log.warning("Growth audit metrics query failed: %s", exc)
        return JSONResponse({"error": "metrics temporarily unavailable"}, status_code=503)
    totals, stages, fallbacks = [], {}, 0
    for row in rows:
        report = row.get("report") or {}
        if isinstance(report, str):
            try:
                report = _json.loads(report)
            except Exception:
                continue
        timing = report.get("timing") or {}
        total = timing.get("total_seconds")
        if isinstance(total, (int, float)) and total >= 0:
            totals.append(float(total))
        for stage, seconds in (timing.get("stages") or {}).items():
            if isinstance(seconds, (int, float)) and seconds >= 0:
                stages.setdefault(stage, []).append(float(seconds))
        if (report.get("source") or report.get("sources") or {}).get("plan") == "deterministic fallback":
            fallbacks += 1
    totals.sort()
    def _percentile(p: float):
        if not totals:
            return None
        return round(totals[min(len(totals) - 1, int((len(totals) - 1) * p))], 3)
    return {
        "sample_size": len(totals),
        "completed_reports_scanned": len(rows),
        "average_seconds": round(sum(totals) / len(totals), 3) if totals else None,
        "p50_seconds": _percentile(0.50),
        "p95_seconds": _percentile(0.95),
        "fallback_plan_count": fallbacks,
        "stage_average_seconds": {
            stage: round(sum(values) / len(values), 3)
            for stage, values in stages.items() if values
        },
    }


@app.get("/api/admin/user-metrics")
async def admin_user_metrics(request: Request):
    """Live weekly user metrics — registrations, activation, paid conversion.

    Same logic as scripts/user_metrics.py but served as JSON over HTTP so
    we don't need to ship SUPABASE_SERVICE_KEY around to anyone running
    the script locally. Gated by AUTOPILOT_TICK_TOKEN.
    """
    expected = (os.environ.get("AUTOPILOT_TICK_TOKEN") or "").strip()
    if not expected:
        return JSONResponse({"error": "AUTOPILOT_TICK_TOKEN not configured"}, status_code=503)
    got = (request.headers.get("X-Autopilot-Tick-Token") or "").strip()
    if got != expected:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    from datetime import datetime, timedelta, timezone
    from collections import Counter
    from modules.supabase_client import get_supabase
    sb = get_supabase()
    if not sb:
        return JSONResponse({"error": "Supabase not configured"}, status_code=503)

    IRIS_EMAILS = {
        "iris103195@gmail.com",
        "gingiris1031@gmail.com",
        "iris.wei@gingiris.com",
    }
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    def _parse(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    # Pull users via direct REST (Iris 2026-06-19: supabase-py's
    # list_users() defaulted to 50 per page and only fetched the first
    # page → report showed 50 when reality is 100+). The /auth/v1/admin
    # endpoint accepts per_page=1000 in one shot, matching what
    # scripts/user_metrics.py does locally.
    users = []
    try:
        import httpx as _httpx
        _sb_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        _sb_key = (os.environ.get("SUPABASE_SERVICE_KEY")
                   or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
                   or "").strip()
        if _sb_url and _sb_key:
            _hdrs = {"apikey": _sb_key, "Authorization": f"Bearer {_sb_key}"}
            async with _httpx.AsyncClient(timeout=20) as _c:
                # per_page=1000 covers current scale; paginate just in case
                for _page in range(1, 6):  # up to 5000 users
                    _r = await _c.get(
                        f"{_sb_url}/auth/v1/admin/users",
                        params={"per_page": 1000, "page": _page},
                        headers=_hdrs,
                    )
                    if _r.status_code != 200:
                        log.warning("auth list_users HTTP %s on page %s: %s",
                                    _r.status_code, _page, _r.text[:200])
                        break
                    _batch = (_r.json() or {}).get("users") or []
                    if not _batch:
                        break
                    for u in _batch:
                        users.append({
                            "id": u.get("id"),
                            "email": u.get("email"),
                            "created_at": u.get("created_at"),
                        })
                    if len(_batch) < 1000:
                        break
    except Exception as e:
        log.warning("user-metrics list_users via REST failed: %s — falling back to supabase-py", e)
        for u in (sb.auth.admin.list_users() or []):
            users.append({
                "id": u.id,
                "email": u.email,
                "created_at": getattr(u, "created_at", None),
            })
    # created_at may be datetime obj — normalize to iso
    for u in users:
        if u["created_at"] and not isinstance(u["created_at"], str):
            try:
                u["created_at"] = u["created_at"].isoformat()
            except Exception:
                u["created_at"] = str(u["created_at"])

    profiles_resp = sb.table("profiles").select(
        "id,email,plan_type,credits_balance,credits_used,created_at"
    ).execute()
    profiles = {p["id"]: p for p in (profiles_resp.data or [])}

    reports_resp = sb.table("reports").select(
        "id,user_id,url,product_name,created_at"
    ).limit(2000).execute()
    reports = reports_resp.data or []

    external = [u for u in users if (u.get("email") or "").lower() not in IRIS_EMAILS]
    total = len(external)

    rpu = Counter()
    last_per_user = {}
    for r in reports:
        uid = r.get("user_id")
        if not uid:
            continue
        rpu[uid] += 1
        ts = _parse(r.get("created_at", ""))
        if ts and (uid not in last_per_user or ts > last_per_user[uid]):
            last_per_user[uid] = ts

    activated = [u for u in external if rpu.get(u["id"], 0) > 0]
    active_this_week = [
        u for u in external
        if last_per_user.get(u["id"]) and last_per_user[u["id"]] >= week_ago
    ]
    paid = [u for u in external
            if profiles.get(u["id"], {}).get("plan_type") in ("pro", "team", "autopilot", "autopilot_team")]
    new_this_week = [u for u in external
                     if _parse(u.get("created_at") or "") and _parse(u["created_at"]) >= week_ago]
    external_reports = [
        r for r in reports
        if r.get("user_id")
        and (profiles.get(r["user_id"], {}).get("email", "")).lower() not in IRIS_EMAILS
    ]
    reports_this_week = [
        r for r in external_reports
        if _parse(r.get("created_at") or "") and _parse(r["created_at"]) >= week_ago
    ]
    url_counter = Counter(
        (r.get("url") or "")[:60] for r in external_reports if r.get("url")
    )

    act_pct = round(100 * len(activated) / total, 1) if total else 0
    paid_pct = round(100 * len(paid) / total, 1) if total else 0
    act_to_paid_pct = round(100 * len(paid) / max(len(activated), 1), 1)

    return {
        "checked_at": now.isoformat(),
        "window_days": 7,
        "totals": {
            "external_users":     total,
            "activated_users":    len(activated),
            "activation_pct":     act_pct,
            "active_this_week":   len(active_this_week),
            "paid_users":         len(paid),
            "paid_pct":           paid_pct,
            "activated_to_paid_pct": act_to_paid_pct,
            "external_reports":   len(external_reports),
            "reports_this_week":  len(reports_this_week),
            "new_signups_this_week": len(new_this_week),
        },
        "new_this_week": [
            {
                "email":      u.get("email"),
                "created_at": (u.get("created_at") or "")[:10],
                "reports":    rpu.get(u["id"], 0),
            } for u in new_this_week
        ],
        "active_this_week": [
            {
                "email":       u.get("email"),
                "last_report": last_per_user[u["id"]].strftime("%Y-%m-%d"),
                "total_reports": rpu[u["id"]],
            } for u in active_this_week
        ],
        "top_5_urls": [
            {"url": url, "count": n} for url, n in url_counter.most_common(5)
        ],
        "paid_users": [
            {
                "email": u.get("email"),
                "plan":  profiles.get(u["id"], {}).get("plan_type"),
            } for u in paid
        ],
    }


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
    from modules.provider_alerts import check_and_alert
    provider_health = await check_and_alert()
    result = await tick_due(limit=limit)
    result["provider_health"] = provider_health
    return result


async def _run_growth_audit(job_id: str, url: str, product_name: str = None, lang: str = "zh"):
    """Background task to run the full growth audit."""
    try:
        result = await run_growth_audit(
            url=url,
            product_name=product_name,
            job_id=job_id,
            jobs_dict=_growth_audit_jobs,
            lang=lang,
        )

        if result.get("error"):
            _growth_audit_jobs[job_id]["status"] = "failed"
            _growth_audit_jobs[job_id]["error"] = result["error"]
        else:
            _growth_audit_jobs[job_id]["status"] = "completed"
            _growth_audit_jobs[job_id]["product_name"] = result.get("product_name", product_name)
            _growth_audit_jobs[job_id]["reports"] = result.get("reports", {})
            _growth_audit_jobs[job_id]["site_data_summary"] = result.get("site_data_summary")

            # Save to Supabase — always persist so share links survive server restarts.
            # Unauthenticated audits are saved with user_id=None and is_public=True.
            user_id = _growth_audit_jobs[job_id].get("user_id")
            try:
                await save_report_to_db(
                    job_id=job_id,
                    user_id=user_id,
                    url=url,
                    product_name=result.get("product_name", ""),
                    report=result,
                    markdown=_json.dumps(result.get("reports", {}), ensure_ascii=False)[:50000],
                    is_public=True,
                )
            except Exception as e:
                log.error("Failed to save growth audit to DB: %s", e)

            # Completion email is deliberately best-effort: a Resend outage
            # must never turn a finished audit into a failed user job.
            user_email = _growth_audit_jobs[job_id].get("user_email")
            if user_email and not _growth_audit_jobs[job_id].get("email_notified"):
                from modules.growth_audit_email import send_growth_audit_ready_email
                sent = await send_growth_audit_ready_email(
                    to_email=user_email,
                    product_name=result.get("product_name") or product_name or url,
                    job_id=job_id,
                    lang=lang,
                )
                _growth_audit_jobs[job_id]["email_notified"] = sent

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
                    _lang = (job.get("lang") or "zh").lower()
                    _timeout_note = (
                        "⏱️ Analysis timed out; this module did not complete."
                        if _lang.startswith("en")
                        else "⏱️ 分析超时，此模块未能完成。"
                    )
                    report = generate_report(
                        product_name, url,
                        job["results"].get("website", {}),
                        job["results"].get("social", {}),
                        job["results"].get("traffic", {}),
                        job["results"].get("producthunt", {}),
                        job["results"].get("ai_summary", {"success": False, "content": _timeout_note, "source": "timeout"}),
                        lang=_lang,
                    )
                    job["report"] = report
                    job["markdown"] = report_to_markdown(report)
                except Exception:
                    job["report"] = {"meta": {"product_name": product_name, "url": url, "note": "partial"}, "sections": job["results"]}
                    if (job.get("lang") or "").lower().startswith("en"):
                        job["markdown"] = f"# {product_name} Competitor Research Report (Partial)\n\n> Analysis timed out; the data below is for the modules that completed.\n"
                    else:
                        job["markdown"] = f"# {product_name} 竞品调研报告（部分）\n\n> 分析超时，以下为已完成模块的数据。\n"
            _persist_report(job_id, job)


async def _run_analysis(job_id: str):
    job = jobs[job_id]
    url = job["url"]
    domain = urlparse(url).netloc
    product_name = job["product_name"]
    from modules.github_oss import _parse_gh_url
    explicit_github_repo = _parse_gh_url(url) if domain.lower() in {"github.com", "www.github.com"} else (None, None)
    if not all(explicit_github_repo):
        explicit_github_repo = None

    # Propagate report language into a ContextVar so analysis modules
    # (funding/bizmodel/traffic_peaks/growth_strategy/github_oss) — which run
    # before report assembly and take no lang param — emit EN or ZH correctly.
    from modules.i18n import set_report_lang, _T
    set_report_lang(job.get("lang"))

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

    # ── Lightweight phase clock (zero-risk: just logs + stashes timings) ──
    # Lets us see which phase actually dominates a real run via `fly logs` or
    # the report's results._timings, before tuning any external-API timeout.
    import time as _time
    _clock = {"start": _time.monotonic(), "last": _time.monotonic()}
    job["results"]["_timings"] = {}

    def _mark(name: str):
        now = _time.monotonic()
        dt = round(now - _clock["last"], 1)
        job["results"]["_timings"][name] = dt
        log.info("[timing] %s %s=%.1fs (cumulative %.1fs)",
                 job_id, name, dt, now - _clock["start"])
        _clock["last"] = now

    # Phase 1: all modules run in parallel (including SEO Review Tools alongside DataForSEO)
    job["progress"]["pr_news"] = "running"
    results_phase1 = await asyncio.gather(
        _t(analyze_website(url), 40),
        _t(analyze_domain(domain), 20),
        _t(analyze_producthunt(domain, product_name), 25),
        _t(analyze_social(domain, product_name, website_social_links={}), 35),  # TwitterAPI.io <3s/handle, total <20s
        _t(analyze_pricing(url, product_name), 20),
        _t(analyze_github_oss(domain, product_name, {}, explicit_repo=explicit_github_repo), 25),
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

    _mark("phase1")

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
                    analyze_github_oss(domain, product_name, _ws_social or {}, explicit_repo=explicit_github_repo), timeout=20
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

    # TikTok/Facebook are useful supporting evidence, but they must not delay
    # the first strategic read.  Start them now and join them only while the
    # next phase (AI synthesis, traffic peaks, propagation) is in flight.
    # Previously this await held the whole pipeline for up to 35 seconds before
    # the AI call even began.
    _slow_social_tasks = [
        asyncio.create_task(_slow_tiktok()),
        asyncio.create_task(_slow_facebook()),
    ]
    await asyncio.gather(_retry_github(), _retry_funding(), return_exceptions=True)

    _mark("phase1.5_retries")

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

    _mark("phase1.8_twitter")

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
            signals.append(_T(
                f"Product Hunt launch: {ph_votes} votes, {ph_comments} comments" + (f" ({ph_date})" if ph_date else ""),
                f"Product Hunt 上线：{ph_votes} 票，{ph_comments} 评论" + (f"（{ph_date}）" if ph_date else "")))

        gh_stars = gh.get("stars", 0)
        gh_growth = (gh.get("insights") or {}).get("peak_growth_rate") or ""
        if gh_stars:
            signals.append(_T(
                f"GitHub Stars: {gh_stars:,}" + (f", peak growth {gh_growth}" if gh_growth else ""),
                f"GitHub Stars：{gh_stars:,}" + (f"，峰值增速 {gh_growth}" if gh_growth else "")))

        reddit_posts = len(reddit.get("top_posts", []))
        reddit_members = reddit.get("subreddit_members", 0)
        if reddit_posts:
            signals.append(_T(
                f"Reddit mentions: {reddit_posts} posts" + (f", community {reddit_members:,} members" if reddit_members else ""),
                f"Reddit 提及：{reddit_posts} 条帖子" + (f"，社区 {reddit_members:,} 成员" if reddit_members else "")))

        errors = [error_msg] if error_msg else [_T("Twitter API unavailable", "Twitter API 不可用")]
        return {
            "data_mode": "multi_channel_fallback",
            "note": _T("⚠️ Twitter API unavailable — the following are multi-channel aggregated propagation signals",
                       "⚠️ Twitter API 不可用，以下为多渠道综合传播信号"),
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
            propagation = _build_multi_channel_fallback(err or _T("Twitter propagation analysis failed", "Twitter 传播分析失败"))

        job["results"]["propagation"] = propagation
        job["progress"]["propagation"] = "done"

    async def _run_traffic_peaks():
        job["progress"]["traffic_peaks"] = "running"
        # Pass first_seen from website analysis to filter HN results before product launch
        # 2026-06-18 fix: prefer current_owner_since when ownership change
        # was detected (multi-year Wayback gap). Iris's analook.com Wayback
        # first_seen=2007 belongs to a previous owner; the current product
        # launched 2026-04. Using 2007 as the trends window pulls in
        # 2014-2017 "Analook by UIComet" data that has nothing to do with
        # the current product.
        _w = job["results"].get("website", {}) or {}
        website_first_seen = _w.get("current_owner_since") or _w.get("first_seen", "")
        peaks = await analyze_traffic_peaks(
            product_name, domain,
            producthunt=job["results"].get("producthunt", {}),
            social=job["results"].get("social", {}),
            first_seen=website_first_seen,
            github_oss=job["results"].get("github_oss", {}),
        )
        job["results"]["traffic_peaks"] = peaks
        job["progress"]["traffic_peaks"] = "done"

    async def _run_oss_growth_attribution():
        """Attach evidence-backed channel attribution to the existing GitHub section."""
        github_oss = job["results"].get("github_oss", {})
        if not isinstance(github_oss, dict) or not github_oss.get("found"):
            return {}
        attribution = await analyze_oss_growth_attribution(product_name, github_oss)
        github_oss["growth_attribution"] = attribution
        return attribution

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
                lang=job.get("lang", "en"),
            )
            job["results"]["ai_summary"] = ai
            return ai
        except Exception as ai_err:
            ai = {"success": False, "content": "", "note": f"AI 分析异常: {str(ai_err)[:100]}", "source": "error"}
            job["results"]["ai_summary"] = ai
            return ai

    # Run propagation + traffic_peaks + OSS attribution + AI summary in parallel
    phase2_results = await asyncio.gather(
        _run_propagation(), _run_traffic_peaks(), _run_oss_growth_attribution(), _run_ai_summary(),
        return_exceptions=True,
    )
    # Collect optional deep-social evidence after the decision-critical work
    # has started.  In the common case this is already finished by the time
    # the AI response arrives, so it is included in the final report without
    # extending time-to-first-insight.
    await asyncio.gather(*_slow_social_tasks, return_exceptions=True)
    if isinstance(phase2_results[0], Exception):
        job["results"]["propagation"] = {"error": str(phase2_results[0])}
        job["progress"]["propagation"] = "error"
    if isinstance(phase2_results[1], Exception):
        job["results"]["traffic_peaks"] = {"error": str(phase2_results[1])}
        job["progress"]["traffic_peaks"] = "error"
    ai = phase2_results[3] if isinstance(phase2_results[3], dict) else job["results"].get("ai_summary", {})

    if _cancelled(): return

    # ================================================================
    _mark("phase2_prop_traffic_ai")

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
        _lang = (job.get("lang") or "zh").lower()
        # Reconcile github_oss into the RAW social data BEFORE generate_report,
        # so every derived artifact (summary channel lines, growth_score
        # distribution, strategy_radar, thesis) is computed from the reconciled
        # channels. Doing it only after generate_report left the summary text
        # saying "not detected: github" while github_oss showed a 511-star repo
        # in the same report (0bee037a) — cross-source contradiction.
        try:
            from modules.report import reconcile_github_channel
            reconcile_github_channel(
                {"social_media": job["results"].get("social", {})},
                job["results"].get("github_oss", {}))
        except Exception:
            pass
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
            lang=_lang,
        )

        growth_strategy = job["results"].get("growth_strategy", {})
        report["sections"]["growth_strategy"] = growth_strategy
        report["sections"]["pricing"] = job["results"].get("pricing", {})
        report["sections"]["github_oss"] = job["results"].get("github_oss", {})
        # 修 bug：开源分析匹配到 GitHub repo 时，回填「账号匹配」的 github channel，
        # 避免同一报告里开源分析显示 GitHub、账号匹配却缺 GitHub 的矛盾。
        try:
            from modules.report import reconcile_github_channel
            reconcile_github_channel(report["sections"], report["sections"]["github_oss"])
        except Exception:
            pass
        report["sections"]["pr_news"]    = job["results"].get("pr_news", {})
        report["sections"]["funding"]    = job["results"].get("funding", {})
        report["sections"]["bizmodel"]   = job["results"].get("bizmodel", {})

        # Recompute strategy radar now that ALL sections are available
        from modules.report import _compute_strategy_radar
        report["sections"]["strategy_radar"] = _compute_strategy_radar(report["sections"], _lang)

        job["report"] = report
        try:
            job["markdown"] = report_to_markdown(report)
        except Exception:
            if _lang.startswith("en"):
                job["markdown"] = f"# {product_name} Competitor Research Report\n\n> Markdown export failed; view the online report instead.\n"
            else:
                job["markdown"] = f"# {product_name} 竞品调研报告\n\n> Markdown 导出出错，请查看在线报告。\n"
        job["progress"]["report"] = "done"
    except Exception as e:
        job["progress"]["report"] = "error"

    job["status"] = "completed"

    _persist_report(job_id, job)

    # Cache write is lang-scoped to match the lang-scoped read in
    # start_analysis (a ZH report must never be served to an EN request).
    cache_key = f"{domain.lower().replace('www.', '')}|{job.get('lang', 'en')}"
    _domain_cache[cache_key] = {"timestamp": time.time(), "job": job}


async def _run_text_analysis(job_id: str, text: str):
    """AI-only analysis from text description (no URL scraping)"""
    job = jobs[job_id]
    product_name = job["product_name"]
    job["progress"]["report"] = "running"
    try:
        ai = await generate_ai_summary_from_text(product_name, text, lang=(job.get("lang") or "zh"))
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
        from modules.supabase_client import normalize_new_free_tier_credits
        if (
            profile.get("plan_type") == "free"
            and profile.get("credits_monthly_quota") == 3
            and profile.get("credits_used", 0) == 0  # don't downgrade users mid-month
            and profile.get("created_at", "") > FREE_TIER_CUTOVER_ISO
        ):
            if normalize_new_free_tier_credits(user["id"]):
                new_quota = PLAN_CREDITS["free"]  # 2
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


# ─── First-touch attribution (objective acquisition capture) ───────────────
# Complements the self-report survey above. The browser (attribution.js) locks
# utm_* + referrer + landing path on the very first pageview; auth.js POSTs it
# here once the user is authenticated. Write-once: we only fill columns that
# are still NULL, so the channel that ORIGINALLY acquired the user is never
# overwritten by a later visit / second device.

_ATTR_FIELDS = (
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
)


@app.post("/api/profile/attribution")
async def submit_first_touch_attribution(request: Request):
    """Record the user's first-touch acquisition attribution.

    Body (all optional): {
        "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
        "referrer", "landing_path", "ts"
    }
    Write-once — only fills profiles columns that are currently NULL.
    Returns {"ok": True, "written": bool}.
    """
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "请先登录", "code": "AUTH_REQUIRED"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    def _clip(v, n):
        return (str(v).strip()[:n]) or None if v else None

    payload = {f"first_{k}": _clip(body.get(k), 200) for k in _ATTR_FIELDS}
    payload["first_referrer"] = _clip(body.get("referrer"), 500)
    payload["first_landing_path"] = _clip(body.get("landing_path"), 300)

    # Nothing meaningful to record (e.g. localStorage was empty) → no-op.
    if not any(payload.values()):
        return {"ok": True, "written": False}

    from datetime import datetime, timezone
    payload["first_touch_at"] = datetime.now(timezone.utc).isoformat()

    from modules.supabase_client import get_supabase
    sb = get_supabase()
    if not sb:
        return JSONResponse({"error": "Supabase 未配置"}, status_code=503)

    try:
        # Write-once: filter on first_touch_at IS NULL so a row that already
        # has attribution is left untouched (matches zero rows → no-op).
        res = (
            sb.table("profiles")
            .update(payload)
            .eq("id", user["id"])
            .is_("first_touch_at", "null")
            .execute()
        )
        written = bool(getattr(res, "data", None))
    except Exception as e:
        log.error("Failed to save first-touch attribution for %s: %s", user["id"], e)
        return JSONResponse({"error": "保存失败"}, status_code=500)

    return {"ok": True, "written": written}


@app.post("/api/redeem")
async def redeem_promo_code(request: Request):
    """Redeem a promo code for bonus credits.

    Body: {"code": "GINGIRIS20"}
    Returns: {"ok": True, "credits_added": 20, "new_balance": 22}
    Errors: 401 AUTH_REQUIRED | 400 INVALID_CODE | 409 ALREADY_REDEEMED | 503 DB unavailable
    """
    user = await _extract_user(request)
    if not user:
        return JSONResponse({"error": "请先登录", "code": "AUTH_REQUIRED"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    code = (body.get("code") or "").strip().upper()
    if not code:
        return JSONResponse({"error": "请输入兑换码", "code": "MISSING_CODE"}, status_code=400)

    from modules.supabase_client import get_supabase
    sb = get_supabase()
    if not sb:
        return JSONResponse({"error": "Service unavailable"}, status_code=503)

    # 1. Look up the promo code
    try:
        promo_result = sb.table("promo_codes").select(
            "code, credits_reward, max_uses, used_count, active"
        ).eq("code", code).eq("active", True).execute()
    except Exception as e:
        log.error("promo_codes lookup failed code=%s: %s", code, e)
        return JSONResponse({"error": "服务暂时不可用，请稍后重试"}, status_code=503)

    if not promo_result.data:
        return JSONResponse({"error": "无效的兑换码", "code": "INVALID_CODE"}, status_code=400)

    promo = promo_result.data[0]

    # 2. Check max_uses
    if promo["max_uses"] is not None and promo["used_count"] >= promo["max_uses"]:
        return JSONResponse({"error": "该兑换码已达到使用上限", "code": "CODE_EXHAUSTED"}, status_code=400)

    # 3. Check if user already redeemed this code
    try:
        redemption_check = sb.table("promo_redemptions").select("id").eq(
            "user_id", user["id"]
        ).eq("code", code).execute()
    except Exception as e:
        log.error("promo_redemptions check failed user=%s code=%s: %s", user["id"], code, e)
        return JSONResponse({"error": "服务暂时不可用，请稍后重试"}, status_code=503)

    if redemption_check.data:
        return JSONResponse({"error": "你已经使用过这个兑换码了", "code": "ALREADY_REDEEMED"}, status_code=409)

    credits_to_add = promo["credits_reward"]

    # 4. Add credits to user profile
    try:
        profile_result = sb.table("profiles").select(
            "credits_balance"
        ).eq("id", user["id"]).single().execute()
        current_balance = profile_result.data["credits_balance"]
        new_balance = current_balance + credits_to_add

        sb.table("profiles").update({
            "credits_balance": new_balance
        }).eq("id", user["id"]).execute()
    except Exception as e:
        log.error("Failed to add credits user=%s code=%s: %s", user["id"], code, e)
        return JSONResponse({"error": "积分更新失败，请重试"}, status_code=500)

    # 5. Record redemption + increment used_count
    try:
        sb.table("promo_redemptions").insert({
            "user_id": user["id"],
            "code": code,
        }).execute()
        sb.table("promo_codes").update({
            "used_count": promo["used_count"] + 1
        }).eq("code", code).execute()
    except Exception as e:
        # Non-fatal: credits already added, just log
        log.error("Failed to record promo redemption user=%s code=%s: %s", user["id"], code, e)

    # Mirror the approved bonus with an idempotent, non-PII audit event.
    # The Supabase balance update above remains authoritative during migration.
    try:
        from modules.insforge_client import record_account_credit_event
        profile = await get_user_profile(user["id"])
        if profile and not await record_account_credit_event(
            profile,
            int(credits_to_add),
            "promo_credit_grant",
            source_event_id=f"promo:{user['id']}:{code}",
            metadata={"promo_code": code},
        ):
            log.warning("Promo credit mirrored without an InsForge ledger row user=%s", user["id"])
    except Exception as mirror_error:
        log.warning("Promo credit ledger mirror failed user=%s: %s", user["id"], mirror_error)

    log.info("Promo code redeemed: user=%s code=%s credits_added=%d", user["id"], code, credits_to_add)
    return {"ok": True, "credits_added": credits_to_add, "new_balance": new_balance}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str, request: Request):
    job = jobs.get(job_id)
    if not job:
        # Dual-machine split-brain: the job may live on the sibling machine.
        replay = _fly_replay_if_foreign(request)
        if replay is not None:
            return replay
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
async def get_report(job_id: str, request: Request):
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
    # 4. Dual-machine split-brain: an in-flight job may live on the sibling.
    replay = _fly_replay_if_foreign(request)
    if replay is not None:
        return replay
    return JSONResponse({"error": "Job not found"}, status_code=404)


# ─── Public reports gallery (Iris 2026-07-07: SEO/GEO play — surface all
# public customer reports at /reports/ with product categories) ────────────

_CATEGORY_RULES = [
    # (category, keyword regex over "product_name url") — first match wins.
    ("Crypto / Web3", r"crypto|web3|defi|blockchain|token|coin|nft|dao|wallet|exchange|trading|hyperliquid|solana|onchain|\.finance"),
    ("AI / Agents",   r"\bai\b|agent|gpt|llm|copilot|assistant|\.ai\b|neural|genai|chatbot"),
    ("Dev Tools",     r"\bdev\b|\bapi\b|sdk|cli|database|deploy|hosting|code|git|terminal|\.dev\b|framework|infra"),
    ("Design / Creative", r"design|creative|video|image|photo|音乐|music|art|render|canva|figma"),
    ("E-commerce",    r"shop|commerce|store|retail|merch|dropship"),
    ("Marketing / SEO", r"seo|marketing|growth|analytics|ads|campaign|content"),
    ("Productivity",  r"note|task|calendar|productivity|workspace|docs|wiki|crm|meeting"),
]
_public_reports_cache = {"ts": 0.0, "data": None}


def _categorize_report(name: str, url: str) -> str:
    import re as _re2
    hay = f"{name} {url}".lower()
    for cat, pat in _CATEGORY_RULES:
        if _re2.search(pat, hay):
            return cat
    return "SaaS / Other"


async def _public_reports_data():
    """Shared data source for the gallery API, the SSR gallery pages, and the
    dynamic sitemap. Returns the cached list of public report dicts.

    Deduped by domain (latest wins), partial audits excluded, 5-min cache.
    """
    if _public_reports_cache["data"] is not None and \
       time.time() - _public_reports_cache["ts"] < 300:
        return _public_reports_cache["data"]["reports"]
    try:
        from modules.supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return {"reports": []}
        # LIGHT query only — pulling the full `report` JSONB for 120 rows
        # (some >100KB each) blew past client limits and dropped the whole
        # endpoint into the exception path (round-1 self-test: 328 public
        # rows in DB, endpoint returned []). The PostgREST arrow selector
        # extracts just the _partial flag.
        rows = sb.table("reports") \
            .select("id,url,product_name,created_at,partial:report->_partial") \
            .eq("is_public", True) \
            .order("created_at", desc=True).limit(150).execute().data or []
    except Exception as e:
        log.warning("public-reports query failed: %s", e)
        return []

    out, seen_domains = [], set()
    for r in rows:
        # Skip partial (still-generating / deploy-orphaned) audits
        if r.get("partial"):
            continue
        url = (r.get("url") or "").strip()
        if not url or url == "—":
            continue  # text/PDF analyses have no URL — skip in the gallery
        domain = urlparse(url if url.startswith("http") else f"https://{url}").netloc \
            .lower().replace("www.", "")
        if not domain or domain in seen_domains:
            continue
        seen_domains.add(domain)
        name = (r.get("product_name") or domain.split(".")[0].capitalize()).strip()
        out.append({
            "id": r["id"],
            "product_name": name[:60],
            "domain": domain,
            "kind": "growth-audit" if str(r["id"]).startswith("ga-") else "analysis",
            "category": _categorize_report(name, url),
            "created_at": (r.get("created_at") or "")[:10],
        })
        if len(out) >= 60:
            break
    _public_reports_cache["ts"] = time.time()
    _public_reports_cache["data"] = {"reports": out}
    return out


@app.get("/api/public-reports")
async def public_reports():
    """List public completed reports for the /reports/ gallery (JSON API)."""
    return {"reports": await _public_reports_data()}


# In-flight (job_id, target) translation runs on THIS machine — prevents
# duplicate LLM spend when the frontend polls while a run is active.
_translations_inflight: set = set()


@app.post("/api/report/{job_id}/translate")
async def translate_report(job_id: str, request: Request):
    """One-click report language toggle (Iris 2026-07-07 feature).

    Body: {"target": "zh" | "en"}
    Translates the AI-generated markdown of a completed report into the
    target language via LLM, caches the result under report._translations
    and persists it — so each report translates at most once per language;
    later toggles return instantly from cache.

    Handles both report shapes:
    - growth-audit (ga-*): report["reports"] = {executive_summary,
      diagnosis_report, action_plan}
    - competitor analysis: report["sections"]["ai_insights"]["content"]
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    target = (body.get("target") or "").strip().lower()
    if target not in ("en", "zh"):
        return JSONResponse({"error": "target must be 'en' or 'zh'"}, status_code=400)

    # ── Load the report (memory → disk → Supabase, same order as get_report) ──
    report = None
    job = jobs.get(job_id)
    if job and job.get("report"):
        report = job["report"]
    ga_job = _growth_audit_jobs.get(job_id)
    if report is None and ga_job and ga_job.get("reports"):
        # growth-audit in-memory shape: promote to the persisted result shape
        report = {"reports": ga_job["reports"], "url": ga_job.get("url"),
                  "product_name": ga_job.get("product_name")}
    if report is None:
        path = os.path.join(REPORTS_DIR, f"{job_id}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    report = _json.load(f).get("report")
            except Exception:
                pass
    if report is None:
        try:
            from modules.supabase_client import get_supabase
            sb = get_supabase()
            if sb:
                result = sb.table("reports").select("report").eq("id", job_id).limit(1).execute()
                if result.data and result.data[0].get("report"):
                    report = result.data[0]["report"]
        except Exception:
            pass
    if report is None:
        replay = _fly_replay_if_foreign(request)
        if replay is not None:
            return replay
        return JSONResponse({"error": "Report not found"}, status_code=404)

    # ── Cache hit? ──
    cached = (report.get("_translations") or {}).get(target)
    if cached:
        return {"target": target, "docs": cached, "cached": True}

    # ── Collect the translatable documents by shape ──
    if isinstance(report.get("reports"), dict):          # growth-audit
        docs = {k: v for k, v in report["reports"].items()
                if isinstance(v, str) and v.strip()}
    else:                                                 # competitor analysis
        ai = ((report.get("sections") or {}).get("ai_insights") or {})
        docs = {}
        if isinstance(ai.get("content"), str) and ai["content"].strip():
            docs["ai_insights"] = ai["content"]
    if not docs:
        return JSONResponse({"error": "Nothing translatable in this report"}, status_code=422)

    # ── Async translation (NB: MUST NOT translate inline). Full-document
    # LLM translation takes 60-180s; Fly's proxy idle-timeout kills the
    # response first (observed 2026-07-07: curl got empty bodies at 240s).
    # Instead: mark in-flight, run in background, persist to Supabase, and
    # let the frontend re-POST this endpoint every few seconds — the cache
    # branch above returns the finished docs once persisted. The inflight
    # guard is per-machine only; a poll landing on the sibling machine may
    # start a duplicate LLM run (~$0.01 wasted, results converge) — known
    # trade-off, acceptable at current traffic.
    inflight_key = (job_id, target)
    if inflight_key in _translations_inflight:
        return JSONResponse({"status": "translating", "target": target}, status_code=202)

    _translations_inflight.add(inflight_key)

    async def _translate_and_persist():
        try:
            from modules.translate_report import translate_docs
            translated = await translate_docs(docs, target)
            report.setdefault("_translations", {})[target] = translated
            try:
                path = os.path.join(REPORTS_DIR, f"{job_id}.json")
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        data = _json.load(f)
                    data["report"] = report
                    with open(path, "w", encoding="utf-8") as f:
                        _json.dump(data, f, ensure_ascii=False, default=str)
            except Exception:
                pass
            try:
                from modules.supabase_client import get_supabase
                sb = get_supabase()
                if sb:
                    sb.table("reports").update({"report": report}).eq("id", job_id).execute()
            except Exception as e:
                log.warning("Translation persisted to disk only (Supabase update failed): %s", e)
            log.info("Report %s translated → %s (%d docs)", job_id, target, len(translated))
        except Exception as e:
            log.error("Report translation failed for %s → %s: %s", job_id, target, e)
        finally:
            _translations_inflight.discard(inflight_key)

    asyncio.create_task(_translate_and_persist())
    return JSONResponse({"status": "translating", "target": target}, status_code=202)


@app.get("/api/export/{job_id}")
async def export_markdown(job_id: str):
    job = jobs.get(job_id)
    markdown = None
    report = None
    product_name = "report"
    if job:
        markdown = job.get("markdown")
        report = job.get("report")
        product_name = job.get("product_name", "report")
    if not report and not markdown:
        path = os.path.join(REPORTS_DIR, f"{job_id}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            markdown = data.get("markdown")
            report = data.get("report")
            product_name = data.get("product_name", "report")
    # Supabase fallback — survives Fly.io restarts where memory/disk are lost
    if not report and not markdown:
        try:
            from modules.supabase_client import get_supabase
            sb = get_supabase()
            if sb:
                result = sb.table("reports").select("markdown,report,product_name").eq("id", job_id).limit(1).execute()
                if result.data:
                    markdown = result.data[0].get("markdown")
                    report = result.data[0].get("report")
                    product_name = result.data[0].get("product_name", "report") or "report"
        except Exception:
            pass
    # Regenerate markdown fresh from the structured report whenever we have it:
    # the stored markdown may be a stale "export failed" stub from a past
    # report_to_markdown crash (e.g. a None cpc/volume in the keyword table).
    # report_to_markdown is a cheap pure function, so always prefer a live render.
    if report:
        try:
            from modules.report import report_to_markdown
            fresh = report_to_markdown(report)
            if fresh and fresh.strip():
                markdown = fresh
        except Exception as _e:
            log.error("export: report_to_markdown failed for %s: %s", job_id, _e)
    if not markdown or "export failed" in markdown.lower():
        return JSONResponse({"error": "Report not ready"}, status_code=404)
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
    lang = None
    if job:
        product_name = job.get("product_name")
        url = job.get("url")
        lang = job.get("lang")
    else:
        path = os.path.join(REPORTS_DIR, f"{job_id}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            product_name = data.get("product_name")
            url = data.get("url")
            lang = ((data.get("report") or {}).get("meta") or {}).get("lang") or data.get("lang")
    # Supabase fallback (survives Railway restarts / cross-instance shares)
    if not product_name:
        try:
            from modules.supabase_client import get_supabase
            sb = get_supabase()
            if sb:
                result = sb.table("reports").select(
                    "product_name,url,report"
                ).eq("id", job_id).limit(1).execute()
                if result.data:
                    product_name = result.data[0].get("product_name")
                    url = result.data[0].get("url")
                    lang = ((result.data[0].get("report") or {}).get("meta") or {}).get("lang")
        except Exception as e:
            log.error("Share info fetch from Supabase failed: %s", e)
    if not product_name:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    from urllib.parse import quote_plus
    # Route by job type: growth-audit IDs (prefix `ga-`) live at
    # /share/audit/{job_id}; classic analyze reports live at /report/{job_id}.
    # The old code always returned /report/, which 404'd silently for growth
    # audits (the report page loaded but the analyze API didn't have the job,
    # so the user got an empty homepage). Detect the prefix and route right.
    if job_id.startswith("ga-"):
        base_url = f"/share/audit/{job_id}"
    else:
        base_url = f"/report/{job_id}"
    utm = f"utm_source=gingiris_tool&utm_medium=share&utm_campaign=competitive_analysis&utm_content={quote_plus(product_name)}"
    share_url = f"{base_url}?{utm}"

    _en = (lang or "").lower().startswith("en")
    share_text = (f"🔍 {product_name} — Competitor Research Report · Powered by Analook"
                  if _en else f"🔍 {product_name} 竞品调研报告 — Powered by Analook")
    return {
        "job_id": job_id,
        "product_name": product_name,
        "share_url": share_url,
        "utm_params": utm,
        "share_text": share_text,
    }


@app.get("/report/{job_id}")
async def shared_report_page(job_id: str, request: Request):
    # Growth-audit IDs (prefix `ga-`) belong at /share/audit/{job_id}, not
    # here. Shared links from older Share buttons used this path and got
    # the homepage (which silently 404'd when fetching /api/report/{ga-…}).
    # Redirect with the query string preserved so the audit OG card +
    # UTM tracking still work.
    if job_id.startswith("ga-"):
        from starlette.responses import RedirectResponse
        qs = ("?" + request.url.query) if request.url.query else ""
        return RedirectResponse(url=f"/share/audit/{job_id}{qs}", status_code=302)
    # Serve zh/index.html for ?lang=zh or Referer from /zh/
    lang = request.query_params.get("lang", "")
    referer = request.headers.get("referer", "")
    zh = lang == "zh" or "/zh/" in referer
    shell = "static/zh/index.html" if zh else "static/index.html"
    return await _serve_report_shell(shell, job_id, zh=zh)


@app.get("/zh/report/{job_id}")
async def shared_report_page_zh(job_id: str, request: Request):
    """Chinese-shell report page — same data, zh/index.html renders it."""
    if job_id.startswith("ga-"):
        from starlette.responses import RedirectResponse
        qs = ("?" + request.url.query) if request.url.query else ""
        return RedirectResponse(url=f"/share/audit/{job_id}{qs}", status_code=302)
    return await _serve_report_shell("static/zh/index.html", job_id, zh=True)


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

    # The MCP streamable-HTTP endpoint lives at /mcp/ (trailing slash). A bare
    # POST /mcp — which is exactly the URL our docs tell clients to use —
    # otherwise 405s. Register a 307 (method + body preserving) redirect so the
    # documented no-slash URL works. Must be added BEFORE the mount so the
    # exact-path route wins over the /mcp/* prefix mount.
    from starlette.responses import RedirectResponse as _RR

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"], include_in_schema=False)
    async def _mcp_trailing_slash(request: Request):
        qs = ("?" + request.url.query) if request.url.query else ""
        return _RR(url=f"/mcp/{qs}", status_code=307)

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
# ─── SEO: per-report SSR head injection + SSR gallery + dynamic sitemap ──────
# Crawlers (esp. AI crawlers GPTBot/PerplexityBot) often don't execute JS.
# The report/gallery pages are SPAs that fetch content client-side, so a bare
# crawl saw: (a) every /report/{id} canonical-tagged to the HOMEPAGE (Google
# then treats all 60 report pages as dupes of "/" and indexes none), and
# (b) a gallery whose 60 internal links + product names existed only after JS
# ran. These helpers inject the real per-report <head> + crawlable card links
# server-side so the reports become an indexable, AI-citable content asset.
import html as _html
import re as _seo_re


async def _lookup_report_meta(job_id: str):
    """3-tier lookup (memory → disk → Supabase) → {product_name, url} or None."""
    product_name = url = None
    job = jobs.get(job_id)
    if job:
        product_name, url = job.get("product_name"), job.get("url")
    if not product_name:
        try:
            path = os.path.join(REPORTS_DIR, f"{job_id}.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    d = _json.load(f)
                product_name, url = d.get("product_name"), d.get("url")
        except Exception:
            pass
    if not product_name:
        try:
            from modules.supabase_client import get_supabase
            sb = get_supabase()
            if sb:
                res = sb.table("reports").select("product_name,url") \
                    .eq("id", job_id).limit(1).execute()
                if res.data:
                    product_name = res.data[0].get("product_name")
                    url = res.data[0].get("url")
        except Exception as e:
            log.warning("_lookup_report_meta failed for %s: %s", job_id, e)
    if not product_name:
        return None
    return {"product_name": product_name, "url": url or ""}


def _report_seo(product_name: str, domain: str, zh: bool):
    """Build (title, description) for a competitor-analysis report page."""
    if zh:
        title = f"{product_name} 竞品分析报告 2026 — 流量 / SEO / 增长策略 | Analook"
        desc = (f"{product_name}（{domain}）的完整竞品情报：自然流量估算、SEO 关键词布局、"
                f"社媒声量、定价与增长策略。由 Analook 用 15 个数据源在 60 秒内生成。")
    else:
        title = f"{product_name} Competitor Analysis 2026 — Traffic, SEO & Growth Strategy | Analook"
        desc = (f"Full competitive intelligence on {product_name} ({domain}): organic traffic "
                f"estimates, SEO keyword footprint, social reach, pricing and growth strategy. "
                f"Generated by Analook across 15 data sources in 60 seconds.")
    return title, desc


async def _serve_report_shell(shell_path: str, job_id: str, zh: bool):
    """Serve the SPA shell with per-report SEO head injected. Falls back to the
    plain shell if the report can't be found (SPA still renders client-side)."""
    from starlette.responses import HTMLResponse
    try:
        meta = await _lookup_report_meta(job_id)
        if not meta:
            return FileResponse(shell_path)
        with open(shell_path, "r", encoding="utf-8") as f:
            htmldoc = f.read()
        name = meta["product_name"]
        raw_url = meta["url"] or ""
        domain = urlparse(raw_url if raw_url.startswith("http") else f"https://{raw_url}") \
            .netloc.lower().replace("www.", "") or name
        title, desc = _report_seo(name, domain, zh)
        path = f"/zh/report/{job_id}" if zh else f"/report/{job_id}"
        canonical = f"https://www.analook.com{path}"
        e = _html.escape
        # 1) title
        htmldoc = _seo_re.sub(r"<title>.*?</title>", f"<title>{e(title)}</title>", htmldoc, count=1, flags=_seo_re.S)
        # 2) description
        htmldoc = _seo_re.sub(r'(<meta\s+name="description"\s+content=")[^"]*(")',
                              lambda m: m.group(1) + e(desc) + m.group(2), htmldoc, count=1)
        # 3) canonical → the report's OWN url (fixes the homepage-canonical bug)
        htmldoc = _seo_re.sub(r'(<link\s+rel="canonical"\s+href=")[^"]*(")',
                              lambda m: m.group(1) + canonical + m.group(2), htmldoc, count=1)
        # 4) og:title / og:description / og:url
        htmldoc = _seo_re.sub(r'(<meta\s+property="og:title"\s+content=")[^"]*(")',
                              lambda m: m.group(1) + e(title) + m.group(2), htmldoc, count=1)
        htmldoc = _seo_re.sub(r'(<meta\s+property="og:description"\s+content=")[^"]*(")',
                              lambda m: m.group(1) + e(desc) + m.group(2), htmldoc, count=1)
        htmldoc = _seo_re.sub(r'(<meta\s+property="og:url"\s+content=")[^"]*(")',
                              lambda m: m.group(1) + canonical + m.group(2), htmldoc, count=1)
        # 4b) Strip the shell's homepage hreflang alternates — on a report page
        # they'd wrongly point Google to "/" and collide with the per-report
        # alternates we inject below.
        htmldoc = _seo_re.sub(r'\s*<link\s+rel="alternate"\s+hreflang="[^"]*"[^>]*>', "", htmldoc)
        # 5) Report + BreadcrumbList JSON-LD + hreflang, injected before </head>
        jsonld = {
            "@context": "https://schema.org", "@type": "Report",
            "name": title, "headline": title, "description": desc, "url": canonical,
            "about": {"@type": "Organization", "name": name,
                      "url": (raw_url if raw_url.startswith("http") else f"https://{domain}")},
            "isPartOf": {"@type": "CollectionPage", "name": "Competitor Intelligence Reports",
                         "url": "https://www.analook.com/reports/"},
            "publisher": {"@type": "Organization", "name": "Analook",
                          "url": "https://www.analook.com",
                          "logo": {"@type": "ImageObject",
                                   "url": "https://www.analook.com/assets/favicon-192x192.png"}},
        }
        crumbs = {
            "@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Reports",
                 "item": "https://www.analook.com/reports/"},
                {"@type": "ListItem", "position": 2, "name": f"{name} Analysis", "item": canonical},
            ],
        }
        alt_en = f"https://www.analook.com/report/{job_id}"
        alt_zh = f"https://www.analook.com/zh/report/{job_id}"
        inject = (
            f'<script type="application/ld+json">{_json.dumps(jsonld, ensure_ascii=False)}</script>\n'
            f'<script type="application/ld+json">{_json.dumps(crumbs, ensure_ascii=False)}</script>\n'
            f'<link rel="alternate" hreflang="en" href="{alt_en}">\n'
            f'<link rel="alternate" hreflang="zh" href="{alt_zh}">\n'
            f'<link rel="alternate" hreflang="x-default" href="{alt_en}">\n'
        )
        htmldoc = htmldoc.replace("</head>", inject + "</head>", 1)
        return HTMLResponse(content=htmldoc)
    except Exception as ex:
        log.warning("_serve_report_shell inject failed for %s: %s", job_id, ex)
        return FileResponse(shell_path)


def _render_gallery_cards(reports: list, zh: bool) -> str:
    """SSR the report cards as crawlable <a> links (JS re-renders on load)."""
    e = _html.escape
    out = []
    for r in reports:
        rid = r["id"]
        name = r.get("product_name") or r.get("domain") or rid
        domain = r.get("domain") or ""
        cat = r.get("category") or "SaaS / Other"
        if str(rid).startswith("ga-"):
            href = f"/share/audit/{rid}"
        else:
            href = f"/zh/report/{rid}" if zh else f"/report/{rid}"
        label = (f"{e(name)} 竞品分析 — {e(cat)}" if zh
                 else f"{e(name)} competitor analysis — {e(cat)}")
        out.append(f'<a href="{href}" data-cat="{e(cat)}" class="report-card-ssr">'
                   f'<strong>{e(name)}</strong> <span>{e(domain)}</span> '
                   f'<em>{label}</em></a>')
    return "\n".join(out)


async def _serve_gallery(shell_path: str, zh: bool):
    """Serve the reports gallery with SSR cards + a real ItemList schema."""
    from starlette.responses import HTMLResponse
    try:
        reports = await _public_reports_data()
        with open(shell_path, "r", encoding="utf-8") as f:
            htmldoc = f.read()
        cards = _render_gallery_cards(reports, zh)
        # Inject crawlable cards right after the grid's opening tag; the client
        # JS overwrites #community-grid.innerHTML on load, so this is idempotent.
        htmldoc = _seo_re.sub(
            r'(<div\s+id="community-grid"[^>]*>)',
            lambda m: m.group(1) + "\n" + cards,
            htmldoc, count=1)
        # Comprehensive ItemList schema (the static one hardcoded only 3).
        base = "https://www.analook.com"
        items = []
        for i, r in enumerate(reports, 1):
            rid = r["id"]
            if str(rid).startswith("ga-"):
                u = f"{base}/share/audit/{rid}"
            else:
                u = f"{base}/zh/report/{rid}" if zh else f"{base}/report/{rid}"
            items.append({"@type": "ListItem", "position": i,
                          "name": f'{r.get("product_name") or r.get("domain")} Analysis',
                          "url": u})
        itemlist = {"@context": "https://schema.org", "@type": "ItemList",
                    "name": "Analook Competitor Intelligence Reports",
                    "numberOfItems": len(items), "itemListElement": items}
        htmldoc = htmldoc.replace(
            "</head>",
            f'<script type="application/ld+json">{_json.dumps(itemlist, ensure_ascii=False)}</script>\n</head>',
            1)
        return HTMLResponse(content=htmldoc)
    except Exception as ex:
        log.warning("_serve_gallery inject failed (%s): %s", shell_path, ex)
        return FileResponse(shell_path)


@app.get("/reports/")
@app.get("/reports/index.html")
async def reports_gallery_en():
    return await _serve_gallery("static/reports/index.html", zh=False)


@app.get("/zh/reports/")
@app.get("/zh/reports/index.html")
async def reports_gallery_zh():
    import os as _os
    shell = "static/zh/reports/index.html"
    if not _os.path.exists(shell):
        shell = "static/reports/index.html"
    return await _serve_gallery(shell, zh=True)


@app.get("/sitemap.xml")
async def dynamic_sitemap():
    """Static sitemap + every public analysis report URL appended.

    Only analysis reports (/report/{id}) are added — growth-audit share pages
    (/share/audit/ga-*) are intentionally noindex, so they stay out.
    """
    from starlette.responses import Response
    try:
        with open("static/sitemap.xml", "r", encoding="utf-8") as f:
            xml = f.read()
        reports = await _public_reports_data()
        today = time.strftime("%Y-%m-%d", time.gmtime())
        extra = []
        for r in reports:
            rid = r["id"]
            if str(rid).startswith("ga-"):
                continue  # noindex share pages
            lastmod = r.get("created_at") or today
            extra.append(
                f"  <url><loc>https://www.analook.com/report/{rid}</loc>"
                f"<lastmod>{lastmod}</lastmod><changefreq>monthly</changefreq>"
                f"<priority>0.6</priority>"
                f'<xhtml:link rel="alternate" hreflang="en" href="https://www.analook.com/report/{rid}"/>'
                f'<xhtml:link rel="alternate" hreflang="zh" href="https://www.analook.com/zh/report/{rid}"/>'
                "</url>")
        if extra and "</urlset>" in xml:
            # Ensure the xhtml namespace is present for hreflang alternates.
            if "xmlns:xhtml" not in xml:
                xml = xml.replace("<urlset ", '<urlset xmlns:xhtml="http://www.w3.org/1999/xhtml" ', 1)
            xml = xml.replace("</urlset>", "\n".join(extra) + "\n</urlset>")
        return Response(content=xml, media_type="application/xml")
    except Exception as ex:
        log.warning("dynamic_sitemap failed: %s", ex)
        return FileResponse("static/sitemap.xml")


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

# ---------------------------------------------------------------------------
# Admin: run database migrations (protected by AUTOPILOT_TICK_TOKEN)
# ---------------------------------------------------------------------------
@app.post("/api/admin/migrate")
async def admin_run_migration(request: Request):
    """Run pending DB migrations.

    Protected by X-Autopilot-Tick-Token header. Idempotent — safe to call
    multiple times.
    """
    expected = (os.environ.get("AUTOPILOT_TICK_TOKEN") or "").strip()
    if not expected:
        return JSONResponse({"error": "AUTOPILOT_TICK_TOKEN not configured"}, status_code=503)
    got = (request.headers.get("X-Autopilot-Tick-Token") or "").strip()
    if got != expected:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    sb = get_supabase()
    if not sb:
        return JSONResponse({"error": "Supabase not configured"}, status_code=503)

    results = []

    # Migration: api_keys table
    # We detect existence by attempting a select; if it raises PGRST205 the
    # table doesn't exist yet and we need to create it via raw SQL.
    # supabase-py doesn't expose DDL, so we use the Supabase REST /rpc path
    # with a helper function we create on first run.

    import hashlib, httpx

    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

    CREATE_HELPER_SQL = """
CREATE OR REPLACE FUNCTION _analook_exec(sql text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN EXECUTE sql; END;
$$;
"""

    CREATE_API_KEYS_SQL = """
CREATE TABLE IF NOT EXISTS api_keys (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    key_hash     text NOT NULL UNIQUE,
    key_prefix   text NOT NULL,
    name         text NOT NULL DEFAULT 'Default key',
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    revoked_at   timestamptz
);
CREATE INDEX IF NOT EXISTS api_keys_key_hash_idx ON api_keys (key_hash);
CREATE INDEX IF NOT EXISTS api_keys_user_id_idx  ON api_keys (user_id);
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename='api_keys' AND policyname='Users manage own api_keys'
  ) THEN
    CREATE POLICY "Users manage own api_keys"
      ON api_keys FOR ALL
      USING (auth.uid() = user_id)
      WITH CHECK (auth.uid() = user_id);
  END IF;
END $$;
"""

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: create the helper function via PostgREST /rpc/... wait,
        # we can't do DDL via REST directly. Instead, we embed the migration
        # in the app startup and use supabase-py's raw SQL capability
        # through the admin endpoint at /rest/v1/rpc
        # Actually: we create a PL/pgSQL function that wraps EXECUTE,
        # then call it.  But we need to create it first — chicken-and-egg.
        #
        # Real solution: Supabase Management API (api.supabase.com/v1)
        # which accepts a service_role JWT for the project.
        mgmt_resp = await client.post(
            f"https://api.supabase.com/v1/projects/nkunysycqapregxubcil/database/query",
            headers={
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            json={"query": CREATE_API_KEYS_SQL},
        )
        results.append({
            "migration": "api_keys",
            "status": mgmt_resp.status_code,
            "body": mgmt_resp.text[:200],
        })

    return JSONResponse({"results": results})


app.mount("/", StaticFiles(directory="static", html=True), name="static")
