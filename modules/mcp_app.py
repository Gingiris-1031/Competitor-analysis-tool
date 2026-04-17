"""
Analook Remote MCP (Model Context Protocol) server.

Exposes Analook's competitor-analysis features as MCP tools for AI agents
(Claude Desktop, Cursor, etc.) via Streamable HTTP transport at `/mcp`.

User configures their MCP client with:
    {
      "analook": {
        "url": "https://analook.com/mcp",
        "headers": { "Authorization": "Bearer <supabase_access_token>" }
      }
    }

Tools:
  - analyze_competitor(url, product_name?)    auth-required → starts job
  - get_report_status(job_id)                 public → poll status
  - get_report(job_id)                        public → full JSON
  - get_report_markdown(job_id)               public → markdown text
  - list_my_reports()                         auth-required → user's history
"""
# NOTE: do NOT add `from __future__ import annotations` here.
# FastMCP's Tool.from_function introspects param annotations at registration
# time via `issubclass(param.annotation, Context)`. With the future import,
# annotations become strings and issubclass raises TypeError — on some mcp
# versions (e.g. 1.12.x) this aborts server mount with no useful error,
# which is exactly what happened to us in prod on Railway.

import contextvars
import logging
import os
import uuid
from typing import Optional

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bearer token plumbing
# ---------------------------------------------------------------------------
# Each incoming MCP HTTP request runs in its own asyncio task; ContextVar gives
# us request-scoped storage without threading state through every tool.
_current_token: contextvars.ContextVar[str] = contextvars.ContextVar(
    "analook_mcp_bearer", default=""
)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Stash the incoming Authorization: Bearer <token> into a ContextVar
    so MCP tools can read it without the caller threading it explicitly.

    Unauthenticated requests are allowed through — public tools work without
    a token; auth-required tools raise a clear error.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
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
mcp = FastMCP("Analook", streamable_http_path="/")


async def _resolve_user() -> Optional[dict]:
    """Verify current request's Bearer token via Supabase. Returns user dict or None."""
    token = _current_token.get()
    if not token:
        return None
    try:
        from modules.supabase_client import verify_token_and_get_user
    except Exception:
        return None
    return await verify_token_and_get_user(token)


def _auth_required_error() -> dict:
    return {
        "error": "AUTH_REQUIRED",
        "hint": (
            "This tool requires authentication. Add your Analook access token "
            "to the MCP client config: "
            "headers: { Authorization: 'Bearer <your_token>' }. "
            "Get your token from analook.com account settings."
        ),
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool()
async def analyze_competitor(url: str, product_name: Optional[str] = None) -> dict:
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
    jobs[job_id] = {
        "status": "running",
        "product_name": product_name or domain,
        "url": normalized_url,
        "user_id": user["id"],
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
    try:
        from app import jobs, _load_persisted_report
    except ImportError:
        return {"error": "SERVER_ERROR", "hint": "analook app not initialized"}

    job = jobs.get(job_id)
    if job:
        out: dict = {"status": job.get("status", "unknown")}
        if job.get("progress"):
            out["progress"] = job["progress"]
        if job.get("status") == "completed":
            out["report_url"] = f"/api/v1/report/{job_id}"
        if job.get("status") == "failed" and job.get("error"):
            out["error"] = job["error"]
        return out

    # Check persisted storage
    report = _load_persisted_report(job_id)
    if report:
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
    try:
        from app import jobs, _load_persisted_report
    except ImportError:
        return {"error": "SERVER_ERROR"}

    job = jobs.get(job_id)
    if job and job.get("report"):
        return job["report"]
    report = _load_persisted_report(job_id)
    if report:
        return report
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
    try:
        from app import jobs
    except ImportError:
        return {"error": "SERVER_ERROR"}

    job = jobs.get(job_id)
    if job and job.get("markdown"):
        return {"markdown": job["markdown"]}
    # Fallback: load from disk and regenerate markdown
    try:
        import json as _json
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
        path = os.path.join(reports_dir, f"{job_id}.json")
        if os.path.exists(path):
            with open(path) as f:
                data = _json.load(f)
            md = data.get("markdown")
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
    return wrapped
