"""Supabase 客户端单例 — 后端使用 service_role key（绕过 RLS）"""
import os
import logging

log = logging.getLogger(__name__)

_client = None


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
            "id, email, plan_type, credits_balance, credits_used, credits_monthly_quota, reports_public_default"
        ).eq("id", user_id).single().execute()
        return result.data
    except Exception as e:
        log.debug("获取 profile 失败 user=%s: %s", user_id, e)
        return None


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
        return True
    except Exception as e:
        log.error("报告写入 Supabase 失败 job=%s: %s", job_id, e)
        return False
