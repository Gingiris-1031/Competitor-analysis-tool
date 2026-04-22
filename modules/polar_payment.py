"""Polar.sh 支付集成 — Checkout + Webhook + 信用额度管理"""
import os
import base64
import hmac
import hashlib
import time
import httpx
import logging
from collections import OrderedDict
from datetime import datetime

log = logging.getLogger(__name__)

POLAR_API = "https://api.polar.sh/v1"

# In-memory idempotency store (webhook-id -> timestamp). LRU-capped at 2000.
# Polar retries webhooks on failure; Standard Webhooks guarantees unique ids per event.
_seen_events: "OrderedDict[str, float]" = OrderedDict()
_SEEN_MAX = 2000
_SEEN_TTL = 24 * 60 * 60  # 24h — Polar stops retrying well before this


def mark_event_seen(event_id: str) -> bool:
    """Record an event id. Returns True if new, False if already seen (duplicate)."""
    if not event_id:
        return True  # Unidentifiable event — process anyway
    now = time.time()
    # Evict expired
    while _seen_events and (now - next(iter(_seen_events.values()))) > _SEEN_TTL:
        _seen_events.popitem(last=False)
    if event_id in _seen_events:
        return False
    _seen_events[event_id] = now
    while len(_seen_events) > _SEEN_MAX:
        _seen_events.popitem(last=False)
    return True

# Product IDs (configured in Polar dashboard)
PRODUCTS = {
    "pro":           os.environ.get("POLAR_PRODUCT_PRO", "37fdbca9-b47b-4c30-8311-94315877a379"),
    "team":          os.environ.get("POLAR_PRODUCT_TEAM", "e3ceae17-4ac6-4952-b2ff-ac6eebf6b771"),
    "single_report": os.environ.get("POLAR_PRODUCT_SINGLE", "7599d40c-771f-4f3e-8ea7-e053075b95d6"),
}

# Credits per plan
PLAN_CREDITS = {
    "pro": 30,            # 30 reports/month
    "team": 999999,       # unlimited
    "single_report": 1,   # 1 report
    "free": 3,            # 3 reports/month (no payment needed)
}


def _get_token() -> str:
    return os.environ.get("POLAR_ACCESS_TOKEN", "").strip()


async def create_checkout(
    product_key: str,
    user_email: str = "",
    success_url: str = "",
    user_id: str = "",
    cancel_url: str = "",
) -> dict:
    """Create a Polar checkout session. Returns {url, id} or {error}."""
    token = _get_token()
    if not token:
        return {"error": "Polar not configured"}

    product_id = PRODUCTS.get(product_key)
    if not product_id:
        return {"error": f"Unknown product: {product_key}"}

    payload = {
        "product_id": product_id,
    }
    if user_email:
        payload["customer_email"] = user_email
    if success_url:
        payload["success_url"] = success_url
    if cancel_url:
        payload["cancel_url"] = cancel_url
    # Metadata lets us reconcile even if the customer changes email during checkout.
    # Always include product_key so webhook can verify mapping independently.
    metadata = {"product_key": product_key}
    if user_id:
        metadata["user_id"] = user_id
    payload["metadata"] = metadata

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{POLAR_API}/checkouts/",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                return {
                    "url": data.get("url", ""),
                    "id": data.get("id", ""),
                }
            else:
                return {"error": f"Polar HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": f"Polar error: {str(e)[:100]}"}


def verify_webhook_signature(
    payload: bytes,
    headers: dict,
    secret: str,
    tolerance_seconds: int = 5 * 60,
) -> bool:
    """Verify Polar webhook per Standard Webhooks spec (https://standardwebhooks.com).

    Polar sends three headers:
      - webhook-id:        unique message id (also used for idempotency)
      - webhook-timestamp: unix seconds (enforced within ±5min to block replays)
      - webhook-signature: space-separated "v1,<base64(HMAC-SHA256)>" values

    Signed payload = f"{id}.{timestamp}.{body}".
    Secret format is "whsec_<base64>"; we base64-decode after the prefix.
    Headers dict must have lowercase keys.
    """
    if not secret:
        return False
    msg_id = headers.get("webhook-id", "")
    ts = headers.get("webhook-timestamp", "")
    sig_header = headers.get("webhook-signature", "")
    if not (msg_id and ts and sig_header):
        return False
    # Replay protection
    try:
        if abs(time.time() - int(ts)) > tolerance_seconds:
            return False
    except ValueError:
        return False
    # Decode secret (Polar format: "whsec_<base64>")
    if secret.startswith("whsec_"):
        try:
            secret_bytes = base64.b64decode(secret[len("whsec_"):])
        except Exception:
            return False
    else:
        secret_bytes = secret.encode()
    # Compute expected signature
    try:
        signed_payload = f"{msg_id}.{ts}.{payload.decode('utf-8')}".encode("utf-8")
    except UnicodeDecodeError:
        return False
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_payload, hashlib.sha256).digest()
    ).decode()
    # Match any "v1,<sig>" in the header (Polar may rotate keys; header can carry both)
    for sig in sig_header.split():
        if not sig.startswith("v1,"):
            continue
        provided = sig[len("v1,"):]
        if hmac.compare_digest(expected, provided):
            return True
    return False


