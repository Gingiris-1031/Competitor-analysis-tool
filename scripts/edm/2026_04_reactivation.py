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
FROM_ADDR = "Iris from Analook <iris@mail.analook.com>"
REPLY_TO = "iris.wei@gingiris.com"

# Iris's own accounts — never email these
IRIS_EMAILS = {
    "iris103195@gmail.com",
    "gingiris1031@gmail.com",
    "iris.wei@gingiris.com",
}

CREDITS_TO_GRANT = 10


# ── helpers ───────────────────────────────────────────────────────────────
def sb_get(path: str):
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


def sb_post(path: str, body: "dict | list") -> dict:
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
    """Send via Resend HTTP API.

    Resend sits behind Cloudflare which rejects requests with no User-Agent
    (CF error 1010 / "browser integrity check"). urllib does NOT set a
    default UA, so we have to provide one explicitly.
    """
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        method="POST",
        data=json.dumps(email).encode(),
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "analook-edm/1.0 (+https://www.analook.com)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def first_name_from_email(email: str) -> str:
    """Conservative first-name heuristic.

    Takes chars up to the first dot or digit. Falls back to "there" when the
    extracted string is too short (<3) or too long (>8) — long unsegmented
    locals are almost always concatenated Chinese pinyin full names where we
    cannot reliably guess the first name, and "Hi Chenchenzhaoyang" reads
    worse than "Hi there".
    """
    import re
    local = email.split("@")[0].lower()
    m = re.match(r"^([a-z]+)", local)
    if not m:
        return "there"
    name = m.group(1)
    if len(name) < 3 or len(name) > 8:
        return "there"
    return name[:1].upper() + name[1:]


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
https://gingiris.tools/blog/2026/04/29/saas-marketing-on-a-budget/#case-study-analook-0-39-in-4-weeks

Two things I'd love to know (one or both, no obligation):
1. Were you affected? Did you run an analysis during 4/3-4/28 that didn't show up later?
2. What would have made you stay/use Analook more frequently after signing up?

Just hit reply — it lands straight in my inbox.

— Iris
Founder, Analook
gingiris.com

