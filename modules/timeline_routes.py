"""竞品官网考古时间轴 —— 独立路由模块（从 app.py 抽出，减少并行改动的冲突面）。

app.py 里只需：
    from modules.timeline_routes import register as register_timeline_routes
    register_timeline_routes(app)

把竞品官网从 Wayback 逐版本挖出来做成可视化时间轴。每个 /timeline/<domain> =
一个可分享单页 + SEO 落地页（增长飞轮）。timelines 表落 InsForge（迁移第二块）。
双语：EN 默认 /timeline，中文 /zh/timeline，SSR 按路由注入 window.__LANG__。
"""
from __future__ import annotations

import html as _tl_html
import json as _json
import logging
import re as _tl_re

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.responses import HTMLResponse

log = logging.getLogger("timeline_routes")


def _timeline_span(nodes: list) -> str:
    if not nodes:
        return ""
    years = [n.get("date", "")[:4] for n in nodes if n.get("date")]
    years = [y for y in years if y]
    if not years:
        return ""
    return years[0] if years[0] == years[-1] else f"{years[0]}-{years[-1]}"


async def _render_timeline_share(domain: str, zh: bool):
    """时间轴分享页 SSR：按语言注入 <html lang> / window.__LANG__ / title / og / canonical。"""
    from modules import timeline as _tl
    dom = _tl.normalize_domain(domain)
    try:
        with open("static/timeline.html", "r", encoding="utf-8") as f:
            doc = f.read()
        span = ""
        try:
            from modules.insforge_client import get_timeline, enabled as _ins_enabled
            if _ins_enabled():
                row = await get_timeline(dom)
                if row:
                    data = row.get("data") or {}
                    if isinstance(data, str):
                        data = _json.loads(data)
                    span = _timeline_span(data.get("nodes") or [])
        except Exception:
            pass
        e = _tl_html.escape
        span_txt = f" {span}" if span else ""
        if zh:
            title = f"{dom} 官网演进时间轴{span_txt} | Analook 竞品考古"
            desc = (f"{dom} 官网从 Wayback 存档逐版本还原：slogan、定价、首屏、页面结构怎么演进。"
                    f"看它什么时候上定价页、怎么改定位——竞品增长路径的化石。")
            canonical = f"https://www.analook.com/zh/timeline/{dom}"
        else:
            title = f"{dom} Website Evolution Timeline{span_txt} | Analook"
            desc = (f"How {dom}'s website evolved version by version from the Wayback archive — "
                    f"slogan, pricing, hero and page structure. See when they shipped a pricing "
                    f"page and how they repositioned.")
            canonical = f"https://www.analook.com/timeline/{dom}"
        og_img = f"https://www.analook.com/api/og/timeline/{dom}.png"
        if zh:
            doc = doc.replace('<html lang="en">', '<html lang="zh-CN">', 1)
            doc = doc.replace('window.__LANG__ = "en";', 'window.__LANG__ = "zh";', 1)
        doc = _tl_re.sub(r"<title>.*?</title>", f"<title>{e(title)}</title>", doc, count=1, flags=_tl_re.S)
        for attr, val in (
            (r'name="description"', desc), (r'property="og:title"', title),
            (r'property="og:description"', desc), (r'property="og:url"', canonical),
            (r'property="og:image"', og_img), (r'name="twitter:title"', title),
            (r'name="twitter:description"', desc), (r'name="twitter:image"', og_img),
        ):
            doc = _tl_re.sub(r'(<meta\s+' + attr + r'\s+content=")[^"]*(")',
                             lambda m, v=val: m.group(1) + e(v) + m.group(2), doc, count=1)
        doc = _tl_re.sub(r'(<link\s+rel="canonical"\s+href=")[^"]*(")',
                         lambda m: m.group(1) + canonical + m.group(2), doc, count=1)
        alt_en = f"https://www.analook.com/timeline/{dom}"
        alt_zh = f"https://www.analook.com/zh/timeline/{dom}"
        doc = _tl_re.sub(r'(<link\s+rel="alternate"\s+hreflang="en"\s+href=")[^"]*(")',
                         lambda m: m.group(1) + alt_en + m.group(2), doc, count=1)
        doc = _tl_re.sub(r'(<link\s+rel="alternate"\s+hreflang="zh-CN"\s+href=")[^"]*(")',
                         lambda m: m.group(1) + alt_zh + m.group(2), doc, count=1)
        return HTMLResponse(content=doc)
    except Exception as ex:
        log.warning("timeline share inject failed domain=%s zh=%s: %s", dom, zh, ex)
        return FileResponse("static/timeline.html")


