#!/usr/bin/env python3
"""
EDM #1: 沉睡用户回访（"我们的 bug 吃了你的报告，送 10 credits"）

适用人群：4/3 - 4/27 注册但 0 reports 的 36 个外部用户
目的：用透明 + 补偿换 5-15 个 reactivation + 1-3 个 paid conversion
预期：发 36 封 → 5-8 人回访 → 2 paid

Usage:
    RESEND_API_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
        python scripts/edm/2026_04_reactivation.py --dry-run    # preview emails

    RESEND_API_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
        python scripts/edm/2026_04_reactivation.py --send       # actually send

Prerequisites:
1. Resend account with verified analook.com domain (SPF/DKIM/Return-Path 3 records in Namecheap)
2. RESEND_API_KEY env var (looks like `re_AbCdEf...`)
3. Supabase access (existing env vars OK)

Safety:
- Dry-run mode prints all emails to stdout, never sends
- Excludes Iris's 3 own accounts (hardcoded IRIS_EMAILS list)
- Excludes any user with credits_used > 0 (already activated, no need to apologize)
- Excludes any user already in `email_log` table for this campaign
- Logs every send to `email_log` table for auditability
- Includes List-Unsubscribe header (CAN-SPAM compliance + reduces spam folder risk)
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ── config ────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = "".join(c for c in os.environ.get("SUPABASE_SERVICE_KEY", "") if c.isprintable() and not c.isspace())
RESEND_KEY = "".join(c for c in os.environ.get("RESEND_API_KEY", "") if c.isprintable() and not c.isspace())

if not (SUPABASE_URL and SUPABASE_KEY and RESEND_KEY):
    print("ERROR: need SUPABASE_URL + SUPABASE_SERVICE_KEY + RESEND_API_KEY", file=sys.stderr)
    sys.exit(1)

DRY_RUN = "--dry-run" in sys.argv
SEND = "--send" in sys.argv
if not (DRY_RUN or SEND):
    print("Specify either --dry-run or --send", file=sys.stderr)
    sys.exit(1)

CAMPAIGN_ID = "2026_04_reactivation_supabase_bug"
FROM_ADDR = "Iris <iris@analook.com>"
REPLY_TO = "iris@gingiris.com"

# Iris's own accounts — never email these
IRIS_EMAILS = {
    "iris103195@gmail.com",
    "gingiris1031@gmail.com",
    "iris.wei@gingiris.com",
}

CREDITS_TO_GRANT = 10


# ── helpers ───────────────────────────────────────────────────────────────
def sb_get(path: str) -> list | dict:
    req = urllib.request.Request(
        SUPABASE_URL + path,
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def sb_patch(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        SUPABASE_URL + path,
        method="PATCH",
        data=json.dumps(body).encode(),
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def sb_post(path: str, body: dict | list) -> dict:
    req = urllib.request.Request(
        SUPABASE_URL + path,
        method="POST",
        data=json.dumps(body).encode(),
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def resend_send(email: dict) -> dict:
    """Send via Resend HTTP API."""
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        method="POST",
        data=json.dumps(email).encode(),
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def first_name_from_email(email: str) -> str:
    """Cheap heuristic for first name from email local-part."""
    local = email.split("@")[0]
    # Strip digits and dots — common patterns: "iris103195" → "iris", "iris.wei" → "iris"
    cleaned = "".join(c for c in local if c.isalpha())
    if not cleaned:
        return "there"
    return cleaned[:1].upper() + cleaned[1:].lower()


# ── email template ────────────────────────────────────────────────────────
SUBJECT = "Your Analook report from April was lost — here's 10 credits to retry"

TEXT_TEMPLATE = """Hi {first_name},

I'm Iris, and I built Analook (analook.com) — the competitor analysis tool you signed up for in April 2026.

I owe you a quick honest note.

