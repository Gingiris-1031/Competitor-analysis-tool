"""增长诊断评分卡 —— 独立路由模块（从 app.py 抽出，减少并行改动的冲突面）。

app.py 里只需：
    from modules.scorecard_routes import register as register_scorecard_routes
    register_scorecard_routes(app, _require_credits, _extract_user)

免费预览层 = 总分 + 红黄绿灯（无需登录，驱动分享卡片 + 119 人召回半开放报告）；
付费解锁层 = 逐项修复方案（走 require_credits 扣积分）。分享页 /scorecard/<id> 匿名只读。
双语：EN 默认 /scorecard，中文 /zh/scorecard，SSR 按路由注入 window.__LANG__。
持久化走 supabase_client（内部按 INSFORGE_URL 开关委派 InsForge）。
"""
from __future__ import annotations

import html as _sc_html
import json as _json
import logging
import re as _sc_re
import uuid

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.responses import HTMLResponse

log = logging.getLogger("scorecard")

# 每个失分项 → 对应 skill 段落 + 服务 CTA（付费层映射）。
_SCORECARD_SKILL_CTA = {
    "paid_conversion":   {"skill": "gingiris-b2b-growth",
                          "cta": "https://gingiris.tools/services/",
                          "hint": "付费转化是最离钱的漏水点：先修定价/付费墙/激活到 aha 的路径，再谈引流。"},
    "signup_conversion": {"skill": "gingiris-go-global",
                          "cta": "https://gingiris.tools/services/",
                          "hint": "UV→注册偏低通常是落地页价值主张 + 首屏 CTA 问题，不是流量问题。"},
    "cac":               {"skill": "gingiris-launch",
                          "cta": "https://gingiris.tools/services/",
                          "hint": "获客成本超红线时先砍渠道、修转化，别加预算。"},
    "seo_onsite":        {"skill": "gingiris-seo-geo",
                          "cta": "https://gingiris.tools/services/",
                          "hint": "站内分未过 85 门槛前铺内容是浪费——先补基建再产内容。"},
}


def _scorecard_free_layer(result: dict) -> dict:
    """免费预览层：总分 + 每项红黄绿灯 + 基准，隐藏逐项修复文案（只给锁定的条数）。"""
    metrics = [
        {
            "key": m["key"], "label": m["label"], "value": m["value"],
            "grade": m["grade"],
            "benchmark_pass": m["benchmark_pass"], "benchmark_good": m["benchmark_good"],
            "lower_is_better": m.get("lower_is_better", False),
        }
        for m in result.get("metrics", [])
    ]
    return {
        "overall_score": result.get("overall_score", 0),
        "category": result.get("category", "default"),
        "metrics": metrics,
        "fix_count": len(result.get("fixes", [])),
        "fixes_locked": True,
    }


def _scorecard_paid_layer(result: dict) -> dict:
    """付费解锁层：在免费层基础上放出逐项修复方案 + skill/服务 CTA。"""
    layer = _scorecard_free_layer(result)
    layer["fixes_locked"] = False
    fixes = []
    for f in result.get("fixes", []):
        cta = _SCORECARD_SKILL_CTA.get(f["key"], {})
        fixes.append({
            "key": f["key"], "priority": f["priority"], "grade": f["grade"],
            "message": f["message"],
            "skill": cta.get("skill"), "cta": cta.get("cta"), "hint": cta.get("hint"),
        })
    layer["fixes"] = fixes
    return layer


def _score_one(payload: dict) -> dict:
    """对单个主体（自己或竞品）跑 score_growth。payload 里有什么字段就用什么。"""
    from modules import benchmarks
    cac = {}
    if payload.get("cac_signup") is not None:
        cac["signup"] = payload["cac_signup"]
    if payload.get("cac_paid") is not None:
        cac["paid"] = payload["cac_paid"]
    return benchmarks.score_growth(
        inputs={
            "uv": payload.get("uv"),
            "signups": payload.get("signups"),
            "paid": payload.get("paid"),
        },
        category=payload.get("category"),
        seo_score=payload.get("seo_score"),
        cac=cac or None,
    )


def _scorecard_domain(raw: str) -> str:
    d = (raw or "").strip().lower()
    for pfx in ("https://", "http://"):
        if d.startswith(pfx):
            d = d[len(pfx):]
    return d.split("/")[0].replace("www.", "") or "your product"


