"""竞品调研 MVP 工具 — FastAPI 后端"""
import asyncio
import json as _json
import os
import time
import uuid
from fastapi import FastAPI, BackgroundTasks
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
from modules.ai_summary import generate_ai_summary
from modules.report import generate_report, report_to_markdown
from modules.traffic_peaks import analyze_traffic_peaks
from modules.growth_strategy import recommend_playbooks, build_qa_playbook_context

app = FastAPI(title="竞品调研工具 MVP")

# In-memory store for analysis jobs
jobs: dict = {}

# ---------------------------------------------------------------------------
# Domain-level result cache (in-memory, single-instance)
# key = domain string, value = {"timestamp": float, "job": dict}
# ---------------------------------------------------------------------------
DOMAIN_CACHE_TTL = 30 * 60  # 30 minutes
_domain_cache: dict = {}


class AnalyzeRequest(BaseModel):
    url: str
    product_name: Optional[str] = None


@app.post("/api/analyze")
async def start_analysis(req: AnalyzeRequest, bg: BackgroundTasks):
    job_id = str(uuid.uuid4())[:8]
    
    # Auto-detect product name from domain if not provided
    domain = urlparse(req.url if req.url.startswith("http") else f"https://{req.url}").netloc
    if not domain:
        domain = req.url.replace("https://", "").replace("http://", "").split("/")[0]
    product_name = req.product_name or domain.replace(".com", "").replace(".io", "").replace(".dev", "").replace(".ai", "").capitalize()

    # --- Domain cache: return cached result if available and fresh ---
    cache_key = domain.lower().replace("www.", "")
    cached = _domain_cache.get(cache_key)
    if cached and (time.time() - cached["timestamp"]) < DOMAIN_CACHE_TTL:
        # Clone cached job under new job_id
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
        "progress": {
            "website": "pending",
            "social": "pending",
            "propagation": "pending",
            "traffic": "pending",
            "traffic_peaks": "pending",
            "growth_analysis": "pending",
            "report": "pending",
        },
        "results": {},
        "report": None,
        "markdown": None,
    }
    
    bg.add_task(_run_analysis, job_id)
    return {"job_id": job_id, "status": "started"}


async def _run_analysis(job_id: str):
    job = jobs[job_id]
    url = job["url"]
    domain = urlparse(url).netloc
    product_name = job["product_name"]

    # ================================================================
    # Phase 1: Website + Traffic/SEO + ProductHunt + Social (all parallel)
    # Social runs without website hints first; handles are accurate enough
    # via Apify/Caravo bio-matching. Website hints improve precision but
    # the speed gain from full parallelism (~30-60s saved) outweighs the
    # occasional miss.
    # ================================================================
    import asyncio as _aio
    job["progress"]["website"] = "running"
    job["progress"]["social"] = "running"
    job["progress"]["traffic"] = "running"

    website_task = analyze_website(url)
    traffic_task = analyze_domain(domain)
    ph_task = analyze_producthunt(domain, product_name)
    social_task = analyze_social(domain, product_name, website_social_links={})

    results_phase1 = await _aio.gather(
        website_task, traffic_task, ph_task, social_task,
        return_exceptions=True,
    )

    job["results"]["website"] = results_phase1[0] if not isinstance(results_phase1[0], Exception) else {"error": str(results_phase1[0])}
    job["progress"]["website"] = "error" if isinstance(results_phase1[0], Exception) else "done"

    job["results"]["traffic"] = results_phase1[1] if not isinstance(results_phase1[1], Exception) else {"error": str(results_phase1[1])}
    job["progress"]["traffic"] = "error" if isinstance(results_phase1[1], Exception) else "done"

    job["results"]["producthunt"] = results_phase1[2] if not isinstance(results_phase1[2], Exception) else {"error": str(results_phase1[2])}

    job["results"]["social"] = results_phase1[3] if not isinstance(results_phase1[3], Exception) else {"error": str(results_phase1[3])}
    job["progress"]["social"] = "error" if isinstance(results_phase1[3], Exception) else "done"

    # ================================================================
    # Phase 2: Propagation + Traffic Peaks (parallel, both depend on Phase 1)
    # ================================================================
    async def _run_propagation():
        if job["results"].get("social", {}).get("_propagation_available"):
            job["progress"]["propagation"] = "running"
            propagation = await run_launch_propagation(job["results"]["social"])
            job["results"]["propagation"] = propagation
            job["progress"]["propagation"] = "done"
        else:
            job["results"]["propagation"] = {}
            job["progress"]["propagation"] = "done"

    async def _run_traffic_peaks():
        job["progress"]["traffic_peaks"] = "running"
        peaks = await analyze_traffic_peaks(
            product_name, domain,
            producthunt=job["results"].get("producthunt", {}),
            social=job["results"].get("social", {}),
        )
        job["results"]["traffic_peaks"] = peaks
        job["progress"]["traffic_peaks"] = "done"

    phase2_results = await _aio.gather(
        _run_propagation(), _run_traffic_peaks(),
        return_exceptions=True,
    )
    # Handle propagation errors
    if isinstance(phase2_results[0], Exception):
        job["results"]["propagation"] = {"error": str(phase2_results[0])}
        job["progress"]["propagation"] = "error"
    # Handle traffic_peaks errors
    if isinstance(phase2_results[1], Exception):
        job["results"]["traffic_peaks"] = {"error": str(phase2_results[1])}
        job["progress"]["traffic_peaks"] = "error"

    # ================================================================
    # Phase 3: Growth analysis + AI summary
    # Growth analysis runs first (sync, instant), then Playbook matching
    # (pure rules), then AI summary gets the full context including Playbook.
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
        )
        job["results"]["growth_analysis"] = growth_deep
        job["progress"]["growth_analysis"] = "done"
    except Exception as growth_err:
        job["results"]["growth_analysis"] = {"error": str(growth_err)}
        job["progress"]["growth_analysis"] = "error"

    # Early Playbook matching (pure rule engine, no LLM — instant)
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

    # AI summary now gets Playbook context for richer insights
    try:
        ai = await generate_ai_summary(
            product_name, url,
            job["results"].get("website", {}),
            job["results"].get("social", {}),
            job["results"].get("traffic", {}),
            job["results"].get("producthunt", {}),
            growth_strategy=early_strategy,
        )
        job["results"]["ai_summary"] = ai
    except Exception as ai_err:
        ai = {"success": False, "content": "", "note": f"AI 分析异常: {str(ai_err)[:100]}", "source": "error"}
        job["results"]["ai_summary"] = ai

    # ================================================================
    # Phase 4: Report generation (depends on everything above)
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

        # Reuse early Playbook matching from Phase 3 (already computed)
        growth_strategy = job["results"].get("growth_strategy", {})
        report["sections"]["growth_strategy"] = growth_strategy

        job["report"] = report
        try:
            job["markdown"] = report_to_markdown(report)
        except Exception:
            job["markdown"] = f"# {product_name} 竞品调研报告\n\n> Markdown 导出出错，请查看在线报告。\n"
        job["progress"]["report"] = "done"
    except Exception as e:
        job["progress"]["report"] = "error"

    job["status"] = "completed"

    # Persist report to disk so shared links survive server restarts
    _persist_report(job_id, job)

    # Cache completed results by domain (for repeat queries)
    cache_key = domain.lower().replace("www.", "")
    _domain_cache[cache_key] = {"timestamp": time.time(), "job": job}


REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


def _persist_report(job_id: str, job: dict):
    """Save completed report to disk as JSON."""
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
        pass  # Non-critical


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return {"error": "Job not found"}
    return {
        "status": job["status"],
        "progress": job["progress"],
        "product_name": job["product_name"],
    }


@app.get("/api/report/{job_id}")
async def get_report(job_id: str):
    # Try in-memory first, then disk
    job = jobs.get(job_id)
    if job and job.get("report"):
        return job["report"]
    # Fallback to persisted report
    path = os.path.join(REPORTS_DIR, f"{job_id}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if data.get("report"):
            return data["report"]
    if job and not job.get("report"):
        return {"error": "Report not ready", "status": job["status"]}
    return {"error": "Job not found"}


@app.get("/api/export/{job_id}")
async def export_markdown(job_id: str):
    job = jobs.get(job_id)
    markdown = None
    product_name = "report"
    if job and job.get("markdown"):
        markdown = job["markdown"]
        product_name = job.get("product_name", "report")
    else:
        # Fallback to disk
        path = os.path.join(REPORTS_DIR, f"{job_id}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            markdown = data.get("markdown")
            product_name = data.get("product_name", "report")
    if not markdown:
        return {"error": "Report not ready"}
    from urllib.parse import quote
    safe_name = quote(f"{product_name}_竞品调研.md")
    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )


@app.get("/api/share/{job_id}")
async def get_share_info(job_id: str):
    """Generate share URL with UTM parameters."""
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
        return {"error": "Job not found"}

    from urllib.parse import quote_plus
    base_url = f"/report/{job_id}"
    utm = f"utm_source=gingiris_tool&utm_medium=share&utm_campaign=competitive_analysis&utm_content={quote_plus(product_name)}"
    share_url = f"{base_url}?{utm}"

    return {
        "job_id": job_id,
        "product_name": product_name,
        "share_url": share_url,
        "utm_params": utm,
        "share_text": f"🔍 {product_name} 竞品调研报告 — Powered by Gingiris",
    }


@app.get("/report/{job_id}")
async def shared_report_page(job_id: str):
    """Serve the shared report page (same UI, auto-loads the report)."""
    return FileResponse("static/index.html")


class QARequest(BaseModel):
    job_id: str
    question: str


@app.post("/api/qa")
async def ask_question(req: QARequest):
    job = jobs.get(req.job_id)
    if not job or not job["report"]:
        return {"error": "Report not ready"}

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

    # Auto-detect if web search needed
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

    # Build Playbook recommendation context for prompt injection
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


# Serve static files — js subfolder and root
app.mount("/js", StaticFiles(directory="static/js"), name="js")
app.mount("/", StaticFiles(directory="static", html=True), name="static")
