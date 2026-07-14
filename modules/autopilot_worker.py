"""Autopilot Phase 2 — worker that ticks due subscriptions.

Pipeline per due subscription:
  1. run_growth_audit(target_url)
  2. extract findings → insert snapshot
  3. diff against previous snapshot
  4. LLM weekly-summary prose (DeepSeek; OpenRouter fallback)
  5. send digest email via Resend
  6. reschedule next_run_at + reset/inc failure counter

Entry points:
  - tick_due(limit) — runs at most N due subs sequentially. Returns a
    summary dict {ran, ok, failed, paused, details:[...]}.
  - run_one(sub) — single subscription, exposed for retries.

Called from:
  - POST /api/admin/autopilot/tick (header X-Autopilot-Tick-Token must match
    env AUTOPILOT_TICK_TOKEN) — cron hits this.
  - GitHub Action (.github/workflows/autopilot-tick.yml) — hourly schedule.

Why we don't use Fly cron: Fly's scheduled machines are still beta and don't
play well with our single-machine app. A GitHub Action hitting an HTTP
endpoint costs nothing and survives Fly redeploys.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from . import autopilot as ap

log = logging.getLogger(__name__)


# ─── LLM (DeepSeek primary, OpenRouter fallback) ─────────────────────────────


async def _weekly_summary_prose(product_name: str, diff: dict, target_url: str) -> str:
    """Generate the human-readable digest body. Keep it short — this lives in
    an email preview pane so the first 200 chars matter most.

    Falls back to a deterministic template if both LLMs fail.
    """
    resolved = diff.get("resolved") or []
    new = diff.get("new") or []
    persistent = diff.get("persistent") or []
    score = diff.get("progress_score", 0)

    facts = (
        f"Product: {product_name} ({target_url})\n"
        f"Resolved this period: {len(resolved)} — "
        f"{', '.join(f.get('title','?') for f in resolved[:5]) or '(none)'}\n"
        f"New issues: {len(new)} — "
        f"{', '.join(f.get('title','?') for f in new[:5]) or '(none)'}\n"
        f"Persistent issues: {len(persistent)} — "
        f"{', '.join(f.get('title','?') for f in persistent[:5]) or '(none)'}\n"
        f"Net progress score: {score}\n"
    )

    prompt = (
        "You are writing a 5-sentence weekly progress recap for a SaaS founder "
        "tracking their product's growth health. Voice: warm, specific, no marketing fluff. "
        "Start with whichever signal matters most (a resolution win, a new urgent issue, "
        "or steady progress). Mention 1-2 concrete items by name. End with one suggestion "
        "for next week's focus. No emojis. No 'Hi {name}'. No greeting. Markdown allowed.\n\n"
        f"DATA:\n{facts}\n\nWRITE THE RECAP:"
    )

    # Same resilient 0→A→B→C chain as growth_audit._call_llm_long: OrcaRouter
    # free → OpenRouter deepseek-v4-flash → DeepSeek direct → OpenRouter Claude.
    # Deterministic template below is the ultimate fallback if all are unreachable.
    from .orcarouter import try_orca
    orca = await try_orca([{"role": "user", "content": prompt}],
                          max_tokens=400, temperature=0.4, title="Analook Autopilot")
    text = (
        (orca or {}).get("content")
        or await _try_openrouter(prompt, "deepseek/deepseek-v4-flash")
        or await _try_deepseek(prompt)
        or await _try_openrouter(prompt, "anthropic/claude-sonnet-4")
    )
    if text:
        return text.strip()

    # Deterministic fallback.
    if not resolved and not new:
        return (
            f"No structural changes detected for **{product_name}** this period — "
            f"{len(persistent)} previously-open items still need attention. "
            f"Recommend a focused sprint on the top persistent issue next week."
        )
    parts = []
    if resolved:
        parts.append(
            f"**{len(resolved)} resolved** — including \"{resolved[0].get('title','?')}\"."
        )
    if new:
        parts.append(
            f"**{len(new)} new** — most urgent: \"{new[0].get('title','?')}\"."
        )
    parts.append(f"Net progress score: **{score}**.")
    return " ".join(parts)


# Fast-failover timeout: ~10s connect (dead provider → next path fast),
# generous read for the short generation. One attempt per provider.
_LLM_TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0)


def _final_content(data: dict) -> Optional[str]:
    """Read ONLY the answer text — never DeepSeek V4's reasoning_content."""
    msg = ((data.get("choices") or [{}])[0] or {}).get("message", {}) or {}
    return msg.get("content") or None