---
You're receiving this because you registered at analook.com.
Unsubscribe from Analook product updates: {unsub_url}
""".strip()


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A note from Iris at Analook</title>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">
<style>
  @media (prefers-color-scheme: dark) {{
    .bg-wrap {{ background:#1a1612 !important; }}
  }}
  @media (max-width:620px) {{
    .card {{ padding:32px 24px !important; }}
    .h1 {{ font-size:28px !important; line-height:1.2 !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:#f3ede0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f1b16;-webkit-font-smoothing:antialiased">
<div class="bg-wrap" style="background:#f3ede0;padding:32px 16px">
<table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" width="600" style="max-width:600px;margin:0 auto;background:#fffdf6;border:1px solid #e8dfca;border-radius:12px;overflow:hidden">

  <!-- top accent stripe -->
  <tr><td style="height:4px;background:linear-gradient(90deg,#b8612d 0%,#d8923f 50%,#b8612d 100%);font-size:0;line-height:0">&nbsp;</td></tr>

  <!-- header -->
  <tr><td style="padding:28px 40px 0 40px">
    <a href="https://www.analook.com" style="text-decoration:none;color:#1f1b16">
      <span style="font-family:'Instrument Serif',Georgia,serif;font-size:24px;font-style:italic;letter-spacing:-0.01em">Analook</span>
      <span style="display:inline-block;margin-left:8px;padding:3px 9px;font-size:11px;text-transform:uppercase;letter-spacing:0.06em;color:#8a6a3a;background:#f5ead4;border-radius:999px;vertical-align:2px">A note from Iris</span>
    </a>
  </td></tr>

  <!-- headline -->
  <tr><td class="card" style="padding:24px 40px 8px 40px">
    <h1 class="h1" style="margin:0;font-family:'Instrument Serif',Georgia,serif;font-size:34px;line-height:1.15;font-weight:400;letter-spacing:-0.015em;color:#1f1b16">
      Hi {first_name} &mdash; <em style="font-style:italic;color:#b8612d">your April report</em><br>
      didn't make it. Here's what happened.
    </h1>
  </td></tr>

  <!-- body -->
  <tr><td class="card" style="padding:20px 40px 8px 40px;font-size:16px;line-height:1.65;color:#2b2522">

    <p style="margin:16px 0">I'm Iris, and I built <a href="https://www.analook.com" style="color:#b8612d;text-decoration:underline">Analook</a> — the competitor analysis tool you signed up for in April 2026.</p>

    <p style="margin:16px 0">I owe you a quick honest note.</p>

    <p style="margin:16px 0">Between April 3 and April 28, a single environment variable in our Railway deployment had a trailing space in its name — one invisible character. Every analysis users ran in that window finished successfully and returned a <code style="background:#f5ead4;padding:2px 6px;border-radius:4px;font-size:14px">job_id</code>, but the report never persisted to our database. It only lived on Railway's ephemeral disk and was wiped on the next redeploy.</p>

    <p style="margin:16px 0"><strong>At least 5 external reports were lost — yours among them if you ran anything that month.</strong></p>

    <p style="margin:16px 0">I caught it on April 28 when an active user emailed asking where his report had gone. Three weeks too late.</p>
  </td></tr>

  <!-- credits callout -->
  <tr><td style="padding:8px 40px">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#f9efd6;border:1px solid #e8d09a;border-radius:10px">
      <tr><td style="padding:20px 24px">
        <div style="font-family:'Instrument Serif',Georgia,serif;font-size:32px;line-height:1;color:#b8612d;font-style:italic;letter-spacing:-0.01em">+{credits} credits</div>
        <div style="margin-top:6px;font-size:14px;color:#6b5a3a">Added to your account. No expiry. No card required.</div>
      </td></tr>
    </table>
  </td></tr>

  <!-- CTA button -->
  <tr><td style="padding:24px 40px 8px 40px">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0">
      <tr><td style="background:#1f1b16;border-radius:8px">
        <a href="https://www.analook.com" style="display:inline-block;padding:14px 28px;font-size:15px;font-weight:600;color:#fffdf6;text-decoration:none;letter-spacing:0.01em">
          Use your credits  &rarr;
        </a>
      </td></tr>
    </table>
    <div style="margin-top:10px;font-size:13px;color:#8a7a5a">Or read <a href="https://gingiris.tools/blog/2026/04/29/saas-marketing-on-a-budget/" style="color:#b8612d">the full postmortem and structural fix</a>.</div>
  </td></tr>

  <!-- two questions -->
  <tr><td class="card" style="padding:24px 40px 0 40px;font-size:16px;line-height:1.65;color:#2b2522">
    <p style="margin:0 0 12px 0;font-weight:600;color:#1f1b16">If you have 30 seconds — two questions, no obligation:</p>
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
      <tr><td style="padding:8px 0;border-top:1px solid #f0e6cf">
        <span style="font-family:'Instrument Serif',Georgia,serif;font-style:italic;color:#b8612d;font-size:18px;margin-right:8px">01</span>
        Were you affected? Did anything you ran during 4/3&ndash;4/28 not show up later?
      </td></tr>
      <tr><td style="padding:8px 0;border-top:1px solid #f0e6cf">
        <span style="font-family:'Instrument Serif',Georgia,serif;font-style:italic;color:#b8612d;font-size:18px;margin-right:8px">02</span>
        What would have made you keep using Analook after signing up?
      </td></tr>
    </table>
    <p style="margin:20px 0 0 0">Just hit reply &mdash; it lands straight in my inbox.</p>
  </td></tr>

  <!-- sign-off -->
  <tr><td class="card" style="padding:8px 40px 0 40px">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#f3ede0;border:1px solid #e8dfca;border-radius:10px">
      <tr><td style="padding:16px 22px;font-size:14px;line-height:1.6;color:#3d3424">
        &#128226; <strong>New: Analook user community on Telegram.</strong>
        Real users sharing audit findings, swapping feedback, getting answers from me directly.
        <a href="https://t.me/analookgroup" style="color:#8a4a1d;text-decoration:underline;font-weight:600" target="_blank">t.me/analookgroup &rarr;</a>
      </td></tr>
    </table>
  </td></tr>

  <tr><td class="card" style="padding:28px 40px 32px 40px">
    <div style="font-family:'Instrument Serif',Georgia,serif;font-size:22px;font-style:italic;color:#1f1b16">— Iris</div>
    <div style="font-size:13px;color:#6b5f4f;margin-top:2px">Founder, Analook &nbsp;·&nbsp; <a href="https://gingiris.com" style="color:#6b5f4f">gingiris.com</a> &nbsp;·&nbsp; ex&#8209;COO, AFFiNE (60K&nbsp;stars)</div>
  </td></tr>

  <!-- footer -->
  <tr><td style="background:#fbf5e6;border-top:1px solid #e8dfca;padding:18px 40px;font-size:11px;line-height:1.6;color:#8a7a5a">
    You're receiving this because you signed up at analook.com.<br>
    <a href="{unsub_url}" style="color:#8a7a5a;text-decoration:underline">Unsubscribe</a> from Analook product updates.
  </td></tr>

</table>
</div>
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
        unsub = f"https://www.analook.com/unsubscribe.html?u={uid}&c={CAMPAIGN_ID}"

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
