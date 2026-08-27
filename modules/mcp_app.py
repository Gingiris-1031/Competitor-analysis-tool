"""
Analook Remote MCP (Model Context Protocol) server.

Exposes Analook's competitor-analysis features as MCP tools for AI agents
(Claude Desktop, Cursor, etc.) via Streamable HTTP transport at `/mcp`.

User configures their MCP client with an Analook MCP API key:
    {
      "analook": {
        "url": "https://analook.com/mcp",
        "headers": { "Authorization": "Bearer anl_mcp_<key>" }
      }
    }

Tools:
  - analyze_competitor(url, product_name?, lang?)  auth-required → starts job
  - get_report_status(job_id)                      owner-only → poll status
  - get_report(job_id)                             owner-only → full JSON
  - get_report_markdown(job_id)                    owner-only → markdown text
  - list_my_reports()                              auth-required → user's history
  - run_growth_audit(url, product_name?, lang?)    auth-required → 3-report audit (10 credits)
  - get_growth_audit(job_id)                       owner-only → audit reports
  - browse_public_reports(category?)               public → gallery discovery
"""
# NOTE: do NOT add `from __future__ import annotations` here.
# FastMCP's Tool.from_function introspects param annotations at registration
# time via `issubclass(param.annotation, Context)`. With the future import,
# annotations become strings and issubclass raises TypeError — on some mcp
# versions (e.g. 1.12.x) this aborts server mount with no useful error,
# which is exactly what happened to us in prod on Railway.

import contextvars
import hashlib
import logging
import os
import uuid
from typing import Optional

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bearer token plumbing
# ---------------------------------------------------------------------------
# Each incoming MCP HTTP request runs in its own asyncio task; ContextVar gives
# us request-scoped storage without threading state through every tool.
_current_token: contextvars.ContextVar[str] = contextvars.ContextVar(
    "analook_mcp_bearer", default=""
)


def _posthog_distinct_id() -> str:
    """Return a stable, non-reversible analytics identifier for an MCP caller.

    Never send the bearer token itself to analytics: it is a credential. MCP
    keys are high-entropy, so a SHA-256 digest gives PostHog a stable actor
    without exposing the raw key outside Analook.
    """
    token = _current_token.get()
    if not token:
        return "anonymous"
    return "mcp:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Stash the incoming Authorization: Bearer <token> into a ContextVar
    so MCP tools can read it without the caller threading it explicitly.

    Unauthenticated requests are allowed through only for public discovery;
    account and report tools reject unauthenticated calls clearly.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Desktop clients generally omit Origin. When a browser supplies one,
        # reject foreign origins to prevent DNS-rebinding style cross-origin MCP
        # calls against a user's configured server.
        origin = (request.headers.get("origin") or "").rstrip("/")
        if origin and origin not in {"https://analook.com", "https://www.analook.com"}:
            return JSONResponse({"error": "INVALID_ORIGIN"}, status_code=403)
        raw = request.headers.get("authorization", "")
        token = raw[7:].strip() if raw[:7].lower() == "bearer " else ""
        tok = _current_token.set(token)
        try:
            return await call_next(request)
        finally:
            _current_token.reset(tok)


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------
# FastMCP serves at settings.streamable_http_path (default "/mcp") inside
# its own app. We mount that app at "/mcp" on FastAPI, so to avoid the
# full path becoming "/mcp/mcp" we flatten the inner path to "/".
# stateless_http=True: no server-side MCP session state. analook runs on 2 Fly
# machines behind a round-robin proxy; with the default (stateful) mode a
# client's initialize lands on machine A but its follow-up tools/call can be
# load-balanced to machine B, which has never seen that session → intermittent
# "Bad Request: No valid session ID provided". Stateless makes every request
# self-contained so either machine can serve it. (Same class of split-brain as
# the in-memory jobs dict we fixed with fly-replay.)
mcp = FastMCP("Analook", streamable_http_path="/", stateless_http=True)