We had a backend misconfiguration between April 3rd and April 28th: a single environment variable in our Railway deployment had a trailing space in its name (literally one invisible character). Because of that, every analysis our users ran during that window completed successfully and showed you a job_id — but the report itself never persisted to our database. It only lived on Railway's ephemeral disk and got wiped on every redeploy.

The damage report: at least 5 external user reports lost, including yours if you'd run any analysis during that window.

I caught this on April 28th when one of our active users emailed asking where his report had gone. Three weeks too late, in other words.

As compensation: I've added **{credits} free credits** to your Analook account. They don't expire. You can use them to run new analyses anytime — no card required.

If you want to try again, just sign back in: https://www.analook.com

I've also written up the full postmortem and the structural fix we shipped, here:
https://gingiris.github.io/growth-tools/blog/2026/04/29/saas-marketing-on-a-budget/#case-study-analook-0-39-in-4-weeks

Two things I'd love to know (one or both, no obligation):
1. Were you affected? Did you run an analysis during 4/3-4/28 that didn't show up later?
2. What would have made you stay/use Analook more frequently after signing up?

Reply to this email — it goes directly to me (iris@gingiris.com).

— Iris
Founder, Analook
gingiris.com

---
You're receiving this because you registered at analook.com.
Unsubscribe from Analook product updates: {unsub_url}
""".strip()


HTML_TEMPLATE = """<!DOCTYPE html>
<html><body style="font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; color: #1f2937; line-height: 1.6;">
<p>Hi {first_name},</p>

<p>I'm Iris, and I built <a href="https://www.analook.com" style="color:#2563eb">Analook</a> — the competitor analysis tool you signed up for in April 2026.</p>

<p>I owe you a quick honest note.</p>

<p>We had a backend misconfiguration between April 3rd and April 28th: a single environment variable in our Railway deployment had a trailing space in its name (literally one invisible character). Because of that, every analysis our users ran during that window completed successfully and showed you a job_id — but the report itself never persisted to our database. It only lived on Railway's ephemeral disk and got wiped on every redeploy.</p>

<p>The damage report: at least 5 external user reports lost, including yours if you'd run any analysis during that window.</p>

<p>I caught this on April 28th when one of our active users emailed asking where his report had gone. Three weeks too late, in other words.</p>

<p>As compensation: <strong>I've added {credits} free credits to your Analook account.</strong> They don't expire. You can use them to run new analyses anytime — no card required.</p>

<p>If you want to try again, just sign back in: <a href="https://www.analook.com" style="color:#2563eb">https://www.analook.com</a></p>

<p>I've also written up <a href="https://gingiris.github.io/growth-tools/blog/2026/04/29/saas-marketing-on-a-budget/" style="color:#2563eb">the full postmortem and the structural fix we shipped</a>.</p>

<p>Two things I'd love to know (one or both, no obligation):</p>
<ol>
  <li>Were you affected? Did you run an analysis during 4/3-4/28 that didn't show up later?</li>
  <li>What would have made you stay/use Analook more frequently after signing up?</li>
</ol>

<p>Reply to this email — it goes directly to me (iris@gingiris.com).</p>

<p>— Iris<br/>
Founder, Analook<br/>
<a href="https://gingiris.com" style="color:#6b7280;font-size:13px">gingiris.com</a></p>

