"""InsForge REST 客户端 — 评分卡（scorecards）的存储后端（strangler-fig 第一块）。

背景：Supabase dashboard 绑在已封的旧 GitHub 上、无法登录建表。评分卡是全新、
无 auth 依赖、无存量数据的独立功能，正好作为迁移 InsForge 的第一块试验田——
scorecards 直接生在 InsForge，analook 其余（reports/profiles/auth）继续留 Supabase。

开关：设了 INSFORGE_URL + INSFORGE_API_KEY 就走 InsForge，否则回落 Supabase
（supabase_client 里的三个评分卡函数据此委派）。全部只碰 scorecards，零破坏其余表。

表结构与 Supabase 版一致（id TEXT 主键存分享 hash），已用 CLI 建好：
  npx @insforge/cli db query "CREATE TABLE scorecards (id TEXT PRIMARY KEY, ...)"
运行时用项目 **api_key（admin，server-only）** 作 Bearer，绕过 RLS 读写。

InsForge REST（docs.insforge.dev，已实测 201/200/204 通过）：
  {POST,GET,PATCH,DELETE} {BASE}/api/database/records/{table}
  header: Authorization: Bearer <api_key>；PostgREST 风格 ?col=eq.val
  插入 body 为「行数组」；Prefer: return=representation 回传行
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("insforge")

TABLE = "scorecards"
_TIMEOUT = httpx.Timeout(15.0)


def enabled() -> bool:
    """设了 URL + key 才启用 InsForge 后端。"""
    return bool(os.environ.get("INSFORGE_URL", "").strip()
                and os.environ.get("INSFORGE_API_KEY", "").strip())


def _base() -> str:
    return os.environ.get("INSFORGE_URL", "").strip().rstrip("/")


def _key() -> str:
    return os.environ.get("INSFORGE_API_KEY", "").strip()


def _records_url() -> str:
    return f"{_base()}/api/database/records/{TABLE}"


def _headers(write: bool = False) -> dict:
    h = {"Authorization": f"Bearer {_key()}"}
    if write:
        h["Content-Type"] = "application/json"
        h["Prefer"] = "return=representation"
    return h


async def save_scorecard(card_hash, user_id, domain, category,
                         inputs, result, competitors=None,
                         is_public=True, unlocked=False) -> bool:
    """upsert 一张评分卡到 InsForge。先删同 id 再插（简化 v1 幂等，无原生 upsert）。"""
    row = {
        "id":          card_hash,
        "user_id":     user_id,
        "domain":      domain,
        "category":    category,
        "inputs":      inputs or {},
        "result":      result or {},
        "competitors": competitors or [],
        "is_public":   bool(is_public),
        "unlocked":    bool(unlocked),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            await c.delete(_records_url(), params={"id": f"eq.{card_hash}"},
                           headers=_headers())
            resp = await c.post(_records_url(), json=[row], headers=_headers(write=True))
            if resp.status_code >= 300:
                log.error("InsForge 评分卡写入失败 hash=%s status=%s body=%s",
                          card_hash, resp.status_code, resp.text[:300])
                return False
        return True
    except Exception as e:
        log.error("InsForge 评分卡写入异常 hash=%s: %s", card_hash, e)
        return False


async def get_scorecard(card_hash: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.get(_records_url(),
                               params={"id": f"eq.{card_hash}", "limit": 1},
                               headers=_headers())
            if resp.status_code >= 300:
                log.error("InsForge 评分卡读取失败 hash=%s status=%s", card_hash, resp.status_code)
                return None
            rows = resp.json() or []
            return rows[0] if rows else None
    except Exception as e:
        log.error("InsForge 评分卡读取异常 hash=%s: %s", card_hash, e)
        return None


async def mark_scorecard_unlocked(card_hash: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.patch(_records_url(),
                                 params={"id": f"eq.{card_hash}"},
                                 json={"unlocked": True},
                                 headers=_headers(write=True))
            if resp.status_code >= 300:
                log.error("InsForge 评分卡解锁失败 hash=%s status=%s", card_hash, resp.status_code)
                return False
        return True
    except Exception as e:
        log.error("InsForge 评分卡解锁异常 hash=%s: %s", card_hash, e)
        return False
