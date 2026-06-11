"""Growth Autopilot — recurring audit + diff + weekly digest pipeline.

A user subscribes a product URL. We periodically (weekly by default) re-run
the existing growth_audit pipeline, snapshot the result, diff against the
previous snapshot, and email a digest of "what got resolved / what's new /
what's still open." Over time the user sees compounding progress they can
brag about — and is much less likely to churn.

Phase 1 scope (this file):
- DB CRUD: subscriptions / snapshots / diffs / digests (via supabase-py).
- run_one_subscription(): the worker entry-point — re-audits, snapshots,
  diffs, returns the diff. (Email send is wired in app.py so it can use
  the same Resend client as the EDM scripts.)
- pick_due(): the cron loop's "what should we run now" query.
- pause_on_failure(): auto-pause after N consecutive failures.

Phase 2 (not in this file):
- LLM "weekly summary" prose for the email body — wires via TeamoRouter.
- Email digest HTML using the same cream brand as growth-audit.
- Real cron worker (Fly machine cron or GitHub Action).
- Polar "$49 Autopilot" product gating.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

log = logging.getLogger(__name__)

# Frequency → next-run delta. Worker can override via subscription row.
FREQUENCY_DELTA = {
    "daily":   timedelta(days=1),
    "weekly":  timedelta(days=7),
    "monthly": timedelta(days=30),
}

# A subscription whose audit fails this many times in a row gets auto-paused.
# The user can re-activate from the dashboard.
MAX_CONSECUTIVE_FAILURES = 3

# Plan-tier caps. We charge by tier; this enforces the limits server-side
# so a Free user can't add 50 subscriptions.
TIER_LIMITS = {
    "free":     {"max_subscriptions": 0, "max_competitors": 0, "min_frequency": "monthly"},
    "pro":      {"max_subscriptions": 3, "max_competitors": 3, "min_frequency": "weekly"},
    "autopilot":{"max_subscriptions": 10,"max_competitors": 10,"min_frequency": "weekly"},
    "team":     {"max_subscriptions": 30,"max_competitors": 20,"min_frequency": "daily"},
}


# ─── DB layer (uses the existing supabase_client) ────────────────────────────


def _sb():
    """Return the Supabase service-role client. Bypasses RLS — only call
    from server-side code that has already authenticated the user via JWT.
    """
    from .supabase_client import get_supabase
    return get_supabase()


def create_subscription(
    user_id: str,
    target_url: str,
    *,
    product_name: Optional[str] = None,
    frequency: str = "weekly",
    competitor_urls: Optional[list] = None,
) -> dict:
    """Create a new tracking subscription. Returns the inserted row.

    Raises ValueError if the user already tracks this URL or has hit their
    tier cap.
    """
    sb = _sb()
    if not sb:
        raise RuntimeError("Supabase client not configured")

    # Enforce tier cap.
    plan = _user_plan(user_id)
    cap = TIER_LIMITS.get(plan, TIER_LIMITS["free"])
    existing = sb.table("autopilot_subscriptions").select("id").eq(
        "user_id", user_id
    ).neq("status", "cancelled").execute()
    n_existing = len(existing.data or [])
    if n_existing >= cap["max_subscriptions"]:
        raise ValueError(
            f"Plan '{plan}' allows {cap['max_subscriptions']} active subscriptions; "
            f"upgrade to add more."
        )

    competitor_urls = competitor_urls or []
    if len(competitor_urls) > cap["max_competitors"]:
        raise ValueError(
            f"Plan '{plan}' allows {cap['max_competitors']} competitor URLs per subscription."
        )

    target_url = _normalize_url(target_url)
    competitor_urls = [_normalize_url(u) for u in competitor_urls]

    try:
        row = sb.table("autopilot_subscriptions").insert({
            "user_id":         user_id,
            "target_url":      target_url,
            "product_name":    product_name,
            "frequency":       frequency,
            "competitor_urls": competitor_urls,
            # Run the first audit ~now so the user gets immediate value.
            "next_run_at":     (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        }).execute()
        return row.data[0] if row.data else {}
    except Exception as e:
        # uniq violation → user already subscribed to same URL
        msg = str(e).lower()
        if "duplicate" in msg or "unique" in msg:
            raise ValueError("You already track this product.")
        raise


def list_user_subscriptions(user_id: str) -> list:
    sb = _sb()
    if not sb:
        return []
    rows = sb.table("autopilot_subscriptions").select(
        "*"
    ).eq("user_id", user_id).order(
        "created_at", desc=True
    ).execute()
    return rows.data or []


def update_subscription(user_id: str, sub_id: str, patch: dict) -> Optional[dict]:
    """Update a subscription. Only allows whitelisted fields and only if
    the subscription belongs to user_id (RLS would also catch this — defense
    in depth)."""
    ALLOWED = {"product_name", "frequency", "competitor_urls", "status"}
    clean = {k: v for k, v in patch.items() if k in ALLOWED}
    if not clean:
        return None
    sb = _sb()
    rows = sb.table("autopilot_subscriptions").update(clean).eq(
        "id", sub_id
    ).eq("user_id", user_id).execute()
    return (rows.data or [None])[0]


def cancel_subscription(user_id: str, sub_id: str) -> bool:
    sb = _sb()
    res = sb.table("autopilot_subscriptions").update({
        "status": "cancelled",
    }).eq("id", sub_id).eq("user_id", user_id).execute()
    return bool(res.data)


# ─── Snapshot + diff ─────────────────────────────────────────────────────────


def insert_snapshot(
    subscription_id: str,
    audit_job_id: str,
    site_data: dict,
    findings: list,
    metrics: Optional[dict] = None,
) -> dict:
    sb = _sb()
    row = sb.table("autopilot_snapshots").insert({
        "subscription_id": subscription_id,
        "audit_job_id":    audit_job_id,
        "site_data":       _slim_site_data(site_data),
        "findings":        findings or [],
        "metrics":         metrics or {},
    }).execute()
    return row.data[0] if row.data else {}


def latest_two_snapshots(subscription_id: str) -> list:
    """Return up to 2 most recent snapshots [latest, second-latest]."""
    sb = _sb()
    rows = sb.table("autopilot_snapshots").select(
        "*"
    ).eq("subscription_id", subscription_id).order(
        "created_at", desc=True
    ).limit(2).execute()
    return rows.data or []


def diff_snapshots(prev: Optional[dict], curr: dict) -> dict:
    """Compute resolved / new / persistent findings between two snapshots.

    Each finding is identified by (category, title). When prev is None
    (very first audit), every finding in curr is "new" and we have nothing
    resolved.
    """
    curr_findings = curr.get("findings") or []
    if not prev:
        return {
            "resolved": [],
            "new":      curr_findings,
            "persistent": [],
            "progress_score": 0,
        }
    prev_findings = prev.get("findings") or []

    def key(f):
        return (
            (f.get("category") or "general").lower(),
            (f.get("title") or "").strip().lower()[:80],
        )

    prev_map = {key(f): f for f in prev_findings if f.get("title")}
    curr_map = {key(f): f for f in curr_findings if f.get("title")}

    resolved = [f for k, f in prev_map.items() if k not in curr_map]
    new      = [f for k, f in curr_map.items() if k not in prev_map]
    persistent = [f for k, f in curr_map.items() if k in prev_map]

    return {
        "resolved":         resolved,
        "new":              new,
        "persistent":       persistent,
        "progress_score":   len(resolved) - len(new),
    }


def insert_diff(
    subscription_id: str,
    prev_snapshot_id: Optional[str],
    curr_snapshot_id: str,
    diff: dict,
    summary_md: Optional[str] = None,
) -> dict:
    sb = _sb()
    row = sb.table("autopilot_diffs").insert({
        "subscription_id":     subscription_id,
        "prev_snapshot_id":    prev_snapshot_id,
        "curr_snapshot_id":    curr_snapshot_id,
        "resolved_findings":   diff.get("resolved", []),
        "new_findings":        diff.get("new", []),
        "persistent_findings": diff.get("persistent", []),
        "progress_score":      diff.get("progress_score", 0),
        "summary_md":          summary_md,
    }).execute()
    return row.data[0] if row.data else {}


# ─── Finding extraction from a Diagnosis markdown ─────────────────────────────


# Match "### 任务 1.1: 修复 robots.txt" / "### 1. 标题" / "## 问题 1: xxx".
_FINDING_HEADER_RE = re.compile(
    r"^(?:#{2,4})\s*"                    # markdown heading
    r"(?:[\d\.　]+\s*[:：、. ]?\s*)?"   # optional numbering
    r"(?:任务|问题|Issue|Task|Finding)?\s*"      # optional category prefix
    r"(?:[\d\.]+\s*[:：、. ]?\s*)?"
    r"(.+?)\s*$",
    flags=re.MULTILINE,
)


def extract_findings_from_diagnosis(md: str) -> list:
    """Pull a list of {category, title, severity?} from a Diagnosis report.

    Heuristic — we look for headings under sections like "三个最严重的问题"
    or "Quick wins" or "## 5. 增长策略推荐". Severity is parsed from
    🔴/🟡/🟢 emoji if present.
    """
    if not md:
        return []

    findings: list[dict] = []
    seen_keys: set[tuple] = set()

    # Section-based extraction: pull bullets under "增长策略推荐" / "三个最严重"
    section_patterns = [
        (r"##[^\n]*?(?:三个最严重的问题|核心问题|关键问题|Top \d+ issues?)", "critical"),
        (r"##[^\n]*?(?:增长策略推荐|Quick win|快速赢面|P0|P1|P2)", "strategy"),
        (r"##[^\n]*?(?:渠道.{0,5}缺口|渠道现状|Channel gap)", "channel"),
        (r"##[^\n]*?(?:SEO/?GEO|Schema)", "seo"),
    ]
    for section_re, category in section_patterns:
        for m in re.finditer(section_re + r"[\s\S]*?(?=^##\s|\Z)", md, re.MULTILINE):
            block = m.group(0)
            for h in _FINDING_HEADER_RE.finditer(block):
                title = h.group(1).strip().rstrip("（(:：")
                if len(title) < 6 or len(title) > 200:
                    continue
                sev = "high" if "🔴" in block[h.start():h.end()+80] else (
                    "low" if "🟢" in block[h.start():h.end()+80] else "medium"
                )
                k = (category, title.lower()[:80])
                if k in seen_keys:
                    continue
                seen_keys.add(k)
                findings.append({
                    "category": category,
                    "title":    title[:200],
                    "severity": sev,
                })
    return findings[:30]  # cap so a noisy report doesn't blow up


# ─── Cron entry point ────────────────────────────────────────────────────────


def pick_due(limit: int = 20) -> list:
    """Return up to N subscriptions due to run. Cron loops over this list.

    Skips paused/cancelled, sorts by next_run_at ascending so the oldest
    waiting subscription runs first.
    """
    sb = _sb()
    if not sb:
        return []
    now = datetime.now(timezone.utc).isoformat()
    rows = sb.table("autopilot_subscriptions").select("*").eq(
        "status", "active"
    ).lte("next_run_at", now).order(
        "next_run_at", desc=False
    ).limit(limit).execute()
    return rows.data or []


def reschedule(subscription_id: str, frequency: str, ok: bool) -> None:
    """After a worker run, set next_run_at + bump failure counter."""
    sb = _sb()
    delta = FREQUENCY_DELTA.get(frequency, FREQUENCY_DELTA["weekly"])
    patch: dict[str, Any] = {
        "last_run_at":  datetime.now(timezone.utc).isoformat(),
        "next_run_at":  (datetime.now(timezone.utc) + delta).isoformat(),
    }
    if ok:
        patch["consecutive_failures"] = 0
    else:
        # Read current count, increment, optionally auto-pause.
        cur = sb.table("autopilot_subscriptions").select(
            "consecutive_failures"
        ).eq("id", subscription_id).execute()
        prev_count = (cur.data or [{}])[0].get("consecutive_failures", 0) or 0
        new_count = prev_count + 1
        patch["consecutive_failures"] = new_count
        if new_count >= MAX_CONSECUTIVE_FAILURES:
            patch["status"] = "paused"
            log.warning("Autopilot sub %s auto-paused after %d failures",
                        subscription_id, new_count)
    sb.table("autopilot_subscriptions").update(patch).eq(
        "id", subscription_id
    ).execute()


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    # Strip trailing slash so per-user uniqueness doesn't break on '/' vs '' .
    url = url.rstrip("/")
    return url


def _user_plan(user_id: str) -> str:
    sb = _sb()
    if not sb:
        return "free"
    row = sb.table("profiles").select("plan_type").eq("id", user_id).execute()
    return (row.data or [{}])[0].get("plan_type") or "free"


def _slim_site_data(site_data: dict) -> dict:
    """Strip raw HTML / large texts so a year of snapshots doesn't bloat
    the table. Keep just the diff-relevant fields."""
    hp = site_data.get("homepage") or {}
    out = {
        "url":    site_data.get("url"),
        "domain": site_data.get("domain"),
        "homepage": {
            "title":       hp.get("title"),
            "description": hp.get("description"),
            # Cap homepage text to 3000 chars so we can still diff hero copy.
            "text":        (hp.get("text") or "")[:3000],
            "links":       (hp.get("links") or [])[:30],
        },
        "robots_txt":   site_data.get("robots_txt"),
        "has_pricing":  bool(site_data.get("pricing_page")),
        "has_sitemap":  bool(site_data.get("sitemap")),
    }
    if isinstance(site_data.get("pricing_page"), dict):
        out["pricing_page"] = {
            "title": site_data["pricing_page"].get("title"),
            "text":  (site_data["pricing_page"].get("text") or "")[:2500],
        }
    return out
