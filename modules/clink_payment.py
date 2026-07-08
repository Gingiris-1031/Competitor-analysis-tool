"""Clink 支付集成 — Checkout + Webhook + 信用额度管理

迁移自 Polar.sh。核心信用逻辑（_grant_credits, _update_user_plan）与
polar_payment.py 保持一致，防止并行运行期间出现分叉。

Clink API base: https://api.clinkbill.com/api
Auth: X-API-Key header  (Secret Key from Developers > API Keys)
Webhook signature: HMAC-SHA256 over "{X-Clink-Timestamp}.{raw_body}"
  verified via X-Clink-Signature header
"""

import hashlib
import hmac
import logging
import os
import time
from collections import OrderedDict

import httpx

log = logging.getLogger(__name__)

# UAT: https://uat-api.clinkbill.com/api  |  Prod: https://api.clinkbill.com/api
_CLINK_ENV = os.environ.get("CLINK_ENV", "production").lower()
CLINK_API = (
    "https://uat-api.clinkbill.com/api"
    if _CLINK_ENV in ("uat", "sandbox", "test", "staging")
    else "https://api.clinkbill.com/api"
)

# ── In-memory idempotency store ───────────────────────────────────────────────
# Clink retries up to 10× with exponential backoff (≈ 1 day window).
# We track event IDs to avoid double-crediting on retry.
_seen_events: "OrderedDict[str, float]" = OrderedDict()
_SEEN_MAX = 2000
_SEEN_TTL = 26 * 60 * 60  # 26 h — safely covers Clink's ~24 h retry window


def mark_event_seen(event_id: str) -> bool:
    """Record an event id. Returns True if new, False if duplicate."""
    if not event_id:
        return True
    now = time.time()
    while _seen_events and (now - next(iter(_seen_events.values()))) > _SEEN_TTL:
        _seen_events.popitem(last=False)
    if event_id in _seen_events:
        return False
    _seen_events[event_id] = now
    while len(_seen_events) > _SEEN_MAX:
        _seen_events.popitem(last=False)
    return True


# ── Plan definitions (mirrors polar_payment.py) ───────────────────────────────
# Clink product IDs are set in the dashboard (Products tab) and stored as env
# vars so the dashboard can be reconfigured without a redeploy.
# Format: CLINK_PRODUCT_<PLAN_KEY_UPPER>
CLINK_PRODUCTS: dict[str, str] = {
    "pro":           os.environ.get("CLINK_PRODUCT_PRO", ""),
    "team":          os.environ.get("CLINK_PRODUCT_TEAM", ""),
    "single_report": os.environ.get("CLINK_PRODUCT_SINGLE", ""),
    "growth_audit":  os.environ.get("CLINK_PRODUCT_GROWTH_AUDIT", ""),
    "autopilot":     os.environ.get("CLINK_PRODUCT_AUTOPILOT", ""),
    "autopilot_team":os.environ.get("CLINK_PRODUCT_AUTOPILOT_TEAM", ""),
}

# Corresponding Clink price IDs (one price per product for simple plans).
CLINK_PRICES: dict[str, str] = {
    "pro":           os.environ.get("CLINK_PRICE_PRO", ""),
    "team":          os.environ.get("CLINK_PRICE_TEAM", ""),
    "single_report": os.environ.get("CLINK_PRICE_SINGLE", ""),
    "growth_audit":  os.environ.get("CLINK_PRICE_GROWTH_AUDIT", ""),
    "autopilot":     os.environ.get("CLINK_PRICE_AUTOPILOT", ""),
    "autopilot_team":os.environ.get("CLINK_PRICE_AUTOPILOT_TEAM", ""),
}

# Pricing in USD cents (for non-registered product mode fallback)
# Clink originalAmount unit is USD (not cents)
PLAN_AMOUNTS_CENTS: dict[str, int] = {
    "pro":           19,    # $19/mo
    "team":          79,    # $79/mo
    "single_report":  5,    # $5 one-time
    "growth_audit":  19,    # $19/mo (Growth Audit subscription, 3 audits/mo)
    "autopilot":     49,    # $49/mo
    "autopilot_team":149,   # $149/mo
}

PLAN_CREDITS: dict[str, int] = {
    "pro":           30,
    "team":          100,
    "single_report":  1,
    "growth_audit":  15,
    "autopilot":     30,
    "autopilot_team":100,
    "free":           2,
}