async def _try_deepseek(prompt: str) -> Optional[str]:
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return None
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as c:
            r = await c.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 400,
                },
            )
            if r.status_code != 200:
                log.warning("deepseek weekly-summary http %s: %s", r.status_code, r.text[:200])
                return None
            return _final_content(r.json())
    except Exception as e:
        log.warning("deepseek weekly-summary error: %s", e)
        return None


async def _try_openrouter(prompt: str, model: str = "deepseek/deepseek-v4-flash") -> Optional[str]:
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as c:
            r = await c.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                         "HTTP-Referer": "https://www.analook.com", "X-Title": "Analook Autopilot"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 400,
                },
            )
            if r.status_code != 200:
                return None
            return _final_content(r.json())
    except Exception:
        return None


# ─── Email digest (cream-on-dark brand, matches EDM voice) ───────────────────


_EMAIL_FROM = "Iris from Analook <iris@gingiris.com>"


def _findings_list_html(items: list, color: str, empty_label: str) -> str:
    if not items:
        return f'<li style="color:#A1A1A0;font-style:italic">{empty_label}</li>'
    rows = []
    for f in items[:6]:
        title = (f.get("title") or "Untitled").replace("<", "&lt;")
        cat = (f.get("category") or "general").replace("<", "&lt;")
        rows.append(
            f'<li style="color:#D1D5DB;margin-bottom:6px">'
            f'<span style="color:{color};font-weight:600">{cat}</span> · {title}'
            f'</li>'
        )
    if len(items) > 6:
        rows.append(f'<li style="color:#6B6864">… +{len(items)-6} more</li>')
    return "\n".join(rows)


