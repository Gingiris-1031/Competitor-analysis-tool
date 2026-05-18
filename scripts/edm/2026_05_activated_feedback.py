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
FROM_ADDR = "Iris <iris@analook.com>"
REPLY_TO = "iris@gingiris.com"

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
    req = urllib.request.Request("https://api.resend.com/emails", method="POST",
        data=json.dumps(email).encode(),
        headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def first_name(email):
    local = email.split("@")[0]
    cleaned = "".join(c for c in local if c.isalpha())
    if not cleaned:
        return "there"
    return cleaned[:1].upper() + cleaned[1:].lower()


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

Just reply to this email — it comes directly to me (iris@gingiris.com), no template.

For context: I'm a solo bootstrapper. The tool you used was built in 4 weekends. Real feedback from real users is the only way I figure out what to build next.

(If you'd like to keep using Analook beyond the free tier, the Pro plan is $29/month for 30 reports — happy to comp you a month if you give me 10 minutes of feedback by call. Cal.com link: https://cal.com/iris-gingiris)

— Iris
Founder, Analook
gingiris.com (ex-AFFiNE COO, 60K stars)

---
Unsubscribe: {{unsub}}
""".strip()


def render_html(fn, report_count, last_url, last_product, unsub):
    target_str = (last_product or "your competitor") if last_url else "your research"
    return f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1f2937;line-height:1.6">
<p>Hi {fn},</p>

<p>I'm Iris, the founder of <a href="https://www.analook.com" style="color:#2563eb">Analook</a>. I noticed you ran <strong>{report_count} {'report' if report_count == 1 else 'reports'}</strong> this month — most recently on <code style="background:#f3f4f6;padding:2px 6px;border-radius:4px">{last_url or 'your target'}</code>.</p>

<p>I'm trying to figure out whether Analook is actually useful, or just a curiosity. Could I ask you two quick questions?</p>

<ol>
<li>What were you trying to figure out about {target_str}? (one sentence is fine)</li>
<li>Did Analook help, partially help, or miss the point?</li>
</ol>

<p>Just reply to this email — it comes directly to me (iris@gingiris.com), no template.</p>

<p style="color:#6b7280;font-size:14px">For context: I'm a solo bootstrapper. The tool you used was built in 4 weekends. Real feedback from real users is the only way I figure out what to build next.</p>

<p style="background:#f3f4f6;border-left:3px solid #2563eb;padding:12px 16px;color:#1f2937;font-size:14px">If you'd like to keep using Analook beyond the free tier, the <strong>Pro plan is $29/month</strong> for 30 reports — happy to comp you a month if you give me <strong>10 minutes of feedback by call</strong>. <a href="https://cal.com/iris-gingiris" style="color:#2563eb">Book a slot here</a>.</p>

<p>— Iris<br>
Founder, Analook<br>
<a href="https://gingiris.com" style="color:#6b7280;font-size:13px">gingiris.com (ex-AFFiNE COO, 60K stars)</a></p>

<hr style="border:0;border-top:1px solid #e5e7eb;margin:32px 0 16px 0">
<p style="font-size:11px;color:#6b7280">You're receiving this because you registered and used Analook. <a href="{unsub}" style="color:#6b7280">Unsubscribe</a>.</p>
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
        unsub = f"https://www.analook.com/unsubscribe?u={uid}&c={CAMPAIGN_ID}"

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