# Subscription plans (monthly recurring) vs one-time plans
SUBSCRIPTION_PLANS = {"pro", "team", "autopilot", "autopilot_team"}


def _get_api_key() -> str:
    return os.environ.get("CLINK_SECRET_KEY", "").strip()


def _headers() -> dict:
    """Standard Clink API request headers."""
    return {
        "X-API-Key": _get_api_key(),
        "X-Timestamp": str(int(time.time() * 1000)),
        "Content-Type": "application/json",
    }


# ── Checkout session creation ─────────────────────────────────────────────────

async def create_checkout(
    product_key: str,
    user_email: str = "",
    user_id: str = "",
    success_url: str = "https://www.analook.com/?payment=success",
    cancel_url: str = "https://www.analook.com/pricing.html?payment=canceled",
) -> dict:
    """Create a Clink hosted-page checkout session.

    Tries registered-product mode first (productId + priceId from env vars).
    Falls back to non-registered mode (priceDataList with inline amount) if
    product/price IDs are not configured.

    Returns {url, sessionId} on success, {error: str} on failure.
    """
    api_key = _get_api_key()
    if not api_key:
        return {"error": "Clink not configured (CLINK_SECRET_KEY missing)"}
    if product_key not in PLAN_AMOUNTS_CENTS:
        return {"error": f"Unknown plan: {product_key}"}

    payload: dict = {
        "uiMode": "hostedPage",
        "successUrl": success_url,
        "cancelUrl": cancel_url,
        "originalCurrency": "USD",
        "originalAmount": PLAN_AMOUNTS_CENTS[product_key],
        # merchantReferenceId lets us reconcile in webhook without relying on email
        "merchantReferenceId": f"analook-{product_key}-{int(time.time())}",
        "metadata": {
            "product_key": product_key,
            **({"user_id": user_id} if user_id else {}),
        },
    }

    # Customer resolution — prefer referenceCustomerId (our Supabase user id)
    # so returning customers are resolved even if they change email.
    # Clink requires at least one of: customerId, customerEmail, referenceCustomerId.
    # For unauthenticated users we generate an ephemeral reference so Clink
    # can create an anonymous customer record (they supply email at checkout).
    if user_id:
        payload["referenceCustomerId"] = user_id
    elif not user_email:
        # Anonymous checkout — Clink will collect email on the hosted page
        payload["referenceCustomerId"] = f"anon-{product_key}-{int(time.time())}"
    if user_email:
        payload["customerEmail"] = user_email

    # Registered product mode if IDs are configured
    product_id = CLINK_PRODUCTS.get(product_key, "")
    price_id = CLINK_PRICES.get(product_key, "")
    if product_id and price_id:
        payload["productId"] = product_id
        payload["priceId"] = price_id
    else:
        # Non-registered product mode: inline line item
        plan_display = product_key.replace("_", " ").title()
        payload["priceDataList"] = [
            {
                "name": f"Analook {plan_display}",
                "quantity": 1,
                "unitAmount": PLAN_AMOUNTS_CENTS[product_key],
                "currency": "USD",
            }
        ]

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{CLINK_API}/checkout/session",
                headers=_headers(),
                json=payload,
            )
            if resp.status_code in (200, 201):
                resp_json = resp.json()
                # Clink wraps response: {code:200, msg:'Success', data:{sessionId,url,...}}
                # Non-200 code means error even if HTTP status is 200
                clink_code = resp_json.get("code", 0)
                if clink_code != 200:
                    msg = resp_json.get("msg", "unknown error")
                    log.error("Clink checkout error code=%s msg=%s", clink_code, msg)
                    return {"error": f"Clink error {clink_code}: {msg}"}
                data = resp_json.get("data") or {}
                return {
                    "url": data.get("url", ""),
                    "sessionId": data.get("sessionId", ""),
                    # keep "id" alias for backward compat with frontend
                    "id": data.get("sessionId", ""),
                }
            log.error("Clink checkout HTTP %s: %s", resp.status_code, resp.text[:300])
            return {"error": f"Clink HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as exc:
        log.error("Clink checkout error: %s", exc)
        return {"error": f"Clink error: {str(exc)[:100]}"}


# ── Webhook signature verification ───────────────────────────────────────────

def verify_webhook_signature(
    raw_body: bytes,
    timestamp: str,
    signature: str,
    signing_key: str,
    tolerance_seconds: int = 5 * 60,
) -> bool:
    """Verify Clink webhook HMAC-SHA256 signature.

    Clink signs: HMAC-SHA256( key=signing_key, msg="{timestamp}.{raw_body}" )
    Headers: X-Clink-Timestamp, X-Clink-Signature
    """
    if not signing_key or not timestamp or not signature:
        return False
    # Replay protection: timestamp must be within ±tolerance of now
    try:
        ts_sec = int(timestamp) / 1000 if len(timestamp) == 13 else int(timestamp)
        if abs(time.time() - ts_sec) > tolerance_seconds:
            return False
    except (ValueError, TypeError):
        return False
    try:
        msg = f"{timestamp}.".encode() + raw_body
        expected = hmac.new(
            signing_key.encode("utf-8"), msg, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature.lower())
    except Exception:
        return False


# ── Webhook event handling ────────────────────────────────────────────────────

async def handle_webhook_event(event: dict) -> dict:
    """Dispatch a Clink webhook event to the appropriate handler."""
    # Clink event structure (from docs): top-level keys include the event group
    # name as the key and the event data as the value.
    # Known event groups: order, subscription, session, refund, dispute

    if "order" in event:
        return await _handle_order_event(event["order"])
    elif "subscription" in event:
        return await _handle_subscription_event(event["subscription"])
    elif "session" in event:
        return await _handle_session_event(event["session"])
    else:
        log.info("Clink webhook: unhandled event keys=%s", list(event.keys()))
        return {"action": "ignored", "keys": list(event.keys())}


async def _handle_order_event(order: dict) -> dict:
    """order webhook — triggered when order is created or updated.

    We grant credits on status == SUCCEEDED for one-time plans.
    Subscription order.SUCCEEDED is also handled here (covers autopilot plan).
    """
    status = (order.get("status") or "").upper()
    if status != "SUCCEEDED":
        return {"action": "order_ignored", "status": status}

    customer_email = _extract_email(order)
    product_key = _extract_product_key(order)
    user_id = _extract_user_id(order)

    log.info("Clink order.SUCCEEDED: email=%s product_key=%s user_id=%s",
             customer_email, product_key, user_id)

    if not user_id and customer_email:
        user_id = await _find_user_by_email(customer_email)

    if user_id and product_key:
        if product_key in SUBSCRIPTION_PLANS:
            await _update_user_plan(user_id, product_key)
        else:
            await _grant_credits(user_id, product_key)

    return {"action": "order_succeeded", "plan": product_key, "email": customer_email}


async def _handle_subscription_event(sub: dict) -> dict:
    """subscription webhook — created, activated, updated, canceled."""
    status = (sub.get("status") or "").upper()
    customer_email = _extract_email(sub)
    product_key = _extract_product_key(sub)

    user_id = _extract_user_id(sub)
    if not user_id and customer_email:
        user_id = await _find_user_by_email(customer_email)

    if status in ("ACTIVE", "ACTIVATED", "TRIALING"):
        if user_id and product_key:
            await _update_user_plan(user_id, product_key)
        return {"action": "subscription_activated", "plan": product_key}
    elif status in ("CANCELED", "CANCELLED", "EXPIRED"):
        if user_id:
            await _update_user_plan(user_id, "free")
        return {"action": "subscription_canceled", "email": customer_email}
    elif status == "PAST_DUE":
        log.warning("Clink subscription PAST_DUE: email=%s", customer_email)
        return {"action": "subscription_past_due", "email": customer_email}
    else:
        return {"action": "subscription_ignored", "status": status}


async def _handle_session_event(session: dict) -> dict:
    """session webhook — completed or expired.

    On COMPLETED we derive plan from metadata and grant credits.
    This is the primary fulfillment signal for hosted-page checkout.
    """
    status = (session.get("status") or "").upper()
    if status != "COMPLETED":
        return {"action": "session_ignored", "status": status}

    metadata = session.get("metadata") or {}
    product_key = metadata.get("product_key", "")
    user_id = metadata.get("user_id", "")
    customer_email = _extract_email(session)

    log.info("Clink session.COMPLETED: product_key=%s user_id=%s email=%s",
             product_key, user_id, customer_email)

    if not user_id and customer_email:
        user_id = await _find_user_by_email(customer_email)

    if user_id and product_key:
        if product_key in SUBSCRIPTION_PLANS:
            await _update_user_plan(user_id, product_key)
        else:
            await _grant_credits(user_id, product_key)

    return {"action": "session_completed", "plan": product_key, "email": customer_email}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_email(obj: dict) -> str:
    """Try common paths for customer email in Clink event payloads."""
    if not obj:
        return ""
    return (
        obj.get("customerEmail")
        or (obj.get("customer") or {}).get("email")
        or ""
    )


def _extract_user_id(obj: dict) -> str:
    """Extract our Supabase user_id from metadata or referenceCustomerId."""
    if not obj:
        return ""
    metadata = obj.get("metadata") or {}
    return (
        metadata.get("user_id")
        or obj.get("referenceCustomerId")
        or ""
    )


def _extract_product_key(obj: dict) -> str:
    """Derive plan key from metadata.product_key, or reverse-map product/price IDs."""
    if not obj:
        return ""
    metadata = obj.get("metadata") or {}
    key = metadata.get("product_key", "")
    if key:
        return key

    # Fallback: reverse-map by productId or priceId
    product_id = obj.get("productId", "")
    price_id = obj.get("priceId", "")
    for plan, pid in CLINK_PRODUCTS.items():
        if pid and pid == product_id:
            return plan
    for plan, pid in CLINK_PRICES.items():
        if pid and pid == price_id:
            return plan

    # Last resort: infer from priceDataList name
    price_list = obj.get("priceDataList") or []
    if price_list:
        name = (price_list[0].get("name") or "").lower()
        for plan in PLAN_AMOUNTS_CENTS:
            if plan.replace("_", " ") in name:
                return plan
    return ""


async def _find_user_by_email(email: str) -> str | None:
    if not email:
        return None
    try:
        from .supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return None
        result = sb.table("profiles").select("id").eq("email", email).limit(1).execute()
        if result.data:
            return result.data[0]["id"]
    except Exception as exc:
        log.error("Clink _find_user_by_email failed: %s", exc)
    return None


async def _grant_credits(user_id: str, plan: str) -> None:
    """Add credits to user based on plan.

    Same balance-preservation logic as polar_payment._grant_credits:
        new_balance = max(current_balance, plan_quota)
    Never downgrades a user with accumulated credits.
    """
    credits = PLAN_CREDITS.get(plan, 0)
    if not credits:
        return
    try:
        from .supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return
        if plan == "single_report":
            # One-time top-up: increment the balance. The add_credits() Postgres
            # RPC was never created in the DB (PGRST202 "function not found"), so
            # the old sb.rpc("add_credits") call threw, got swallowed by the
            # except below, and $5 single-report buyers received 0 credits.
            # Do the add in application code instead (read-modify-write; concurrent
            # single-report webhooks for the same user are rare enough that the
            # lack of atomicity is acceptable, and matches the subscription path).
            cur = sb.table("profiles").select("credits_balance").eq("id", user_id).single().execute()
            current = (cur.data or {}).get("credits_balance") or 0
            sb.table("profiles").update(
                {"credits_balance": current + credits}
            ).eq("id", user_id).execute()
            log.info("Clink granted %d single-report credit(s) to %s: %d→%d",
                     credits, user_id, current, current + credits)
            return

        cur = sb.table("profiles").select("credits_balance").eq("id", user_id).single().execute()
        current = (cur.data or {}).get("credits_balance") or 0
        new_balance = max(current, credits)
        sb.table("profiles").update({
            "plan_type":             plan,
            "credits_monthly_quota": credits,
            "credits_balance":       new_balance,
            "credits_used":          0,
        }).eq("id", user_id).execute()
        log.info(
            "Clink granted plan=%s to %s: quota=%d, balance %d→%d",
            plan, user_id, credits, current, new_balance,
        )
    except Exception as exc:
        log.error("Clink _grant_credits failed user=%s: %s", user_id, exc)


async def _update_user_plan(user_id: str, plan: str) -> None:
    """Update subscription plan. Same balance-preservation rule as _grant_credits."""
    credits = PLAN_CREDITS.get(plan, 2)
    try:
        from .supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return
        cur = sb.table("profiles").select("credits_balance").eq("id", user_id).single().execute()
        current = (cur.data or {}).get("credits_balance") or 0
        new_balance = max(current, credits)
        sb.table("profiles").update({
            "plan_type":             plan,
            "credits_monthly_quota": credits,
            "credits_balance":       new_balance,
            "credits_used":          0,
        }).eq("id", user_id).execute()
        log.info(
            "Clink updated plan for %s: %s, quota=%d, balance %d→%d",
            user_id, plan, credits, current, new_balance,
        )
    except Exception as exc:
        log.error("Clink _update_user_plan failed user=%s: %s", user_id, exc)