def _digest_html(
    *,
    product_name: str,
    target_url: str,
    summary_md: str,
    diff: dict,
    sub_id: str,
    audit_share_url: Optional[str] = None,
) -> str:
    # Minimal markdown→HTML for the summary (bold + paragraph break).
    summary_html = (
        summary_md
        .replace("**", "###BOLD###")
        .replace("\n\n", "</p><p>")
    )
    parts = summary_html.split("###BOLD###")
    bolded = ""
    for i, p in enumerate(parts):
        if i % 2 == 1:
            bolded += f'<strong style="color:#F5F1EB">{p}</strong>'
        else:
            bolded += p
    summary_html = f"<p>{bolded}</p>"

    cta_html = ""
    if audit_share_url:
        cta_html = (
            f'<a href="{audit_share_url}" '
            f'style="display:inline-block;background:#F5F1EB;color:#0A0A0A;'
            f'padding:10px 22px;border-radius:9999px;text-decoration:none;'
            f'font-weight:600;font-size:14px;margin-top:12px">View full report →</a>'
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Weekly Autopilot — {product_name}</title></head>
<body style="margin:0;padding:0;background:#0A0A0A;font-family:-apple-system,Inter,sans-serif;color:#F5F1EB">
<div style="max-width:560px;margin:0 auto;padding:32px 24px">
  <div style="height:3px;background:linear-gradient(90deg,#FB923C,#EC4899,#F59E0B);border-radius:2px;margin-bottom:28px"></div>
  <p style="font-family:Georgia,serif;font-style:italic;font-size:28px;color:#F5F1EB;margin:0 0 6px 0">
    Weekly Autopilot
  </p>
  <p style="color:#A1A1A0;font-size:13px;margin:0 0 28px 0">
    {product_name} · <a href="{target_url}" style="color:#A1A1A0">{target_url}</a>
  </p>

  <div style="background:#141414;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:20px;margin-bottom:18px">
    <p style="font-size:11px;letter-spacing:0.15em;color:#FB923C;text-transform:uppercase;margin:0 0 10px 0">
      This week's recap
    </p>
    <div style="font-size:15px;line-height:1.7;color:#D1D5DB">
      {summary_html}
    </div>
    {cta_html}
  </div>

  <div style="display:flex;gap:12px;margin-bottom:18px">
    <div style="flex:1;background:#141414;border:1px solid rgba(34,197,94,0.25);border-radius:10px;padding:14px;text-align:center">
      <div style="font-size:24px;color:#22C55E;font-weight:700">{len(diff.get('resolved') or [])}</div>
      <div style="font-size:11px;color:#A1A1A0;text-transform:uppercase;letter-spacing:0.1em">Resolved</div>
    </div>
    <div style="flex:1;background:#141414;border:1px solid rgba(239,68,68,0.25);border-radius:10px;padding:14px;text-align:center">
      <div style="font-size:24px;color:#EF4444;font-weight:700">{len(diff.get('new') or [])}</div>
      <div style="font-size:11px;color:#A1A1A0;text-transform:uppercase;letter-spacing:0.1em">New</div>
    </div>
    <div style="flex:1;background:#141414;border:1px solid rgba(251,146,60,0.25);border-radius:10px;padding:14px;text-align:center">
      <div style="font-size:24px;color:#FB923C;font-weight:700">{len(diff.get('persistent') or [])}</div>
      <div style="font-size:11px;color:#A1A1A0;text-transform:uppercase;letter-spacing:0.1em">Open</div>
    </div>
  </div>

  <div style="background:#141414;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:20px;margin-bottom:14px">
    <p style="font-size:11px;letter-spacing:0.15em;color:#22C55E;text-transform:uppercase;margin:0 0 10px 0">✓ Resolved this period</p>
    <ul style="margin:0;padding-left:18px;font-size:14px;line-height:1.6">
      {_findings_list_html(diff.get('resolved') or [], '#22C55E', 'Nothing resolved yet.')}
    </ul>
  </div>

  <div style="background:#141414;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:20px;margin-bottom:14px">
    <p style="font-size:11px;letter-spacing:0.15em;color:#EF4444;text-transform:uppercase;margin:0 0 10px 0">⚠ New this period</p>
    <ul style="margin:0;padding-left:18px;font-size:14px;line-height:1.6">
      {_findings_list_html(diff.get('new') or [], '#EF4444', 'No new issues — clean week.')}
    </ul>
  </div>

  <div style="background:#141414;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:20px;margin-bottom:24px">
    <p style="font-size:11px;letter-spacing:0.15em;color:#FB923C;text-transform:uppercase;margin:0 0 10px 0">↻ Still open</p>
    <ul style="margin:0;padding-left:18px;font-size:14px;line-height:1.6">
      {_findings_list_html(diff.get('persistent') or [], '#FB923C', 'Nothing carried over.')}
    </ul>
  </div>

  <p style="font-size:12px;color:#6B6864;text-align:center;margin:28px 0 8px 0;line-height:1.7">
    You're receiving this because you subscribed to Autopilot tracking for {product_name}.<br>
    <a href="https://www.analook.com/autopilot" style="color:#A1A1A0">Manage subscriptions</a> ·
    <a href="https://www.analook.com/autopilot?unsub={sub_id}" style="color:#A1A1A0">Unsubscribe</a>
  </p>
  <p style="font-size:11px;color:#6B6864;text-align:center;margin:0">— Iris @ Analook</p>
</div>
</body></html>"""


async def _send_digest_email(
    *,
    to_email: str,
    subject: str,
    html: str,
) -> Optional[str]:
    """Send via Resend. Returns Resend message id on success, None on failure."""
    key = (os.environ.get("RESEND_API_KEY") or "").strip()
    if not key:
        log.warning("RESEND_API_KEY not set — autopilot digest skipped")
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from":    _EMAIL_FROM,
                    "to":      [to_email],
                    "subject": subject,
                    "html":    html,
                    "tags":    [{"name": "campaign", "value": "autopilot_weekly"}],
                },
            )
            if r.status_code not in (200, 201):
                log.warning("Resend autopilot http %s: %s", r.status_code, r.text[:200])
                return None
            return (r.json() or {}).get("id")
    except Exception as e:
        log.warning("Resend autopilot error: %s", e)
        return None


# ─── Worker ──────────────────────────────────────────────────────────────────


async def run_one(sub: dict) -> dict:
    """Process one due subscription. Returns a {ok, sub_id, …} result.

    Does NOT raise — it converts exceptions into ok=False so the cron loop
    can keep going through the rest of the batch.
    """
    sub_id = sub.get("id")
    user_id = sub.get("user_id")
    target_url = sub.get("target_url")
    product_name = sub.get("product_name") or (target_url or "").split("/")[-1] or "your product"
    frequency = sub.get("frequency") or "weekly"

    if not target_url:
        return {"ok": False, "sub_id": sub_id, "error": "no_target_url"}

    log.info("autopilot run_one: %s %s", sub_id, target_url)
    try:
        from .growth_audit import run_growth_audit
        # Use a unique job_id so the dashboard doesn't trample regular audits.
        job_id = f"ap-{sub_id[:8]}-{int(datetime.now(timezone.utc).timestamp())}"
        result = await run_growth_audit(
            target_url, product_name=product_name, job_id=job_id, jobs_dict=None,
        )

        if result.get("error"):
            ap.reschedule(sub_id, frequency, ok=False)
            return {"ok": False, "sub_id": sub_id, "error": result["error"]}

        diagnosis_md = result.get("diagnosis_report") or ""
        findings = ap.extract_findings_from_diagnosis(diagnosis_md)

        snapshot = ap.insert_snapshot(
            sub_id, job_id,
            site_data=result.get("site_data") or {},
            findings=findings,
            metrics={
                "report_word_count": len(diagnosis_md),
                "sources":           result.get("sources"),
            },
        )

        # Diff against most recent prior snapshot (latest_two returns
        # newest-first; this insert is now element 0).
        recent = ap.latest_two_snapshots(sub_id)
        prev = recent[1] if len(recent) >= 2 else None
        diff = ap.diff_snapshots(prev, snapshot)

        summary_md = await _weekly_summary_prose(product_name, diff, target_url)

        ap.insert_diff(
            sub_id,
            prev_snapshot_id=(prev or {}).get("id"),
            curr_snapshot_id=snapshot.get("id"),
            diff=diff,
            summary_md=summary_md,
        )

        # Look up the user email for the digest.
        email = _user_email(user_id)
        sent_id = None
        if email:
            subject_emoji = "✓" if diff.get("progress_score", 0) >= 0 else "⚠"
            n_resolved = len(diff.get("resolved") or [])
            n_new = len(diff.get("new") or [])
            subject = (
                f"{subject_emoji} {product_name} weekly — "
                f"{n_resolved} resolved, {n_new} new"
            )
            audit_share_url = f"https://www.analook.com/share/audit/{job_id}"
            html = _digest_html(
                product_name=product_name,
                target_url=target_url,
                summary_md=summary_md,
                diff=diff,
                sub_id=sub_id,
                audit_share_url=audit_share_url,
            )
            sent_id = await _send_digest_email(
                to_email=email, subject=subject, html=html,
            )

        ap.reschedule(sub_id, frequency, ok=True)
        return {
            "ok":          True,
            "sub_id":      sub_id,
            "snapshot_id": snapshot.get("id"),
            "resolved":    len(diff.get("resolved") or []),
            "new":         len(diff.get("new") or []),
            "persistent":  len(diff.get("persistent") or []),
            "email_sent":  bool(sent_id),
            "email_id":    sent_id,
        }
    except Exception as e:
        log.exception("autopilot run_one error %s: %s", sub_id, e)
        try:
            ap.reschedule(sub_id, frequency, ok=False)
        except Exception:
            pass
        return {"ok": False, "sub_id": sub_id, "error": str(e)[:200]}


async def tick_due(limit: int = 10) -> dict:
    """Pop the N most-overdue subscriptions and process them sequentially.

    We don't parallelize because each audit hits DataForSEO / TinyFish /
    DeepSeek and we don't want a 10× spike on those APIs. With weekly
    frequency and (current) <50 active subs, sequential at hourly cron
    handles ~240/day worst case — plenty of headroom.
    """
    due = ap.pick_due(limit=limit)
    out = {"ran": 0, "ok": 0, "failed": 0, "details": []}
    for sub in due:
        res = await run_one(sub)
        out["ran"] += 1
        out["ok" if res.get("ok") else "failed"] += 1
        out["details"].append(res)
        # Tiny breather so a burst of audits doesn't slam the LLM at once.
        await asyncio.sleep(2)
    return out


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _user_email(user_id: str) -> Optional[str]:
    """Look up the email for a Supabase auth user. Goes through auth.users
    rather than profiles because profiles row may not have email synced."""
    sb = ap._sb()
    if not sb or not user_id:
        return None
    try:
        # supabase-py's admin API exposes get_user_by_id on the auth namespace.
        u = sb.auth.admin.get_user_by_id(user_id)
        email = getattr(getattr(u, "user", None), "email", None)
        if email:
            return email
    except Exception:
        pass
    try:
        row = sb.table("profiles").select("email").eq("id", user_id).execute()
        return (row.data or [{}])[0].get("email")
    except Exception:
        return None
