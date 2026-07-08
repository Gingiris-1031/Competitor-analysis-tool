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
    """curr 相对 prev 变了什么（人话列表）。"""
    ch = []
    if prev.get("slogan") and curr.get("slogan") and prev["slogan"] != curr["slogan"]:
        ch.append(f"Slogan 改为「{curr['slogan'][:48]}」")
    pf, cf = _active_features({"features": prev.get("features")}), _active_features({"features": curr.get("features")})
    _labels = {"pricing": "💰 定价页", "blog": "博客", "docs": "文档", "changelog": "Changelog",
               "faq": "FAQ", "trial": "免费试用", "demo": "Demo", "logos": "企业 Logo 墙",
               "testimonials": "用户评价", "case_study": "案例"}
    for f in cf - pf:
        ch.append(f"新增 {_labels.get(f, f)}")
    for f in pf - cf:
        ch.append(f"移除 {_labels.get(f, f)}")
    ps, cs = curr.get("screens", 0), prev.get("screens", 0)
    if ps and cs and abs(ps - cs) >= max(2, cs * 0.5):
        ch.append(f"页面规模 {cs}→{ps} 屏")
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
            node["changes"] = ["首个有效版本"]
            kept.append(node)
            continue
        if _is_significant(kept[-1], node):
            node["changes"] = _diff_changes(kept[-1], node) or ["版面改版"]
            kept.append(node)
    # 保证最后一个版本在（哪怕它与上一保留版差异 <20%）
    if snaps and kept and kept[-1]["timestamp"] != snaps[-1]["timestamp"]:
        last = snaps[-1]
        last["changes"] = _diff_changes(kept[-1], last) or ["最新版本"]
        kept.append(last)

    return {"domain": domain, "total_snapshots": len(timestamps), "nodes": kept}