async def _resolve_user() -> Optional[dict]:
    """Resolve an InsForge-backed MCP key, then accept a transition JWT."""
    token = _current_token.get()
    if not token:
        return None
    try:
        from modules.insforge_client import resolve_mcp_api_key
        key = await resolve_mcp_api_key(token)
        if key:
            return {
                "id": str(key["owner_id"]), "email": "",
                "auth_type": "mcp_api_key", "mcp_key_id": str(key["id"]),
            }
    except Exception:
        pass
    # Transitional browser-token compatibility: an InsForge identity must be
    # linked to the matching legacy account before it can access legacy credits
    # or reports. The public documentation never asks users to copy a session
    # token; MCP API keys remain the documented integration path.
    try:
        from modules.insforge_client import link_insforge_identity, verify_user_token
        user = await verify_user_token(token)
        if user:
            linked = await link_insforge_identity(user)
            if linked:
                linked["auth_type"] = "insforge_jwt"
                return linked
    except Exception:
        pass
    try:
        from modules.supabase_client import verify_token_and_get_user
    except Exception:
        return None
    user = await verify_token_and_get_user(token)
    if user:
        user["auth_type"] = "legacy_jwt"
    return user


def _auth_required_error() -> dict:
    return {
        "error": "AUTH_REQUIRED",
        "hint": (
            "This tool requires authentication. Add your Analook MCP API key "
            "to the MCP client config: "
            "headers: { Authorization: 'Bearer anl_mcp_<your_key>' }. "
            "Create or revoke a key in Analook account settings."
        ),
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool()
async def analyze_competitor(
    url: str, product_name: Optional[str] = None, lang: Optional[str] = None
) -> dict:
    """Submit a competitor analysis job.

    Analyzes a competitor's website across 15+ data sources (SEO, traffic,
    social, Product Hunt, GitHub, Wayback Machine history, AI-generated
    insights, etc.) and returns a job_id. Use get_report_status(job_id) to
    poll and get_report(job_id) to retrieve results when status='completed'.

    Typical analysis takes 2-5 minutes. Requires authentication (deducts 1
    credit from your Analook balance).

    Args:
        url: Competitor website URL (e.g. 'https://linear.app' or 'lovable.dev')
        product_name: Optional product name override (defaults to domain)
        lang: Report language, 'en' (default) or 'zh' for Chinese output

    Returns:
        {job_id: str, status: 'started', poll_url: str} on success
        {error: str, hint?: str} on auth/validation failure
    """
    user = await _resolve_user()
    if not user:
        return _auth_required_error()

    # Reuse the existing HTTP handler's logic by importing the needed helpers
    # and internal state directly (same-process access — no HTTP round-trip).
    try:
        from app import (
            jobs, _persist_report, _run_analysis_with_timeout,
            normalize_url_or_raise,  # may not exist; we guard below
        )
    except ImportError:
        from app import jobs, _persist_report, _run_analysis_with_timeout
        normalize_url_or_raise = None

    from modules.supabase_client import deduct_credit
    from urllib.parse import urlparse

    # Normalize URL
    raw = (url or "").strip()
    if not raw:
        return {"error": "INVALID_URL", "hint": "Provide a non-empty URL"}
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
        if not parsed.netloc:
            raise ValueError("no netloc")
    except Exception:
        return {"error": "INVALID_URL", "hint": f"Could not parse: {url!r}"}

    # Allowlist schemes: prevent file://, javascript:, data:, ssh:// etc.
    # _run_analysis fetches this URL, so an unvalidated scheme is an SSRF/local-file read risk.
    if parsed.scheme not in ("http", "https"):
        return {"error": "INVALID_URL", "hint": "Only http/https URLs are supported"}

    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain or "." not in domain:
        return {"error": "INVALID_URL", "hint": f"Invalid domain: {domain!r}"}

    # Deduct credit (fails if balance is 0).
    # NOTE: _run_analysis_with_timeout does NOT deduct — deduction happens here
    # once, matching the HTTP /api/analyze flow. Don't add deduction to
    # _run_analysis_with_timeout or we double-charge MCP users.
    if user.get("auth_type") == "mcp_api_key":
        from modules.insforge_client import consume_mcp_credit
        ok = await consume_mcp_credit(user.get("mcp_key_id", "")) is not None
    else:
        ok = await deduct_credit(user["id"])
    if not ok:
        return {
            "error": "INSUFFICIENT_CREDITS",
            "hint": "Top up at https://analook.com/pricing or upgrade plan",
        }

    # Start the job in the shared jobs dict. Full uuid hex to avoid
    # collisions with HTTP-originated job_ids (shared dict).
    import asyncio as _aio

    job_id = uuid.uuid4().hex
    while job_id in jobs:
        job_id = uuid.uuid4().hex

    # IMPORTANT: schema must match the HTTP /api/analyze job schema exactly,
    # since _run_analysis mutates job["progress"]["website"] (dict keys) and
    # reads job["results"]. A flat progress string breaks _run_analysis.
    normalized_url = f"https://{domain}" if parsed.scheme == "https" else raw
    _lang = (lang or "").strip().lower()
    if _lang not in ("en", "zh"):
        _lang = "en"  # MCP agents default to English output
    jobs[job_id] = {
        "status": "running",
        "product_name": product_name or domain,
        "url": normalized_url,
        "user_id": user["id"],
        "lang": _lang,
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
    # Fire-and-forget the analysis background task
    _aio.create_task(_run_analysis_with_timeout(job_id))

    return {
        "job_id": job_id,
        "status": "started",
        "poll_url": f"/api/v1/status/{job_id}",
        "hint": "Poll get_report_status(job_id) every 10-20s until status='completed'",
    }


@mcp.tool()
async def get_report_status(job_id: str) -> dict:
    """Poll an analysis job's status.

    Args:
        job_id: ID returned from analyze_competitor()

    Returns:
        {status: 'running'|'completed'|'failed', progress?: str, report_url?: str}
    """
    user = await _resolve_user()
    if not user:
        return _auth_required_error()
    try:
        from app import jobs, _load_persisted_report
    except ImportError:
        return {"error": "SERVER_ERROR", "hint": "analook app not initialized"}

    job = jobs.get(job_id)
    if job and str(job.get("user_id") or "") == str(user["id"]):
        out: dict = {"status": job.get("status", "unknown")}
        if job.get("progress"):
            out["progress"] = job["progress"]
        if job.get("status") == "completed":
            out["report_url"] = f"/api/v1/report/{job_id}"
        if job.get("status") == "failed" and job.get("error"):
            out["error"] = job["error"]
        return out

    # Check persisted storage
    try:
        from modules.insforge_client import get_report_record
        record = await get_report_record(job_id)
    except Exception:
        record = None
    if record and str(record.get("user_id") or "") == str(user["id"]):
        return {"status": "completed", "report_url": f"/api/v1/report/{job_id}"}

    return {"status": "not_found", "job_id": job_id}


@mcp.tool()
async def get_report(job_id: str) -> dict:
    """Fetch the full competitor analysis report as structured JSON.

    Reports contain: website snapshot, Wayback Machine history, SEO/traffic
    data (DataForSEO), social media presence, Product Hunt launches, GitHub
    stats, pricing, funding, AI-generated business insights, growth
    playbooks, and more.

    Args:
        job_id: ID from analyze_competitor(); status must be 'completed'

    Returns:
        The full report dict (nested structure), or {error} if not found / not ready.
    """
    user = await _resolve_user()
    if not user:
        return _auth_required_error()
    try:
        from app import jobs, _load_persisted_report
    except ImportError:
        return {"error": "SERVER_ERROR"}

    job = jobs.get(job_id)
    if job and str(job.get("user_id") or "") == str(user["id"]) and job.get("report"):
        return job["report"]
    try:
        from modules.insforge_client import get_report_record
        record = await get_report_record(job_id)
    except Exception:
        record = None
    if record and str(record.get("user_id") or "") == str(user["id"]):
        return record.get("report") or {"error": "REPORT_NOT_FOUND", "job_id": job_id}
    return {"error": "REPORT_NOT_FOUND", "job_id": job_id}


@mcp.tool()
async def get_report_markdown(job_id: str) -> dict:
    """Fetch the competitor analysis report as human-readable Markdown.

    Suitable for piping into agents that prefer text over structured JSON,
    or for direct display to end users.

    Args:
        job_id: ID from analyze_competitor(); status must be 'completed'

    Returns:
        {markdown: str} or {error: str}
    """
    user = await _resolve_user()
    if not user:
        return _auth_required_error()
    try:
        from app import jobs
    except ImportError:
        return {"error": "SERVER_ERROR"}

    job = jobs.get(job_id)
    if job and str(job.get("user_id") or "") == str(user["id"]) and job.get("markdown"):
        return {"markdown": job["markdown"]}
    try:
        from modules.insforge_client import get_report_record
        record = await get_report_record(job_id)
        if record and str(record.get("user_id") or "") == str(user["id"]):
            md = record.get("markdown")
            if md:
                return {"markdown": md}
    except Exception:
        pass
    return {"error": "MARKDOWN_NOT_FOUND", "job_id": job_id}


@mcp.tool()
async def list_my_reports() -> dict:
    """List your recent competitor analysis reports (up to 50).

    Requires authentication. Returns a lightweight list (id, url,
    product_name, created_at, status) — use get_report(job_id) to fetch
    the full report for any of them.

    Returns:
        {reports: [{id, url, product_name, created_at, status}, ...]}
    """
    user = await _resolve_user()
    if not user:
        return _auth_required_error()
    try:
        from modules.supabase_client import list_user_reports
    except Exception:
        return {"error": "SERVER_ERROR"}
    rows = await list_user_reports(user["id"], limit=50)
    return {"reports": rows}


@mcp.tool()
async def run_growth_audit(
    url: str, product_name: Optional[str] = None, lang: Optional[str] = None
) -> dict:
    """Run a full Growth Audit — three linked strategic reports for a product.

    Unlike analyze_competitor (a single 15-signal intelligence snapshot), a
    Growth Audit produces an Executive Summary + a Diagnosis Report + a 30-day
    Action Plan, grounded in real channel/tactic playbooks. Best for 'how do I
    grow THIS product' rather than 'what is this competitor doing'.

    Takes ~4-6 minutes. Requires authentication and deducts 10 credits. Poll
    with get_growth_audit(job_id) until status='completed'.

    Args:
        url: Product website URL to audit
        product_name: Optional product name override (defaults to domain)
        lang: Report language, 'en' (default) or 'zh'
    """
    user = await _resolve_user()
    if not user:
        return _auth_required_error()

    raw = (url or "").strip()
    if not raw:
        return {"error": "INVALID_URL", "hint": "Provide a non-empty URL"}
    if "://" not in raw:
        raw = "https://" + raw
    from urllib.parse import urlparse
    try:
        parsed = urlparse(raw)
        if not parsed.netloc:
            raise ValueError("no netloc")
    except Exception:
        return {"error": "INVALID_URL", "hint": f"Could not parse: {url!r}"}
    if parsed.scheme not in ("http", "https"):
        return {"error": "INVALID_URL", "hint": "Only http/https URLs are supported"}

    _lang = (lang or "").strip().lower()
    if _lang not in ("en", "zh"):
        _lang = "en"

    try:
        from app import (
            _growth_audit_jobs, _run_growth_audit, GROWTH_AUDIT_CREDITS,
        )
    except ImportError:
        return {"error": "SERVER_ERROR", "hint": "growth audit unavailable"}
    if user.get("auth_type") == "mcp_api_key":
        from modules.insforge_client import consume_mcp_credit
        remaining = await consume_mcp_credit(user.get("mcp_key_id", ""), GROWTH_AUDIT_CREDITS)
        if remaining is None:
            return {
                "error": "INSUFFICIENT_CREDITS",
                "hint": f"Growth Audit needs {GROWTH_AUDIT_CREDITS} MCP credits.",
            }
    else:
        from modules.supabase_client import get_user_profile, deduct_credit
        # Transitional JWT path: preserve the existing credit ledger until the
        # whole website account system has moved to InsForge.
        profile = await get_user_profile(user["id"])
        balance = (profile or {}).get("credits_balance") or 0
        if balance < GROWTH_AUDIT_CREDITS:
            return {
                "error": "INSUFFICIENT_CREDITS",
                "hint": f"Growth Audit needs {GROWTH_AUDIT_CREDITS} credits "
                        f"(you have {balance}). Top up at https://analook.com/pricing",
            }
        for _ in range(GROWTH_AUDIT_CREDITS):
            if not await deduct_credit(user["id"]):
                break

    import asyncio as _aio
    job_id = f"ga-{uuid.uuid4().hex[:8]}"
    while job_id in _growth_audit_jobs:
        job_id = f"ga-{uuid.uuid4().hex[:8]}"
    normalized_url = raw
    _growth_audit_jobs[job_id] = {
        "status": "running",
        "product_name": product_name or parsed.netloc,
        "url": normalized_url,
        "lang": _lang,
        "user_id": user["id"],
        "progress": {
            "fetch": "pending",
            "executive_summary": "pending",
            "diagnosis": "pending",
            "action_plan": "pending",
        },
        "reports": None,
    }
    _aio.create_task(_run_growth_audit(job_id, normalized_url, product_name, _lang))
    return {
        "job_id": job_id,
        "status": "started",
        "hint": "Poll get_growth_audit(job_id) every 20-30s until status='completed'",
    }


@mcp.tool()
async def get_growth_audit(job_id: str) -> dict:
    """Fetch a Growth Audit's three reports (Executive Summary, Diagnosis,
    Action Plan) as Markdown.

    Args:
        job_id: ID from run_growth_audit() (starts with 'ga-')

    Returns:
        {status, reports: {executive_summary, diagnosis_report, action_plan}}
        while running, only {status, progress} is returned.
    """
    user = await _resolve_user()
    if not user:
        return _auth_required_error()
    try:
        from app import _growth_audit_jobs
    except ImportError:
        return {"error": "SERVER_ERROR"}

    job = _growth_audit_jobs.get(job_id)
    if job and str(job.get("user_id") or "") == str(user["id"]):
        status = job.get("status", "running")
        if status == "completed" and job.get("reports"):
            return {"status": "completed", "reports": job["reports"]}
        if status == "failed":
            return {"status": "failed", "error": job.get("error", "unknown")}
        return {"status": status, "progress": job.get("progress", {})}

    # InsForge survives restarts and cross-machine requests.
    try:
        from modules.insforge_client import get_report_record
        record = await get_report_record(job_id)
        if record and str(record.get("user_id") or "") == str(user["id"]):
            rep = record.get("report") or {}
            reports = rep.get("reports")
            if reports and not rep.get("_partial"):
                return {"status": "completed", "reports": reports}
            if reports:
                return {"status": "running", "reports": reports}
    except Exception as e:
        log.warning("get_growth_audit supabase fallback failed: %s", e)
    return {"status": "not_found", "job_id": job_id}


@mcp.tool()
async def browse_public_reports(category: Optional[str] = None) -> dict:
    """Browse Analook's public competitor-intelligence report gallery.

    Returns recently published public reports (product name, domain, category,
    and a link). No authentication or credits required — a fast way to discover
    existing analyses before spending a credit on a fresh one.

    Args:
        category: Optional filter, e.g. 'AI / Agents', 'Dev Tools',
                  'Crypto / Web3', 'Marketing / SEO', 'SaaS / Other'
    """
    try:
        from app import _public_reports_data
    except ImportError:
        return {"error": "SERVER_ERROR"}
    reports = await _public_reports_data()
    if category:
        cl = category.strip().lower()
        reports = [r for r in reports if cl in (r.get("category") or "").lower()]
    out = []
    for r in reports[:60]:
        rid = r["id"]
        path = f"/share/audit/{rid}" if str(rid).startswith("ga-") else f"/report/{rid}"
        out.append({
            "id": rid,
            "product_name": r.get("product_name"),
            "domain": r.get("domain"),
            "category": r.get("category"),
            "url": f"https://www.analook.com{path}",
        })
    return {"count": len(out), "reports": out}


# ---------------------------------------------------------------------------
# ASGI app — mount this at /mcp in the main FastAPI app
# ---------------------------------------------------------------------------
def build_mcp_app():
    """Build the Streamable HTTP ASGI app, wrapped with Bearer middleware."""
    raw_app = mcp.streamable_http_app()
    # Starlette apps support add_middleware AFTER instantiation only if the
    # middleware stack hasn't been built yet; FastMCP's app is already built.
    # So we wrap it manually using a simple ASGI adapter.
    from starlette.applications import Starlette
    from starlette.routing import Mount

    wrapped = Starlette(
        routes=[Mount("/", app=raw_app)],
        middleware=[],
    )
    wrapped.add_middleware(BearerAuthMiddleware)

    # PostHog MCP analytics — auto-captures $mcp_tool_call / $mcp_initialize /
    # $exception / $mcp_tools_list. Best-effort: if the SDK is unavailable or
    # misconfigured, the MCP endpoint still mounts without analytics.
    try:
        from modules.posthog_track import get_client
        from posthog.mcp import instrument
        from posthog.mcp.types import MCPAnalyticsOptions, UserIdentity
        instrument(
            mcp,
            get_client(),
            MCPAnalyticsOptions(
                enable_conversation_id=True,
                enable_exception_autocapture=True,
                identify=lambda request, extra: UserIdentity(
                    distinct_id=_posthog_distinct_id(),
                    properties={
                        "auth_type": (
                            "authenticated" if _current_token.get() else "anonymous"
                        ),
                    },
                ),
            ),
        )
    except Exception as _ph_err:
        log.warning("PostHog MCP instrumentation skipped: %s", _ph_err, exc_info=True)

    return wrapped
