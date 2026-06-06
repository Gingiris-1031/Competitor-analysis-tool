#!/usr/bin/env python3
"""
EDM #2: 给已激活外部用户发反馈邮件 + 升级 nudge

适用人群：≥1 report 跑过的外部用户（5/18 baseline 是 20 人）
目的：1) 收集真实反馈 2) 触发 paid conversion
预期：发 20 封 → 8-12 回复 → 2-4 paid

Usage:
    RESEND_API_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
        python scripts/edm/2026_05_activated_feedback.py --dry-run

    RESEND_API_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
        python scripts/edm/2026_05_activated_feedback.py --send
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = "".join(c for c in os.environ.get("SUPABASE_SERVICE_KEY", "") if c.isprintable() and not c.isspace())
RESEND_KEY = "".join(c for c in os.environ.get("RESEND_API_KEY", "") if c.isprintable() and not c.isspace())

if not (SUPABASE_URL and SUPABASE_KEY and RESEND_KEY):
    print("ERROR: need SUPABASE_URL + SUPABASE_SERVICE_KEY + RESEND_API_KEY", file=sys.stderr)
    sys.exit(1)

DRY_RUN = "--dry-run" in sys.argv
SEND = "--send" in sys.argv
if not (DRY_RUN or SEND):
    print("Specify --dry-run or --send", file=sys.stderr)
    sys.exit(1)

CAMPAIGN_ID = "2026_05_activated_feedback"
FROM_ADDR = "Iris from Analook <iris@mail.analook.com>"
REPLY_TO = "iris.wei@gingiris.com"

IRIS_EMAILS = {
    "iris103195@gmail.com",
    "gingiris1031@gmail.com",
    "iris.wei@gingiris.com",
}


def sb_get(path):
    req = urllib.request.Request(SUPABASE_URL + path, headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def sb_post(path, body):
    req = urllib.request.Request(SUPABASE_URL + path, method="POST",
        data=json.dumps(body).encode(),
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                 "Content-Type": "application/json", "Prefer": "return=representation"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def resend_send(email):
    """Resend is behind Cloudflare → urllib without a UA gets CF 1010."""
    req = urllib.request.Request("https://api.resend.com/emails", method="POST",
        data=json.dumps(email).encode(),
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "analook-edm/1.0 (+https://www.analook.com)",
        })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def first_name(email):
    """Conservative: chars-before-first-dot-or-digit; fall back to 'there' if
    too short (<3) or too long (>8). Long unsegmented locals are usually
    concatenated Chinese pinyin; 'Hi there' beats 'Hi Chenchenzhaoyang'."""
    import re
    local = email.split("@")[0].lower()
    m = re.match(r"^([a-z]+)", local)
    if not m:
        return "there"
    name = m.group(1)
    if len(name) < 3 or len(name) > 8:
        return "there"
    return name[:1].upper() + name[1:]


SUBJECT_VARIANTS = [
    "Quick question about your Analook report",
    "How was your Analook experience?",
    "30 seconds — was Analook useful for {target}?",
]


def render_text(fn, report_count, last_url, last_product):
    target_str = last_product or "your competitor" if last_url else "your research"
    return f"""Hi {fn},

I'm Iris, the founder of Analook (analook.com). I noticed you ran {report_count} {'report' if report_count == 1 else 'reports'} this month — most recently on {last_url or 'your target'}.

I'm trying to figure out whether Analook is actually useful, or just a curiosity. Could I ask you two quick questions?

1. What were you trying to figure out about {target_str}? (one sentence is fine)
2. Did Analook help, partially help, or miss the point?

Just hit reply — it lands straight in my inbox, no template.

For context: I'm a solo bootstrapper. The tool you used was built in 4 weekends. Real feedback from real users is the only way I figure out what to build next.

(If you'd like to keep using Analook beyond the free tier, Pro is $29/month for 30 reports — happy to comp you a month if you give me 15 minutes of feedback on a call. Just reply with 3 time slots in your timezone and I'll send a calendar invite.)

— Iris
Founder, Analook
gingiris.com (ex-AFFiNE COO, 60K stars)