async def _render_scorecard_share(card_hash: str, zh: bool):
    """分享页 SSR：按语言注入 <html lang> / window.__LANG__ / 域名+健康分 title/og/canonical。"""
    try:
        from modules.supabase_client import get_scorecard
        row = await get_scorecard(card_hash)
        with open("static/scorecard.html", "r", encoding="utf-8") as f:
            doc = f.read()
        if zh:
            doc = doc.replace('<html lang="en">', '<html lang="zh-CN">', 1)
            doc = doc.replace('window.__LANG__ = "en";', 'window.__LANG__ = "zh";', 1)
        if not row:
            return HTMLResponse(content=doc)  # 前端自行显示表单/404

        result = row.get("result") or {}
        if isinstance(result, str):
            try:
                result = _json.loads(result)
            except Exception:
                result = {}
        score = result.get("overall_score", 0)
        domain = _scorecard_domain(row.get("domain") or "")
        e = _sc_html.escape
        if zh:
            title = f"{domain} 增长健康分 {score}/100 | Analook 增长诊断"
            desc = (f"{domain} 的增长诊断：注册→付费、UV→注册、获客成本、SEO 基建对着行业基准打分，"
                    f"综合增长健康分 {score}/100。免费看分数，付费看逐项修复方案。")
            canonical = f"https://www.analook.com/zh/scorecard/{card_hash}"
        else:
            title = f"{domain} Growth Health Score {score}/100 | Analook"
            desc = (f"{domain}'s growth diagnostic: signup→paid, visitor→signup, CAC and on-site SEO "
                    f"scored against industry benchmarks — overall {score}/100. Free score, paid fix plan.")
            canonical = f"https://www.analook.com/scorecard/{card_hash}"
        og_img = f"https://www.analook.com/api/og/scorecard/{card_hash}.png"

        doc = _sc_re.sub(r"<title>.*?</title>", f"<title>{e(title)}</title>", doc, count=1, flags=_sc_re.S)
        for attr, val in (
            (r'name="description"', desc), (r'property="og:title"', title),
            (r'property="og:description"', desc), (r'property="og:url"', canonical),
            (r'property="og:image"', og_img), (r'name="twitter:title"', title),
            (r'name="twitter:description"', desc), (r'name="twitter:image"', og_img),
        ):
            doc = _sc_re.sub(r'(<meta\s+' + attr + r'\s+content=")[^"]*(")',
                             lambda m, v=val: m.group(1) + e(v) + m.group(2), doc, count=1)
        doc = _sc_re.sub(r'(<link\s+rel="canonical"\s+href=")[^"]*(")',
                         lambda m: m.group(1) + canonical + m.group(2), doc, count=1)
        alt_en = f"https://www.analook.com/scorecard/{card_hash}"
        alt_zh = f"https://www.analook.com/zh/scorecard/{card_hash}"
        doc = _sc_re.sub(r'(<link\s+rel="alternate"\s+hreflang="en"\s+href=")[^"]*(")',
                         lambda m: m.group(1) + alt_en + m.group(2), doc, count=1)
        doc = _sc_re.sub(r'(<link\s+rel="alternate"\s+hreflang="zh-CN"\s+href=")[^"]*(")',
                         lambda m: m.group(1) + alt_zh + m.group(2), doc, count=1)
        return HTMLResponse(content=doc)
    except Exception as ex:
        log.warning("scorecard share inject failed hash=%s zh=%s: %s", card_hash, zh, ex)
        return FileResponse("static/scorecard.html")


def _scorecard_form(zh: bool):
    try:
        with open("static/scorecard.html", "r", encoding="utf-8") as f:
            doc = f.read()
        if zh:
            doc = doc.replace('<html lang="en">', '<html lang="zh-CN">', 1)
            doc = doc.replace('window.__LANG__ = "en";', 'window.__LANG__ = "zh";', 1)
            zt = "增长诊断评分卡 | Analook"
            zd = ("输入自己的官网 + 竞品，对着行业基准线自动诊断增长健康分：UV→注册、注册→付费、"
                  "获客成本、SEO 基建。免费看分数和红黄绿灯，付费解锁逐项修复方案。")
            doc = _sc_re.sub(r"<title>.*?</title>", f"<title>{zt}</title>", doc, count=1, flags=_sc_re.S)
            for attr, val in ((r'name="description"', zd), (r'property="og:title"', zt),
                              (r'property="og:description"', zd), (r'name="twitter:title"', zt),
                              (r'name="twitter:description"', zd)):
                doc = _sc_re.sub(r'(<meta\s+' + attr + r'\s+content=")[^"]*(")',
                                 lambda m, v=val: m.group(1) + v + m.group(2), doc, count=1)
            doc = _sc_re.sub(r'(<link\s+rel="canonical"\s+href=")[^"]*(")',
                             lambda m: m.group(1) + "https://www.analook.com/zh/scorecard" + m.group(2), doc, count=1)
        return HTMLResponse(content=doc)
    except Exception:
        return FileResponse("static/scorecard.html")


