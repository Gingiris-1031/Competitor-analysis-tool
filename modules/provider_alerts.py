"""Server-side provider credit monitoring and deduplicated owner alerts.

This module deliberately stores only provider status and a short operator-safe
note in the existing service-role-only ``audit_cache`` table. It never stores
keys, raw provider responses, user data, or report URLs.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from html import escape

import httpx

log = logging.getLogger(__name__)

_SOURCE = "provider_alert_state"
_RUN_KEY = "_last_check"
_CHECK_INTERVAL = timedelta(hours=6)
_RENOTIFY_INTERVAL = timedelta(hours=24)
_STATE_TTL_SECONDS = 90 * 24 * 3600
_CRITICAL = {"error", "exhausted", "rate_limited"}
_WARNING = {"low", "unknown"}
# These providers can delay reports, block email delivery, or incur variable
# spend. Optional integrations without a configured key are intentionally not
# emailed, otherwise a first check would create noisy false alarms.
_ALERTED_PROVIDERS = {
    "DataForSEO", "SEOReviewTools", "SerpAPI", "Apify", "Brave Search",
    "TinyFish", "DeepSeek", "OpenRouter", "OrcaRouter", "Resend",
    "TwitterAPI.io",
}
_MEMORY_STATE: dict[str, dict] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _severity(status: str) -> str:
    if status in _CRITICAL:
        return "critical"
    if status in _WARNING:
        return "warning"
    return "healthy"


def _store():
    try:
        from .supabase_client import get_supabase
        return get_supabase()
    except Exception:
        return None


def _read(key: str) -> dict:
    if key in _MEMORY_STATE:
        return _MEMORY_STATE[key]
    sb = _store()
    if not sb:
        return {}
    try:
        rows = sb.table("audit_cache").select("value").eq("source", _SOURCE).eq("cache_key", key).execute().data or []
        return (rows[0].get("value") or {}) if rows else {}
    except Exception as exc:
        log.warning("provider alert state read failed: %s", exc)
        return {}


def _write(key: str, value: dict) -> None:
    _MEMORY_STATE[key] = value
    sb = _store()
    if not sb:
        return
    try:
        now = _now()
        sb.table("audit_cache").upsert({
            "source": _SOURCE,
            "cache_key": key,
            "value": value,
            "fetched_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=_STATE_TTL_SECONDS)).isoformat(),
            "ttl_seconds": _STATE_TTL_SECONDS,
            "hit_count": 0,
        }, on_conflict="source,cache_key").execute()
    except Exception as exc:
        log.warning("provider alert state write failed: %s", exc)


def is_provider_blocked(provider: str) -> bool:
    """Return whether a provider is deliberately disabled or critically sick.

    Reads a tiny in-process cache first and fails open when persistence is down;
    explicit ``<PROVIDER>_ENABLED=false`` remains the reliable emergency brake.
    """
    env_key = provider.upper().replace(" ", "_").replace(".", "") + "_ENABLED"
    if (os.environ.get(env_key) or "true").strip().lower() in {"0", "false", "no", "off"}:
        return True
    return _read(provider).get("severity") == "critical"


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


async def _send_email(alerts: list[dict]) -> bool:
    recipient = (os.environ.get("OPS_ALERT_EMAIL") or "").strip()
    key = (os.environ.get("RESEND_API_KEY") or "").strip()
    if not recipient or not key:
        log.warning("provider alert email skipped: OPS_ALERT_EMAIL or RESEND_API_KEY is not configured")
        return False
    rows = "".join(
        f"<li><strong>{escape(a['provider'])}</strong> — {escape(a['severity'])}: {escape(a['note'])}</li>"
        for a in alerts
    )
    payload = {
        "from": "Analook Ops <iris@mail.analook.com>",
        "to": [recipient],
        "subject": f"[Analook] {len(alerts)} API provider alert(s)",
        "html": (
            "<p>Analook detected a provider credit or authentication issue. "
            "Affected report sources may be skipped until it is resolved.</p>"
            f"<ul>{rows}</ul><p>Open the protected API-balance endpoint for details. "
            "No API keys are included in this email.</p>"
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code in (200, 201):
            return True
        log.warning("provider alert email failed: HTTP %s", response.status_code)
    except Exception as exc:
        log.warning("provider alert email failed: %s", exc)
    return False


async def check_and_alert(*, force: bool = False, dry_run: bool = False) -> dict:
    """Check providers at most every six hours and send deduplicated alerts.

    ``dry_run`` is for protected verification: it calculates what would be
    delivered without contacting Resend or changing notification timestamps.
    """
    now = _now()
    last_run = _parse_time(_read(_RUN_KEY).get("checked_at"))
    if not force and last_run and now - last_run < _CHECK_INTERVAL:
        return {"checked": False, "reason": "throttled", "next_check_after": (last_run + _CHECK_INTERVAL).isoformat()}

    from .api_balances import check_all
    report = await check_all()
    candidates: list[dict] = []
    states: list[dict] = []
    for result in report.get("providers") or []:
        provider = str(result.get("provider") or "unknown")
        severity = _severity(str(result.get("status") or "unknown"))
        note = str(result.get("note") or "").replace("\n", " ")[:240]
        previous = _read(provider)
        last_sent = _parse_time(previous.get("last_sent_at"))
        changed = previous.get("severity") != severity or previous.get("note") != note
        should_send = (
            provider in _ALERTED_PROVIDERS
            and severity != "healthy"
            and (changed or not last_sent or now - last_sent >= _RENOTIFY_INTERVAL)
        )
        state = {"severity": severity, "status": result.get("status"), "note": note, "checked_at": now.isoformat(), "last_sent_at": previous.get("last_sent_at")}
        states.append({"provider": provider, "state": state})
        if should_send:
            candidates.append({"provider": provider, "severity": severity, "note": note})

    delivered = False
    if candidates and not dry_run:
        delivered = await _send_email(candidates)
        if delivered:
            for state in states:
                if any(a["provider"] == state["provider"] for a in candidates):
                    state["state"]["last_sent_at"] = now.isoformat()

    if not dry_run:
        for state in states:
            _write(state["provider"], state["state"])
        _write(_RUN_KEY, {"checked_at": now.isoformat()})

    return {
        "checked": True,
        "dry_run": dry_run,
        "alert_candidates": candidates,
        "email_sent": delivered,
        "summary": report.get("summary") or {},
        "providers": [{"provider": s["provider"], "severity": s["state"]["severity"]} for s in states],
    }