---
Unsubscribe: {{unsub}}
""".strip()


def render_html(fn, report_count, last_url, last_product, unsub):
    target_str = (last_product or "your competitor") if last_url else "your research"
    report_word = "report" if report_count == 1 else "reports"
    last_target = last_url or "your target"
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A quick question from Iris at Analook</title>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">
<style>
  @media (prefers-color-scheme: dark) { .bg-wrap { background:#1a1612 !important; } }
  @media (max-width:620px) {
    .card { padding:32px 24px !important; }
    .h1 { font-size:28px !important; line-height:1.2 !important; }
  }
</style>
</head>
<body style="margin:0;padding:0;background:#f3ede0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f1b16;-webkit-font-smoothing:antialiased">
<div class="bg-wrap" style="background:#f3ede0;padding:32px 16px">
<table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" width="600" style="max-width:600px;margin:0 auto;background:#fffdf6;border:1px solid #e8dfca;border-radius:12px;overflow:hidden">

  <tr><td style="height:4px;background:linear-gradient(90deg,#b8612d 0%,#d8923f 50%,#b8612d 100%);font-size:0;line-height:0">&nbsp;</td></tr>

  <tr><td style="padding:28px 40px 0 40px">
    <a href="https://www.analook.com" style="text-decoration:none;color:#1f1b16">
      <span style="font-family:'Instrument Serif',Georgia,serif;font-size:24px;font-style:italic;letter-spacing:-0.01em">Analook</span>
      <span style="display:inline-block;margin-left:8px;padding:3px 9px;font-size:11px;text-transform:uppercase;letter-spacing:0.06em;color:#8a6a3a;background:#f5ead4;border-radius:999px;vertical-align:2px">Founder check-in</span>
    </a>
  </td></tr>

  <tr><td class="card" style="padding:24px 40px 8px 40px">
    <h1 class="h1" style="margin:0;font-family:'Instrument Serif',Georgia,serif;font-size:34px;line-height:1.15;font-weight:400;letter-spacing:-0.015em;color:#1f1b16">
      Hi """ + fn + """ &mdash; <em style="font-style:italic;color:#b8612d">two questions</em>,<br>
      30 seconds, no template.
    </h1>
  </td></tr>

  <tr><td class="card" style="padding:20px 40px 8px 40px;font-size:16px;line-height:1.65;color:#2b2522">
    <p style="margin:16px 0">I'm Iris, the founder of <a href="https://www.analook.com" style="color:#b8612d;text-decoration:underline">Analook</a>. I noticed you ran <strong>""" + str(report_count) + """ """ + report_word + """</strong> this month &mdash; most recently on <code style="background:#f5ead4;padding:2px 6px;border-radius:4px;font-size:14px">""" + last_target + """</code>.</p>

    <p style="margin:16px 0">I'm trying to figure out whether Analook is actually useful, or just a curiosity. Could I ask you:</p>
  </td></tr>

  <tr><td class="card" style="padding:8px 40px 8px 40px">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="font-size:16px;line-height:1.65;color:#2b2522">
      <tr><td style="padding:12px 0;border-top:1px solid #f0e6cf">
        <span style="font-family:'Instrument Serif',Georgia,serif;font-style:italic;color:#b8612d;font-size:18px;margin-right:8px">01</span>
        What were you trying to figure out about """ + target_str + """? <span style="color:#8a7a5a">(one sentence is fine)</span>
      </td></tr>
      <tr><td style="padding:12px 0;border-top:1px solid #f0e6cf;border-bottom:1px solid #f0e6cf">
        <span style="font-family:'Instrument Serif',Georgia,serif;font-style:italic;color:#b8612d;font-size:18px;margin-right:8px">02</span>
        Did Analook help, partially help, or miss the point?
      </td></tr>
    </table>
    <p style="margin:18px 0 0 0;font-size:16px;line-height:1.65;color:#2b2522">Just hit reply &mdash; lands straight in my inbox, no template, no queue.</p>
  </td></tr>

  <tr><td class="card" style="padding:20px 40px 0 40px;font-size:14px;line-height:1.65;color:#6b5f4f">
    <p style="margin:16px 0">For context: I'm a solo bootstrapper. The tool you used was built in 4 weekends. Real feedback from real users is the only way I figure out what to build next.</p>
  </td></tr>

  <!-- Pro plan offer -->
  <tr><td style="padding:8px 40px 8px 40px">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#f9efd6;border:1px solid #e8d09a;border-radius:10px">
      <tr><td style="padding:22px 24px">
        <div style="font-family:'Instrument Serif',Georgia,serif;font-size:22px;line-height:1.2;color:#1f1b16;font-style:italic;letter-spacing:-0.01em">
          One more thing &mdash; <span style="color:#b8612d">a month of Pro on me</span>
        </div>
        <div style="margin-top:10px;font-size:14px;color:#3d3424;line-height:1.6">
          If you'd like to keep using Analook beyond the free tier, Pro is <strong>$29/month</strong> for 30 reports. Happy to <strong>comp you a month</strong> if you give me 15 minutes of feedback on a call.
        </div>
        <div style="margin-top:12px;padding:10px 14px;background:#fffdf6;border:1px dashed #d8b873;border-radius:8px;font-size:13px;color:#3d3424;line-height:1.55">
          &#9656; <strong>Just reply</strong> with 3 time slots in your timezone and I'll send a calendar invite.
        </div>
      </td></tr>
    </table>
  </td></tr>

  <tr><td class="card" style="padding:28px 40px 32px 40px">
    <div style="font-family:'Instrument Serif',Georgia,serif;font-size:22px;font-style:italic;color:#1f1b16">— Iris</div>
    <div style="font-size:13px;color:#6b5f4f;margin-top:2px">Founder, Analook &nbsp;·&nbsp; <a href="https://gingiris.com" style="color:#6b5f4f">gingiris.com</a> &nbsp;·&nbsp; ex&#8209;COO, AFFiNE (60K&nbsp;stars)</div>
  </td></tr>

  <tr><td style="background:#fbf5e6;border-top:1px solid #e8dfca;padding:18px 40px;font-size:11px;line-height:1.6;color:#8a7a5a">
    You're receiving this because you signed up and used Analook.<br>
    <a href=\"""" + unsub + """\" style="color:#8a7a5a;text-decoration:underline">Unsubscribe</a> from Analook product updates.
  </td></tr>

</table>
</div>
</body></html>""".strip()


