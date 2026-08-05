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
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx

log = logging.getLogger("insforge")

TABLE = "scorecards"
REPORTS_TABLE = "reports"
MCP_KEYS_TABLE = "mcp_api_keys"
MCP_ACCOUNTS_TABLE = "mcp_accounts"
ACCOUNT_PROFILES_TABLE = "account_profiles"
_TIMEOUT = httpx.Timeout(15.0)


def enabled() -> bool:
    """设了 URL + key 才启用 InsForge 后端。"""
    return bool(os.environ.get("INSFORGE_URL", "").strip()
                and os.environ.get("INSFORGE_API_KEY", "").strip())


def _base() -> str:
    return os.environ.get("INSFORGE_URL", "").strip().rstrip("/")


def _key() -> str:
    return os.environ.get("INSFORGE_API_KEY", "").strip()


def _records_url(table: str = TABLE) -> str:
    return f"{_base()}/api/database/records/{table}"


def _rpc_url(name: str) -> str:
    return f"{_base()}/api/database/rpc/{name}"


def reports_dual_write_enabled() -> bool:
    """Opt-in mirror for reports while Supabase remains the source of truth."""
    return enabled() and (os.environ.get("INSFORGE_REPORTS_DUAL_WRITE") or "").lower() in {
        "1", "true", "yes", "on"
    }


def _headers(write: bool = False) -> dict:
    h = {"Authorization": f"Bearer {_key()}"}
    if write:
        h["Content-Type"] = "application/json"
        h["Prefer"] = "return=representation"
    return h


