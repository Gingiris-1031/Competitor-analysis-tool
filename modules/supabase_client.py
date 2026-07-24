"""Supabase 客户端单例 — 后端使用 service_role key（绕过 RLS）"""
import os
import logging

log = logging.getLogger(__name__)

_client = None


def supabase_required() -> bool:
    """
    True when the deployment INTENDS to use Supabase. We use SUPABASE_URL
    presence as the signal: if it's set, prod is meant to authenticate via
    Supabase. If get_supabase() then returns None (key missing/invalid), we
    must REFUSE auth-required requests with a 503 instead of silently
    falling into dev-mode — otherwise reports & credits get dropped.
    """
    return bool(os.environ.get("SUPABASE_URL", "").strip())


def get_supabase():
    """返回 Supabase Admin 客户端（懒加载单例）。环境变量未配置时返回 None。"""
    global _client
    if _client is not None:
        return _client

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

    if not url or not key:
        log.warning("Supabase 未配置（缺少 SUPABASE_URL 或 SUPABASE_SERVICE_KEY），跳过 Auth 检查")
        return None

    try:
        from supabase import create_client
        _client = create_client(url, key)
        log.info("Supabase 客户端初始化成功: %s", url)
    except Exception as e:
        log.error("Supabase 客户端初始化失败: %s", e)
        return None

    return _client


async def verify_token_and_get_user(token: str) -> dict | None:
    """
    验证 JWT token，返回 user dict（含 id / email）。
    验证失败返回 None。
    """
    sb = get_supabase()
    if not sb:
        return None
    try:
        resp = sb.auth.get_user(token)
        user = resp.user
        if not user:
            return None
        return {"id": str(user.id), "email": user.email}
    except Exception as e:
        log.debug("Token 验证失败: %s", e)
        return None


async def deduct_credit(user_id: str) -> bool:
    """
    原子扣减 1 积分。
    返回 True = 扣减成功；False = 余额不足或操作失败。
    """
    sb = get_supabase()
    if not sb:
        return True  # Supabase 未配置时放行（开发模式）

    try:
        result = sb.rpc("deduct_credit", {"p_user_id": user_id}).execute()
        # deduct_credit 函数返回 boolean
        return bool(result.data)
    except Exception as e:
        log.error("积分扣减失败 user=%s: %s", user_id, e)
        return False


async def get_user_profile(user_id: str) -> dict | None:
    """获取用户 profile（plan_type, credits_balance 等）"""
    sb = get_supabase()
    if not sb:
        return None
    try:
        result = sb.table("profiles").select(
            "id, email, plan_type, credits_balance, credits_used, credits_monthly_quota, "
            "reports_public_default, referral_source"
        ).eq("id", user_id).single().execute()
        return result.data
    except Exception as e:
        log.debug("获取 profile 失败 user=%s: %s", user_id, e)
        return None


async def list_user_reports(user_id: str, limit: int = 50) -> list[dict]:
    """
    列出用户最近的报告（用于登录用户的历史记录同步）。
    返回字段精简，避免把大 report JSON 一次拉回。
    """
    sb = get_supabase()
    if not sb:
        return []
    try:
        result = (
            sb.table("reports")
            .select("id, url, product_name, created_at, status")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        log.error("拉取用户报告列表失败 user=%s: %s", user_id, e)
        return []


async def save_report_to_db(
    job_id: str,
    user_id: str | None,
    url: str,
    product_name: str,
    report: dict,
    markdown: str,
    is_public: bool = True,
) -> bool:
    """将报告同步写入 Supabase reports 表（同时保留本地 JSON 文件）"""
    sb = get_supabase()
    if not sb:
        return False
    try:
        sb.table("reports").upsert({
            "id":           job_id,
            "user_id":      user_id,
            "url":          url,
            "product_name": product_name,
            "report":       report,
            "markdown":     markdown,
            "is_public":    is_public,
            "status":       "completed",
        }).execute()
        # Stage 2 migration: Supabase remains authoritative. When the
        # explicitly enabled mirror is healthy, copy the same completed row to
        # InsForge without allowing an auxiliary write to affect delivery.
        from modules import insforge_client as _insforge
        if _insforge.reports_dual_write_enabled():
            mirrored = await _insforge.mirror_report(
                job_id, user_id, url, product_name, report, markdown, is_public,
                status="completed",
            )
            if not mirrored:
                log.warning("InsForge report mirror unavailable job=%s; Supabase remains primary", job_id)
        return True
    except Exception as e:
        log.error("报告写入 Supabase 失败 job=%s: %s", job_id, e)
        return False


async def save_scorecard(
    card_hash: str,
    user_id: str | None,
    domain: str,
    category: str,
    inputs: dict,
    result: dict,
    competitors: list | None = None,
    is_public: bool = True,
    unlocked: bool = False,
) -> bool:
    """将增长诊断评分卡写入。免费预览层与付费解锁层共用一行，unlocked 标记是否已解锁。
    设了 INSFORGE_URL+KEY 则走 InsForge（评分卡迁移的第一块），否则回落 Supabase。"""
    from modules import insforge_client as _insforge
    if _insforge.enabled():
        return await _insforge.save_scorecard(
            card_hash, user_id, domain, category, inputs, result,
            competitors=competitors, is_public=is_public, unlocked=unlocked)
    sb = get_supabase()
    if not sb:
        return False
    try:
        sb.table("scorecards").upsert({
            "id":          card_hash,
            "user_id":     user_id,
            "domain":      domain,
            "category":    category,
            "inputs":      inputs,
            "result":      result,
            "competitors": competitors or [],
            "is_public":   is_public,
            "unlocked":    unlocked,
        }).execute()
        return True
    except Exception as e:
        log.error("评分卡写入 Supabase 失败 hash=%s: %s", card_hash, e)
        return False


async def get_scorecard(card_hash: str) -> dict | None:
    """按 hash 读取评分卡整行（含 result / competitors / unlocked）。"""
    from modules import insforge_client as _insforge
    if _insforge.enabled():
        return await _insforge.get_scorecard(card_hash)
    sb = get_supabase()
    if not sb:
        return None
    try:
        result = sb.table("scorecards").select(
            "id,user_id,domain,category,inputs,result,competitors,is_public,unlocked,created_at"
        ).eq("id", card_hash).limit(1).execute()
        rows = result.data or []
        return rows[0] if rows else None
    except Exception as e:
        log.error("评分卡读取失败 hash=%s: %s", card_hash, e)
        return None


async def mark_scorecard_unlocked(card_hash: str) -> bool:
    """把评分卡标记为已解锁（付费后调用）。"""
    from modules import insforge_client as _insforge
    if _insforge.enabled():
        return await _insforge.mark_scorecard_unlocked(card_hash)
    sb = get_supabase()
    if not sb:
        return False
    try:
        sb.table("scorecards").update({"unlocked": True}).eq("id", card_hash).execute()
        return True
    except Exception as e:
        log.error("评分卡解锁标记失败 hash=%s: %s", card_hash, e)
        return False