def main():
    print(f"\n═══ EDM #2: {CAMPAIGN_ID} ═══")
    print(f"Mode: {'DRY-RUN (no emails sent)' if DRY_RUN else 'LIVE SEND'}\n")

    # Pull users
    profiles = sb_get("/rest/v1/profiles?select=id,email,plan_type,credits_balance,credits_used,credits_monthly_quota,created_at")
    reports = sb_get("/rest/v1/reports?select=id,user_id,url,product_name,created_at&order=created_at.desc&limit=500")

    # Build per-user report stats
    from collections import Counter
    rep_count = Counter()
    most_recent = {}  # uid → most recent (url, product_name)
    for r in reports:
        uid = r.get("user_id")
        if not uid:
            continue
        rep_count[uid] += 1
        if uid not in most_recent:
            most_recent[uid] = (r.get("url", ""), r.get("product_name", ""))

    # Candidates: external users with ≥1 report AND not yet paid
    candidates = []
    for p in profiles:
        email = (p.get("email") or "").lower()
        if not email or email in IRIS_EMAILS:
            continue
        if p.get("plan_type") in ("pro", "team"):
            continue  # already paid
        if rep_count.get(p["id"], 0) == 0:
            continue
        candidates.append(p)

    print(f"Activated external candidates (unpaid): {len(candidates)}\n")

    # Skip already sent
    try:
        sent = sb_get(f"/rest/v1/email_log?campaign_id=eq.{CAMPAIGN_ID}&select=user_id")
        already = {row["user_id"] for row in sent}
        candidates = [p for p in candidates if p["id"] not in already]
        print(f"After dedup: {len(candidates)}")
    except Exception:
        print("(email_log dedup unavailable — proceeding)")

    if not candidates:
        print("Nothing to do.")
        return

    sent_count = 0
    failed = []
    for i, p in enumerate(candidates, 1):
        email = p["email"]
        uid = p["id"]
        fn = first_name(email)
        last_url, last_product = most_recent.get(uid, ("", ""))
        rc = rep_count[uid]
        unsub = f"https://www.analook.com/unsubscribe.html?u={uid}&c={CAMPAIGN_ID}"

        # Subject rotation by uid hash (consistent per-user, varied across cohort)
        subj_idx = sum(ord(c) for c in uid) % len(SUBJECT_VARIANTS)
        subject = SUBJECT_VARIANTS[subj_idx].format(target=(last_product or "your target"))

        text = render_text(fn, rc, last_url, last_product).replace("{unsub}", unsub)
        html = render_html(fn, rc, last_url, last_product, unsub)

        payload = {
            "from": FROM_ADDR,
            "to": [email],
            "reply_to": REPLY_TO,
            "subject": subject,
            "text": text,
            "html": html,
            "headers": {
                "List-Unsubscribe": f"<{unsub}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
            "tags": [{"name": "campaign", "value": CAMPAIGN_ID}],
        }

        print(f"[{i}/{len(candidates)}] {email}  ({rc} reports, last={last_url[:30] if last_url else '?'})")
        print(f"   subj: {subject}")

        if DRY_RUN:
            continue

        try:
            resp = resend_send(payload)
            msg_id = resp.get("id", "?")
            print(f"   ✅ sent (resend id={msg_id})")
            try:
                sb_post("/rest/v1/email_log", [{
                    "campaign_id": CAMPAIGN_ID, "user_id": uid, "email": email,
                    "resend_message_id": msg_id,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                }])
            except Exception as e:
                print(f"   ⚠️ log skipped: {e}")
            sent_count += 1
            time.sleep(1.5)
        except Exception as e:
            print(f"   ❌ failed: {e}")
            failed.append((email, str(e)[:100]))

    print("\n═══ Summary ═══")
    if DRY_RUN:
        print(f"  Would send: {len(candidates)} emails")
    else:
        print(f"  Sent: {sent_count}/{len(candidates)}")
        if failed:
            print(f"  Failed: {len(failed)}")
            for e, err in failed[:5]:
                print(f"    - {e}: {err}")


if __name__ == "__main__":
    main()