async def verify_user_token(token: str) -> Optional[dict]:
    """Verify an InsForge user access token and return only safe identity fields."""
    if not enabled() or not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.get(
                f"{_base()}/api/auth/sessions/current",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code >= 300:
                return None
            user = (resp.json() or {}).get("user") or {}
            if not user.get("id"):
                return None
            return {"id": str(user["id"]), "email": user.get("email") or ""}
    except Exception as e:
        log.debug("InsForge user token verification failed: %s", e)
        return None


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


async def mirror_report(
    job_id: str, user_id: str | None, url: str, product_name: str,
    report: dict, markdown: str, is_public: bool, status: str = "completed",
    created_at: str | None = None,
) -> bool:
    """Best-effort reports mirror; never replaces the Supabase primary write."""
    if not reports_dual_write_enabled():
        return False
    return await save_report(job_id, user_id, url, product_name, report, markdown, is_public, status, created_at)


async def save_report(
    job_id: str, user_id: str | None, url: str, product_name: str,
    report: dict, markdown: str, is_public: bool, status: str = "completed",
    created_at: str | None = None,
) -> bool:
    """Persist a report in InsForge. The server is the only database caller."""
    if not enabled():
        return False
    row = {
        "id": job_id, "user_id": user_id, "url": url,
        "product_name": product_name or "", "report": report or {},
        "markdown": markdown or "", "is_public": bool(is_public),
        "status": status if status in {"running", "completed", "failed"} else "completed",
    }
    if created_at:
        row["created_at"] = created_at
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            # Do not use delete-then-insert here. A deploy, SSH disconnect, or
            # request timeout between those calls would make a previously
            # migrated report disappear from InsForge. Read once, PATCH an
            # existing row, and only INSERT when its immutable ID is absent.
            existing = await c.get(
                _records_url(REPORTS_TABLE),
                params={"id": f"eq.{job_id}", "select": "id", "limit": 1},
                headers=_headers(),
            )
            if existing.status_code >= 300:
                log.error("InsForge report lookup failed job=%s status=%s", job_id, existing.status_code)
                return False
            if existing.json() or []:
                resp = await c.patch(
                    _records_url(REPORTS_TABLE), params={"id": f"eq.{job_id}"},
                    # Backfill passes the original source timestamp. Normal
                    # runtime saves omit it and retain the database default.
                    json=row, headers=_headers(write=True),
                )
            else:
                resp = await c.post(_records_url(REPORTS_TABLE), json=[row], headers=_headers(write=True))
            if resp.status_code >= 300:
                log.error("InsForge report save failed job=%s status=%s", job_id, resp.status_code)
                return False
        return True
    except Exception as e:
        log.error("InsForge report save exception job=%s: %s", job_id, e)
        return False


async def get_report_record(job_id: str) -> Optional[dict]:
    """Return a report plus access metadata. Never expose this REST call to clients."""
    if not enabled():
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.get(
                _records_url(REPORTS_TABLE),
                params={"id": f"eq.{job_id}", "limit": 1}, headers=_headers(),
            )
            if resp.status_code >= 300:
                log.error("InsForge report read failed job=%s status=%s", job_id, resp.status_code)
                return None
            rows = resp.json() or []
            return rows[0] if rows else None
    except Exception as e:
        log.error("InsForge report read exception job=%s: %s", job_id, e)
        return None


def get_report_record_sync(job_id: str) -> Optional[dict]:
    """Small sync bridge for existing FastAPI routes that predate InsForge."""
    if not enabled():
        return None
    try:
        with httpx.Client(timeout=httpx.Timeout(4.0)) as c:
            resp = c.get(
                _records_url(REPORTS_TABLE),
                params={"id": f"eq.{job_id}", "limit": 1}, headers=_headers(),
            )
            if resp.status_code >= 300:
                return None
            rows = resp.json() or []
            return rows[0] if rows else None
    except Exception as e:
        log.error("InsForge report sync read exception job=%s: %s", job_id, e)
        return None


async def list_reports_for_user(user_id: str, limit: int = 50) -> list[dict]:
    if not enabled() or not user_id:
        return []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.get(
                _records_url(REPORTS_TABLE),
                params={
                    "user_id": f"eq.{user_id}", "status": "eq.completed",
                    "select": "id,url,product_name,created_at,status", "order": "created_at.desc",
                    "limit": min(max(int(limit), 1), 50),
                }, headers=_headers(),
            )
            return resp.json() if resp.status_code < 300 else []
    except Exception as e:
        log.error("InsForge report list exception user=%s: %s", user_id, e)
        return []


async def save_account_profile(profile: dict) -> bool:
    """Upsert the private Supabase-account mirror during the staged cutover.

    `legacy_user_id` deliberately remains the key until the user has completed
    an InsForge password reset or OAuth sign-in and can be linked safely.
    """
    if not enabled() or not profile.get("id") or not profile.get("email"):
        return False
    row = {
        "legacy_user_id": str(profile["id"]),
        "email": str(profile["email"]).strip().lower(),
        "plan_type": str(profile.get("plan_type") or "free"),
        "credits_balance": max(0, int(profile.get("credits_balance") or 0)),
        "credits_used": max(0, int(profile.get("credits_used") or 0)),
        "credits_monthly_quota": max(0, int(profile.get("credits_monthly_quota") or 0)),
        "reports_public_default": bool(profile.get("reports_public_default", True)),
        "referral_source": profile.get("referral_source") or None,
        "source_created_at": profile.get("created_at") or None,
        "source_updated_at": profile.get("updated_at") or None,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            existing = await c.get(
                _records_url(ACCOUNT_PROFILES_TABLE),
                params={"legacy_user_id": f"eq.{row['legacy_user_id']}", "select": "legacy_user_id", "limit": 1},
                headers=_headers(),
            )
            if existing.status_code >= 300:
                log.error("InsForge account profile lookup failed user=%s status=%s", row["legacy_user_id"], existing.status_code)
                return False
            if existing.json() or []:
                resp = await c.patch(
                    _records_url(ACCOUNT_PROFILES_TABLE),
                    params={"legacy_user_id": f"eq.{row['legacy_user_id']}"},
                    json=row, headers=_headers(write=True),
                )
            else:
                resp = await c.post(
                    _records_url(ACCOUNT_PROFILES_TABLE), json=[row], headers=_headers(write=True),
                )
            if resp.status_code >= 300:
                log.error("InsForge account profile save failed user=%s status=%s", row["legacy_user_id"], resp.status_code)
                return False
        return True
    except Exception as e:
        log.error("InsForge account profile save exception user=%s: %s", profile.get("id"), e)
        return False


def _key_hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def create_mcp_api_key(owner_id: str, name: str, initial_credits: int = 3) -> Optional[dict]:
    """Create a one-time-display MCP key and its account credit ledger."""
    if not enabled() or not owner_id:
        return None
    raw_key = "anl_mcp_" + secrets.token_urlsafe(32)
    prefix = raw_key[:20]
    key_id = secrets.token_hex(16)
    row = {
        "id": key_id, "owner_id": owner_id, "name": (name or "MCP key")[:80],
        "key_prefix": prefix, "secret_hash": _key_hash(raw_key),
        "scopes": ["analysis:read", "analysis:write"],
    }
    account = {"owner_id": owner_id, "credits_balance": max(0, int(initial_credits))}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            # An account is created once per owner; ignore a duplicate response.
            account_resp = await c.post(_records_url(MCP_ACCOUNTS_TABLE), json=[account], headers=_headers(write=True))
            if account_resp.status_code >= 300 and account_resp.status_code != 409:
                log.error("InsForge MCP account create failed owner=%s status=%s", owner_id, account_resp.status_code)
                return None
            resp = await c.post(_records_url(MCP_KEYS_TABLE), json=[row], headers=_headers(write=True))
            if resp.status_code >= 300:
                log.error("InsForge MCP key create failed owner=%s status=%s", owner_id, resp.status_code)
                return None
        return {"id": key_id, "key": raw_key, "prefix": prefix, "name": row["name"]}
    except Exception as e:
        log.error("InsForge MCP key create exception owner=%s: %s", owner_id, e)
        return None


async def resolve_mcp_api_key(raw_key: str) -> Optional[dict]:
    """Validate a bearer key without logging it; update last-used best-effort."""
    if not enabled() or not raw_key.startswith("anl_mcp_"):
        return None
    prefix = raw_key[:20]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.get(
                _records_url(MCP_KEYS_TABLE), params={"key_prefix": f"eq.{prefix}", "limit": 1}, headers=_headers(),
            )
            if resp.status_code >= 300:
                return None
            rows = resp.json() or []
            if not rows:
                return None
            row = rows[0]
            if row.get("revoked_at") or row.get("expires_at"):
                return None
            if not secrets.compare_digest(str(row.get("secret_hash") or ""), _key_hash(raw_key)):
                return None
            await c.patch(
                _records_url(MCP_KEYS_TABLE), params={"id": f"eq.{row['id']}"},
                json={"last_used_at": datetime.now(timezone.utc).isoformat()}, headers=_headers(write=True),
            )
            return row
    except Exception as e:
        log.error("InsForge MCP key resolve exception: %s", e)
        return None


async def list_mcp_api_keys(owner_id: str) -> list[dict]:
    if not enabled() or not owner_id:
        return []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.get(
                _records_url(MCP_KEYS_TABLE),
                params={
                    "owner_id": f"eq.{owner_id}",
                    "select": "id,name,key_prefix,scopes,expires_at,revoked_at,last_used_at,created_at",
                    "order": "created_at.desc", "limit": 50,
                }, headers=_headers(),
            )
            return resp.json() if resp.status_code < 300 else []
    except Exception as e:
        log.error("InsForge MCP key list exception owner=%s: %s", owner_id, e)
        return []


async def revoke_mcp_api_key(owner_id: str, key_id: str) -> bool:
    if not enabled() or not owner_id or not key_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.patch(
                _records_url(MCP_KEYS_TABLE),
                params={"id": f"eq.{key_id}", "owner_id": f"eq.{owner_id}", "revoked_at": "is.null"},
                json={"revoked_at": datetime.now(timezone.utc).isoformat()}, headers=_headers(write=True),
            )
            return resp.status_code < 300
    except Exception as e:
        log.error("InsForge MCP key revoke exception owner=%s: %s", owner_id, e)
        return False


async def consume_mcp_credit(key_id: str, amount: int = 1) -> Optional[int]:
    """Atomically charge an MCP key's owner account via a database RPC."""
    if not enabled() or not key_id or amount < 1:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.post(
                _rpc_url("consume_mcp_credit"), json={"p_key_id": key_id, "p_amount": amount}, headers=_headers(write=True),
            )
            if resp.status_code >= 300:
                return None
            remaining = resp.json()
            return int(remaining) if remaining is not None else None
    except Exception as e:
        log.error("InsForge MCP credit consume exception: %s", e)
        return None


# ── 时间轴（timelines 表，id=归一化域名，每域名一条 canonical 时间轴）────────
async def save_timeline(domain: str, data: dict, is_public: bool = True) -> bool:
    """upsert 一个域名的考古时间轴。先删同 id 再插（简化幂等）。"""
    url = _records_url("timelines")
    row = {"id": domain, "domain": domain, "data": data or {}, "is_public": bool(is_public)}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            await c.delete(url, params={"id": f"eq.{domain}"}, headers=_headers())
            resp = await c.post(url, json=[row], headers=_headers(write=True))
            if resp.status_code >= 300:
                log.error("InsForge 时间轴写入失败 domain=%s status=%s body=%s",
                          domain, resp.status_code, resp.text[:300])
                return False
        return True
    except Exception as e:
        log.error("InsForge 时间轴写入异常 domain=%s: %s", domain, e)
        return False


async def get_timeline(domain: str) -> Optional[dict]:
    """按域名读时间轴整行（含 data / created_at）。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.get(_records_url("timelines"),
                               params={"id": f"eq.{domain}", "limit": 1},
                               headers=_headers())
            if resp.status_code >= 300:
                log.error("InsForge 时间轴读取失败 domain=%s status=%s", domain, resp.status_code)
                return None
            rows = resp.json() or []
            return rows[0] if rows else None
    except Exception as e:
        log.error("InsForge 时间轴读取异常 domain=%s: %s", domain, e)
        return None