def _timeline_form(zh: bool):
    try:
        with open("static/timeline.html", "r", encoding="utf-8") as f:
            doc = f.read()
        if zh:
            doc = doc.replace('<html lang="en">', '<html lang="zh-CN">', 1)
            doc = doc.replace('window.__LANG__ = "en";', 'window.__LANG__ = "zh";', 1)
            zt = "竞品官网考古时间轴 | Analook"
            zd = ("把竞品官网从 Wayback 存档逐版本挖出来，做成可视化时间轴：slogan、定价、首屏、"
                  "页面结构怎么演进。看它什么时候上定价页、怎么改定位。竞品增长路径的化石。")
            doc = _tl_re.sub(r"<title>.*?</title>", f"<title>{zt}</title>", doc, count=1, flags=_tl_re.S)
            for attr, val in ((r'name="description"', zd), (r'property="og:title"', zt),
                              (r'property="og:description"', zd), (r'name="twitter:title"', zt),
                              (r'name="twitter:description"', zd)):
                doc = _tl_re.sub(r'(<meta\s+' + attr + r'\s+content=")[^"]*(")',
                                 lambda m, v=val: m.group(1) + v + m.group(2), doc, count=1)
            doc = _tl_re.sub(r'(<link\s+rel="canonical"\s+href=")[^"]*(")',
                             lambda m: m.group(1) + "https://www.analook.com/zh/timeline" + m.group(2), doc, count=1)
        return HTMLResponse(content=doc)
    except Exception:
        return FileResponse("static/timeline.html")


def register(app):
    """把时间轴路由挂到 app 上。"""

    @app.get("/api/timeline/{domain}")
    async def get_timeline_api(domain: str, request: Request):
        """公开读：缓存优先。InsForge 有则返回；没有则现抓 Wayback 构建、落库、返回。
        refresh=1 强制重建。"""
        from modules import timeline as _tl
        from modules.insforge_client import get_timeline, save_timeline, enabled as _ins_enabled
        dom = _tl.normalize_domain(domain)
        if not dom:
            return JSONResponse({"error": "invalid domain"}, status_code=400)
        force = request.query_params.get("refresh") == "1"
        if not force and _ins_enabled():
            row = await get_timeline(dom)
            if row:
                data = row.get("data") or {}
                if isinstance(data, str):
                    try:
                        data = _json.loads(data)
                    except Exception:
                        data = {}
                if data.get("nodes"):
                    data["cached"] = True
                    data["created_at"] = row.get("created_at")
                    return data
        built = await _tl.build_timeline(dom)
        if not built.get("nodes"):
            return JSONResponse({"domain": dom, "nodes": [],
                                 "error": built.get("error") or "无可用快照"}, status_code=404)
        try:
            await save_timeline(dom, built, is_public=True)
        except Exception as e:
            log.warning("timeline persist failed domain=%s: %s", dom, e)
        built["cached"] = False
        return built

    @app.get("/timeline/{domain}")
    async def timeline_share_page(domain: str):
        return await _render_timeline_share(domain, zh=False)

    @app.get("/zh/timeline/{domain}")
    async def timeline_share_page_zh(domain: str):
        return await _render_timeline_share(domain, zh=True)

    @app.get("/api/og/timeline/{domain}.png")
    async def og_card_timeline(domain: str):
        """动态 OG 卡：<域名> 官网演进 + 年份跨度 + 节点数。"""
        from modules import timeline as _tl
        dom = _tl.normalize_domain(domain)
        span, node_count = "", 0
        try:
            from modules.insforge_client import get_timeline, enabled as _ins_enabled
            if _ins_enabled():
                row = await get_timeline(dom)
                if row:
                    data = row.get("data") or {}
                    if isinstance(data, str):
                        data = _json.loads(data)
                    nodes = data.get("nodes") or []
                    node_count = len(nodes)
                    span = _timeline_span(nodes)
        except Exception as e:
            log.warning("og_card_timeline fetch failed domain=%s: %s", dom, e)
        try:
            from modules.og_card import render_timeline_card
            png = render_timeline_card(dom, span, node_count, f"analook.com/timeline/{dom}")
        except Exception as e:
            log.error("og_card_timeline render failed domain=%s: %s", dom, e)
            return FileResponse("static/assets/og/growth-audit.png")
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/timeline")
    async def timeline_form_page():
        return _timeline_form(zh=False)

    @app.get("/zh/timeline")
    async def timeline_form_page_zh():
        return _timeline_form(zh=True)