async def handle_webhook_event(event: dict) -> dict:
    """Process a Polar webhook event. Returns action taken."""
    event_type = event.get("type", "")
    data = event.get("data", {})

    log.info("Polar webhook: %s", event_type)

    if event_type == "checkout.completed":
        return await _handle_checkout_completed(data)
    elif event_type == "subscription.created":
        return await _handle_subscription_created(data)
    elif event_type == "subscription.updated":
        return await _handle_subscription_updated(data)
    elif event_type == "subscription.canceled":
        return await _handle_subscription_canceled(data)
    elif event_type == "order.created":
        return await _handle_order_created(data)
    else:
        return {"action": "ignored", "event_type": event_type}


async def _handle_checkout_completed(data: dict) -> dict:
    """Checkout completed — extract customer info and product."""
    customer_email = data.get("customer_email", "")
    metadata = data.get("metadata", {})
    user_id = metadata.get("user_id", "")
    product_id = ""
    products = data.get("products", [])
    if products:
        product_id = products[0].get("product_id", "")

    plan = _product_id_to_plan(product_id)
    log.info("Checkout completed: email=%s plan=%s user_id=%s", customer_email, plan, user_id)

    if user_id and plan:
        await _grant_credits(user_id, plan)

    return {"action": "checkout_completed", "plan": plan, "email": customer_email}


async def _handle_subscription_created(data: dict) -> dict:
    """New subscription — grant monthly credits."""
    customer_email = data.get("customer", {}).get("email", "")
    product_id = data.get("product_id", "")
    plan = _product_id_to_plan(product_id)

    # Find user by email and grant credits
    user_id = await _find_user_by_email(customer_email)
    if user_id and plan:
        await _update_user_plan(user_id, plan)

    return {"action": "subscription_created", "plan": plan, "email": customer_email}


async def _handle_subscription_updated(data: dict) -> dict:
    """Subscription changed (upgrade/downgrade)."""
    customer_email = data.get("customer", {}).get("email", "")
    product_id = data.get("product_id", "")
    plan = _product_id_to_plan(product_id)

    user_id = await _find_user_by_email(customer_email)
    if user_id and plan:
        await _update_user_plan(user_id, plan)

    return {"action": "subscription_updated", "plan": plan}


async def _handle_subscription_canceled(data: dict) -> dict:
    """Subscription canceled — downgrade to free."""
    customer_email = data.get("customer", {}).get("email", "")

    user_id = await _find_user_by_email(customer_email)
    if user_id:
        await _update_user_plan(user_id, "free")

    return {"action": "subscription_canceled", "email": customer_email}


async def _handle_order_created(data: dict) -> dict:
    """One-time purchase (Single Report) — add 1 credit."""
    customer_email = data.get("customer", {}).get("email", "")
    product_id = data.get("product_id", "")
    plan = _product_id_to_plan(product_id)

    user_id = await _find_user_by_email(customer_email)
    if user_id and plan == "single_report":
        await _grant_credits(user_id, "single_report")

    return {"action": "order_created", "plan": plan, "email": customer_email}


def _product_id_to_plan(product_id: str) -> str:
    """Map Polar product ID to plan name."""
    for plan, pid in PRODUCTS.items():
        if pid == product_id:
            return plan
    return ""


async def _find_user_by_email(email: str) -> str | None:
    """Find Supabase user ID by email."""
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
    except Exception as e:
        log.error("Find user by email failed: %s", e)
    return None


async def _grant_credits(user_id: str, plan: str):
    """Add credits to user based on plan."""
    credits = PLAN_CREDITS.get(plan, 0)
    if not credits:
        return
    try:
        from .supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return
        # For single report: add 1 credit
        # For subscription: set monthly quota
        if plan == "single_report":
            sb.rpc("add_credits", {"p_user_id": user_id, "p_amount": credits}).execute()
        else:
            sb.table("profiles").update({
                "plan_type": plan,
                "credits_monthly_quota": credits,
                "credits_balance": credits,
                "credits_used": 0,
            }).eq("id", user_id).execute()
        log.info("Granted %d credits to user %s (plan=%s)", credits, user_id, plan)
    except Exception as e:
        log.error("Grant credits failed user=%s: %s", user_id, e)


async def _update_user_plan(user_id: str, plan: str):
    """Update user plan type and credits."""
    credits = PLAN_CREDITS.get(plan, 3)
    try:
        from .supabase_client import get_supabase
        sb = get_supabase()
        if not sb:
            return
        sb.table("profiles").update({
            "plan_type": plan,
            "credits_monthly_quota": credits,
            "credits_balance": credits,
            "credits_used": 0,
        }).eq("id", user_id).execute()
        log.info("Updated plan for user %s: %s (%d credits)", user_id, plan, credits)
    except Exception as e:
        log.error("Update plan failed user=%s: %s", user_id, e)