<hr style="border:0;border-top:1px solid #e5e7eb;margin:32px 0 16px 0">
<p style="font-size:11px;color:#6b7280">You're receiving this because you registered at analook.com. <a href="{unsub_url}" style="color:#6b7280">Unsubscribe</a> from Analook product updates.</p>
</body></html>""".strip()


# ── main flow ─────────────────────────────────────────────────────────────
def main():
    print(f"\n═══ EDM Campaign: {CAMPAIGN_ID} ═══")
    print(f"Mode: {'DRY-RUN (no emails sent)' if DRY_RUN else 'LIVE SEND'}\n")

    # Pull all profiles, filter to "dormant external users"
    profiles = sb_get(
        "/rest/v1/profiles?select=id,email,plan_type,credits_balance,credits_used,credits_monthly_quota,created_at"
    )
    print(f"Total profiles: {len(profiles)}")

    candidates = []
    for p in profiles:
        email = (p.get("email") or "").lower()
        if not email or email in IRIS_EMAILS:
            continue
        if (p.get("credits_used") or 0) > 0:
            continue  # already used the tool — they don't need an "I'm sorry" email
        candidates.append(p)

    print(f"Dormant external candidates: {len(candidates)}\n")

    # Skip those already emailed in this campaign (idempotency)
    try:
        sent_log = sb_get(
            f"/rest/v1/email_log?campaign_id=eq.{CAMPAIGN_ID}&select=user_id"
        )
        already_sent = {row["user_id"] for row in sent_log}
        candidates = [p for p in candidates if p["id"] not in already_sent]
        print(f"Skipping {len(already_sent)} already sent in this campaign.")
    except Exception:
        print("(email_log table missing or empty — proceeding without dedup check)")

    print(f"To send: {len(candidates)}\n")

    if not candidates:
        print("Nothing to do.")
        return

    sent = 0
    failed = []
    for i, p in enumerate(candidates, 1):
        email = p["email"]
        uid = p["id"]
        fn = first_name_from_email(email)
        unsub = f"https://www.analook.com/unsubscribe?u={uid}&c={CAMPAIGN_ID}"

        text_body = TEXT_TEMPLATE.format(first_name=fn, credits=CREDITS_TO_GRANT, unsub_url=unsub)
        html_body = HTML_TEMPLATE.format(first_name=fn, credits=CREDITS_TO_GRANT, unsub_url=unsub)

        payload = {
            "from": FROM_ADDR,
            "to": [email],
            "reply_to": REPLY_TO,
            "subject": SUBJECT,
            "text": text_body,
            "html": html_body,
            "headers": {
                "List-Unsubscribe": f"<{unsub}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
            "tags": [{"name": "campaign", "value": CAMPAIGN_ID}],
        }

        print(f"[{i}/{len(candidates)}] {email} (fn={fn})")

        if DRY_RUN:
            print("   ▸ would send subject:", SUBJECT)
            print("   ▸ first 80 chars of body:", text_body[:80].replace("\n", " "), "...")
            continue

        # LIVE: send + grant credits + log
        try:
            resp = resend_send(payload)
            msg_id = resp.get("id", "?")
            print(f"   ✅ sent (resend id={msg_id})")

            # Grant credits
            sb_patch(
                f"/rest/v1/profiles?id=eq.{uid}",
                {"credits_balance": (p.get("credits_balance") or 0) + CREDITS_TO_GRANT},
            )
            print(f"   ✅ +{CREDITS_TO_GRANT} credits added")

            # Log to email_log table (create row regardless of table existing)
            try:
                sb_post(
                    "/rest/v1/email_log",
                    [{"campaign_id": CAMPAIGN_ID, "user_id": uid, "email": email,
                      "resend_message_id": msg_id, "sent_at": datetime.now(timezone.utc).isoformat()}],
                )
            except Exception as e:
                print(f"   ⚠️  log write failed (table missing?): {e}")

            sent += 1
            # Rate limit: 1 email / 1.5 sec → 24/min, safe under Resend free tier
            time.sleep(1.5)
        except Exception as e:
            print(f"   ❌ failed: {e}")
            failed.append((email, str(e)[:100]))

    # Summary
    print("\n═══ Summary ═══")
    if DRY_RUN:
        print(f"  Would send: {len(candidates)} emails")
        print(f"  Would grant: {len(candidates) * CREDITS_TO_GRANT} total credits")
    else:
        print(f"  Sent: {sent}/{len(candidates)}")
        print(f"  Credits granted: {sent * CREDITS_TO_GRANT}")
        if failed:
            print(f"  Failed: {len(failed)}")
            for email, err in failed[:5]:
                print(f"    - {email}: {err}")


if __name__ == "__main__":
    main()