def register(app, require_credits, extract_user):
    """把评分卡路由挂到 app 上。require_credits/extract_user = app.py 的鉴权助手。"""

    @app.post("/api/scorecard")
    async def create_scorecard(request: Request):
        """免费预览层：跑增长诊断，返回总分 + 灯 + 分享 hash。无需登录（喂注册 + 可分享）。"""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)

        domain = (body.get("domain") or "").strip()
        if not domain:
            return JSONResponse({"error": "domain 必填", "code": "DOMAIN_REQUIRED"}, status_code=400)
        if not any(body.get(k) is not None for k in ("uv", "signups", "paid", "seo_score")):
            return JSONResponse(
                {"error": "至少填一个漏斗数字（UV / 注册 / 付费）或 SEO 分", "code": "INPUTS_REQUIRED"},
                status_code=400)

        result = _score_one(body)
        category = result.get("category", "default")
        competitors = []
        for comp in (body.get("competitors") or [])[:3]:
            cdomain = (comp.get("domain") or "").strip()
            if not cdomain:
                continue
            cres = _score_one(comp)
            competitors.append({
                "domain": cdomain,
                "overall_score": cres.get("overall_score", 0),
                "metrics": [
                    {"key": m["key"], "label": m["label"], "value": m["value"], "grade": m["grade"]}
                    for m in cres.get("metrics", [])
                ],
            })

        card_hash = "sc-" + uuid.uuid4().hex[:10]
        user = await extract_user(request)
        try:
            from modules.supabase_client import save_scorecard
            await save_scorecard(
                card_hash=card_hash,
                user_id=user["id"] if user else None,
                domain=domain, category=category,
                inputs={k: body.get(k) for k in
                        ("uv", "signups", "paid", "cac_signup", "cac_paid", "seo_score", "category")},
                result=result, competitors=competitors,
                is_public=bool(body.get("is_public", True)), unlocked=False,
            )
        except Exception as e:
            log.error("scorecard persist failed hash=%s: %s", card_hash, e)

        free = _scorecard_free_layer(result)
        free["hash"] = card_hash
        free["domain"] = domain
        free["competitors"] = competitors
        free["share_url"] = f"/scorecard/{card_hash}"
        return free

    @app.get("/api/scorecard/{card_hash}")
    async def get_scorecard_api(card_hash: str):
        """匿名只读：返回评分卡。已解锁则给付费层，否则给免费层。"""
        from modules.supabase_client import get_scorecard
        row = await get_scorecard(card_hash)
        if not row:
            return JSONResponse({"error": "评分卡不存在"}, status_code=404)
        if row.get("is_public") is False:
            return JSONResponse({"error": "该评分卡为私有"}, status_code=403)
        result = row.get("result") or {}
        if isinstance(result, str):
            try:
                result = _json.loads(result)
            except Exception:
                result = {}
        layer = _scorecard_paid_layer(result) if row.get("unlocked") else _scorecard_free_layer(result)
        layer["hash"] = card_hash
        layer["domain"] = row.get("domain")
        layer["competitors"] = row.get("competitors") or []
        layer["created_at"] = row.get("created_at")
        return layer

    @app.post("/api/scorecard/{card_hash}/unlock")
    async def unlock_scorecard(card_hash: str, request: Request):
        """付费解锁层：走 require_credits 扣积分，放出逐项修复方案。"""
        from modules.supabase_client import get_scorecard, mark_scorecard_unlocked
        row = await get_scorecard(card_hash)
        if not row:
            return JSONResponse({"error": "评分卡不存在"}, status_code=404)
        if not row.get("unlocked"):
            user, err = await require_credits(request)
            if err:
                return err
            await mark_scorecard_unlocked(card_hash)
        result = row.get("result") or {}
        if isinstance(result, str):
            try:
                result = _json.loads(result)
            except Exception:
                result = {}
        layer = _scorecard_paid_layer(result)
        layer["hash"] = card_hash
        layer["domain"] = row.get("domain")
        layer["competitors"] = row.get("competitors") or []
        return layer

    @app.get("/scorecard/{card_hash}")
    async def scorecard_share_page(card_hash: str):
        return await _render_scorecard_share(card_hash, zh=False)

    @app.get("/zh/scorecard/{card_hash}")
    async def scorecard_share_page_zh(card_hash: str):
        return await _render_scorecard_share(card_hash, zh=True)

    @app.get("/api/og/scorecard/{card_hash}.png")
    async def og_card_scorecard(card_hash: str):
        """动态 OG 卡：<域名> + 巨大健康分 <score>/100。社交分享的视觉钩子。"""
        from modules.supabase_client import get_scorecard
        domain, score = "your product", 0
        try:
            row = await get_scorecard(card_hash)
            if row:
                domain = _scorecard_domain(row.get("domain") or "")
                result = row.get("result") or {}
                if isinstance(result, str):
                    result = _json.loads(result)
                score = result.get("overall_score", 0)
        except Exception as e:
            log.warning("og_card_scorecard fetch failed hash=%s: %s", card_hash, e)
        try:
            from modules.og_card import render_scorecard_card
            png = render_scorecard_card(domain, score, f"analook.com/scorecard/{card_hash}")
        except Exception as e:
            log.error("og_card_scorecard render failed hash=%s: %s", card_hash, e)
            return FileResponse("static/assets/og/growth-audit.png")
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/scorecard")
    async def scorecard_form_page():
        return _scorecard_form(zh=False)

    @app.get("/zh/scorecard")
    async def scorecard_form_page_zh():
        return _scorecard_form(zh=True)
