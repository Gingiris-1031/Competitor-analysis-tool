"""竞品官网考古时间轴 — 把 Wayback 逐版本演进做成一条可视化时间轴。

复用 website.py 已有的 Wayback 机制（_try_cdx 拿快照列表、_analyze_snapshot 抓单快照
并 _extract_page_structure 提取 slogan/title/h1/h2/section_count/features），本模块只做：
  1. 编排：CDX 快照列表 → 并发抓取分析（有界并发）
  2. 过滤：只保留「结构变化 >20%」的版本（第一版用 DOM 结构 diff 近似——slogan 变、
     pricing/关键 feature 翻转、或 H2 sections Jaccard 距离 >0.2）
  3. 每节点算「相对上一保留版本变了什么」的 change 列表

存储与 API 在 app.py（timelines 表落 InsForge，同评分卡 strangler-fig 打法）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from modules import website as _web

log = logging.getLogger("timeline")

_MAX_SNAPSHOTS = 24          # CDX 已按半年 collapse，够覆盖 2-3 年演进
_CONCURRENCY = 6             # Wayback 抓取并发上限
_CHANGE_JACCARD = 0.2        # sections 变化 >20% 视为显著改版


def normalize_domain(raw: str) -> str:
    d = (raw or "").strip().lower()
    for pfx in ("https://", "http://"):
        if d.startswith(pfx):
            d = d[len(pfx):]
    return d.split("/")[0].replace("www.", "").strip()


def _active_features(snap: dict) -> frozenset:
    feats = snap.get("features") or {}
    return frozenset(k for k, v in feats.items() if v)


def _to_node(snap: dict) -> dict:
    """把 _analyze_snapshot 的原始快照压成时间轴节点。"""
    return {
        "date": snap.get("date") or (snap.get("timestamp", "")[:8]),
        "timestamp": snap.get("timestamp", ""),
        "title": snap.get("title", ""),
        "slogan": snap.get("slogan", ""),
        "has_pricing": bool((snap.get("features") or {}).get("pricing")),
        "screens": snap.get("section_count", 0),
        "sections": (snap.get("headings_h2") or [])[:8],
        "features": {k: bool(v) for k, v in (snap.get("features") or {}).items()},
        "preview_url": snap.get("preview_url") or snap.get("archive_url", ""),
        "archive_url": snap.get("archive_url", ""),
    }


def _diff_changes(prev: dict, curr: dict) -> list:
    """curr 相对 prev 变了什么——返回「结构化代码」列表（语言中性），前端按语言本地化。
    形态：{"t":"slogan","v":...} / {"t":"add"|"remove","f":feature} / {"t":"screens","from":x,"to":y}"""
    ch = []
    if prev.get("slogan") and curr.get("slogan") and prev["slogan"] != curr["slogan"]:
        ch.append({"t": "slogan", "v": curr["slogan"][:48]})
    pf = _active_features({"features": prev.get("features")})
    cf = _active_features({"features": curr.get("features")})
    for f in sorted(cf - pf):
        ch.append({"t": "add", "f": f})
    for f in sorted(pf - cf):
        ch.append({"t": "remove", "f": f})
    ps, cs = curr.get("screens", 0), prev.get("screens", 0)
    if ps and cs and abs(ps - cs) >= max(2, cs * 0.5):
        ch.append({"t": "screens", "from": cs, "to": ps})
    return ch


def _is_significant(prev: dict, curr: dict) -> bool:
    """curr 相对上一保留版本是否「>20% 变化」。"""
    if prev.get("slogan") != curr.get("slogan"):
        return True
    if _active_features({"features": prev.get("features")}) != _active_features({"features": curr.get("features")}):
        return True
    a = set(prev.get("sections") or [])
    b = set(curr.get("sections") or [])
    union = a | b
    if union:
        jaccard = len(a & b) / len(union)
        if (1 - jaccard) > _CHANGE_JACCARD:
            return True
    return False


async def _analyze_bounded(domain: str, ts: str, sem: asyncio.Semaphore) -> Optional[dict]:
    async with sem:
        try:
            return await _web._analyze_snapshot(domain, ts)
        except Exception as e:
            log.warning("timeline snapshot 失败 %s@%s: %s", domain, ts, e)
            return None


async def build_timeline(domain: str) -> dict:
    """构建 <domain> 的考古时间轴。返回 {domain, total_snapshots, nodes:[...]}。"""
    domain = normalize_domain(domain)
    if not domain:
        return {"domain": "", "total_snapshots": 0, "nodes": [], "error": "invalid domain"}

    cdx = await _web._try_cdx(domain)
    timestamps = (cdx.get("all_timestamps") or [])[:_MAX_SNAPSHOTS]
    if not timestamps:
        return {"domain": domain, "total_snapshots": 0, "nodes": [],
                "error": "Wayback 无可用快照"}

    sem = asyncio.Semaphore(_CONCURRENCY)
    raw = await asyncio.gather(*[_analyze_bounded(domain, ts, sem) for ts in timestamps])

    # 清洗：去掉抓取失败 / 停放页 / 无 slogan 的空壳
    snaps = []
    for s in raw:
        if not s or s.get("error"):
            continue
        if _web._is_parked_page(s):
            continue
        node = _to_node(s)
        if not node["slogan"] and not node["title"]:
            continue
        snaps.append(node)
    snaps.sort(key=lambda n: n.get("date", "") or n.get("timestamp", ""))

    # 过滤到「显著改版」的版本；首末必留
    kept = []
    for node in snaps:
        if not kept:
            node["changes"] = [{"t": "first"}]
            kept.append(node)
            continue
        if _is_significant(kept[-1], node):
            node["changes"] = _diff_changes(kept[-1], node) or [{"t": "revamp"}]
            kept.append(node)
    # 保证最后一个版本在（哪怕它与上一保留版差异 <20%）
    if snaps and kept and kept[-1]["timestamp"] != snaps[-1]["timestamp"]:
        last = snaps[-1]
        last["changes"] = _diff_changes(kept[-1], last) or [{"t": "latest"}]
        kept.append(last)

    return {"domain": domain, "total_snapshots": len(timestamps), "nodes": kept}


def summarize_evolution(snapshots: list, first_seen: str = "", lang: str = "zh") -> str:
    """从官网历史快照生成「商业化演变阶段总结」——结合不同产品的演变节奏，
    给主分析报告的时间轴段加一段人话判断。规则驱动、不烧 LLM。

    snapshots: deep_timeline 的原始快照列表（含 date/slogan/features）。
    返回一段中/英文叙述；无足够数据返回空串。
    """
    pts = sorted(
        [s for s in (snapshots or []) if s.get("date") and not s.get("error")],
        key=lambda s: s.get("date", ""))
    if len(pts) < 2:
        return ""
    zh = not (lang or "").startswith("en")

    first, last = pts[0], pts[-1]
    fdate, ldate = first.get("date", "")[:7], last.get("date", "")[:7]
    fslogan = (first.get("slogan") or "").strip()[:50]
    lslogan = (last.get("slogan") or "").strip()[:50]

    # 首次出现定价页 = 商业化拐点
    priced = next((s for s in pts if (s.get("features") or {}).get("pricing")), None)
    # slogan 改版次数
    pivots = 0
    prev = None
    for s in pts:
        sl = (s.get("slogan") or "").strip()
        if prev is not None and sl and sl != prev:
            pivots += 1
        prev = sl or prev

    bits = []
    if zh:
        bits.append(f"从 {fdate} 首个有效版本（“{fslogan}”）到 {ldate}，共追踪 {len(pts)} 个关键版本。")
        if priced:
            pdate = priced.get("date", "")[:7]
            bits.append(f"**{pdate} 首次出现定价页 = 商业化拐点**——此前是产品/流量优先，之后开始变现。")
        else:
            bits.append("全程未见公开定价页，仍处产品/流量优先阶段（或走销售驱动、定价不公开）。")
        if pivots >= 2:
            bits.append(f"定位飘移较大：slogan 改版 {pivots} 次，最终收敛到“{lslogan}”，说明还在找 PMF 表达。")
        elif pivots == 1:
            bits.append(f"定位一次调整，收敛到“{lslogan}”，方向渐清晰。")
        else:
            bits.append("定位稳定，slogan 基本没变——早定方向或迭代克制。")
    else:
        bits.append(f"From the first real version in {fdate} (“{fslogan}”) to {ldate}, {len(pts)} key versions tracked.")
        if priced:
            pdate = priced.get("date", "")[:7]
            bits.append(f"**Pricing page first appeared {pdate} = the commercialization inflection** — product/traffic-first before, monetizing after.")
        else:
            bits.append("No public pricing page across the timeline — still product/traffic-first (or sales-led with private pricing).")
        if pivots >= 2:
            bits.append(f"Heavy repositioning: {pivots} slogan pivots, converging on “{lslogan}” — still finding its PMF wording.")
        elif pivots == 1:
            bits.append(f"One repositioning, converging on “{lslogan}”.")
        else:
            bits.append("Stable positioning — slogan barely changed.")
    return " ".join(bits)
