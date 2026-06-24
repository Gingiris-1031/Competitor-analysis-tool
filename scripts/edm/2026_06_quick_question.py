#!/usr/bin/env python3
"""
EDM #4: Reply-only ask — plain text, single question, looks hand-typed.

Why this exists:
  Iris's 6/18 EDM (`2026_06_growth_audit_launch`) sent 100, got 0 replies
  (verified via Gmail API 2026-06-24). Hypotheses: (1) the button CTA stole
  the engagement that could have become a reply; (2) From `iris@mail.analook.com`
  reads as transactional; (3) the HTML template looks marketing.

  This EDM removes all three. Plain text only, no buttons, no images,
  from a personal-looking address (iris@gingiris.com), single sentence
  question. If reply rate doesn't lift here, the hypothesis was wrong
  and we re-frame.

Usage:
    RESEND_API_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
        python scripts/edm/2026_06_quick_question.py --dry-run
    RESEND_API_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
        python scripts/edm/2026_06_quick_question.py --send

Optional flags:
    --cohort=engaged       Only users with credits_used > 0 (engaged segment)
    --cohort=never_used    Only users with credits_used = 0
    --cohort=all           Everyone (default)
    --max=N                Hard cap on send count (sanity guard)
    --from-fallback        Send from iris@mail.analook.com instead of gingiris.com
                           (use when gingiris.com isn't yet verified in Resend)
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ─── Config ──────────────────────────────────────────────────────────────────

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

# Cohort selector — P2 segmentation
COHORT = "all"
for a in sys.argv:
    if a.startswith("--cohort="):
        COHORT = a.split("=", 1)[1]
if COHORT not in ("all", "engaged", "never_used"):
    print(f"ERROR: invalid --cohort={COHORT} (use all|engaged|never_used)", file=sys.stderr)
    sys.exit(1)

# Hard cap (sanity guard against runaway sends)
MAX_SEND = None
for a in sys.argv:
    if a.startswith("--max="):
        MAX_SEND = int(a.split("=", 1)[1])

FROM_FALLBACK = "--from-fallback" in sys.argv

CAMPAIGN_ID = f"2026_06_quick_question_{COHORT}"

# From-address strategy:
# Default (recommended): `Iris Wei <iris@gingiris.com>` — personal-looking
# Fallback: `Iris Wei <iris@mail.analook.com>` — when gingiris.com isn't
#  yet added to Resend's verified domains
FROM_ADDR = "Iris Wei <iris@gingiris.com>"
if FROM_FALLBACK:
    FROM_ADDR = "Iris Wei <iris@mail.analook.com>"
REPLY_TO = "iris.wei@gingiris.com"

# Iris's own emails — never send to these
IRIS_EMAILS = {
    "iris103195@gmail.com",
    "gingiris1031@gmail.com",
    "iris.wei@gingiris.com",
}

# ─── HTTP helpers ────────────────────────────────────────────────────────────


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


def resend_check_domain():
    """Preflight: is the From-domain verified in Resend?
    Returns (verified: bool, info: dict|None).
    """
    domain = FROM_ADDR.split("@", 1)[1].rstrip(">")
    req = urllib.request.Request("https://api.resend.com/domains", headers={
        "Authorization": f"Bearer {RESEND_KEY}",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        for d in data.get("data", []):
            if d.get("name") == domain:
                return d.get("status") == "verified", d
        return False, None
    except Exception:
        return False, None


def first_name(email):
    """Conservative first-name extraction. See clone for rationale."""
    local = email.split("@")[0].lower()
    m = re.match(r"^([a-z]+)", local)
    if not m:
        return "there"
    name = m.group(1)
    if len(name) < 3 or len(name) > 8:
        return "there"
    return name[:1].upper() + name[1:]


# ─── Content — deliberately tiny ─────────────────────────────────────────────

# Single subject — no A/B variants. Keep this run clean for measurement.
# Lowercase deliberately ("looks hand-typed, not marketing-y").
SUBJECT = "quick question about your Analook audit"


def render_text(fn: str, used_audit: bool, last_url: str) -> str:
    """Three sentences, one question, no links except unsubscribe.

    Branching: minor wording change if recipient never ran an audit, so
    the email doesn't claim something untrue ("the report you ran on…").
    """
    if used_audit and last_url:
        opener = (
            f"Hi {fn} — I'm Iris, the founder of Analook. You ran an audit on "
            f"{last_url} recently, and I'm trying to figure out one thing."
        )
        question = (
            "Did the audit actually tell you something you didn't already know? "
            "Even a one-line reply (\"yes — the X part\" or \"no, generic\") would "
            "help me decide what to fix next."
        )
    else:
        opener = (
            f"Hi {fn} — I'm Iris, the founder of Analook. You signed up but haven't "
            "run an audit yet, and I'm trying to figure out one thing."
        )
        question = (
            "What stopped you? Was it the wait, the credit cost, or you just "
            "didn't have a competitor in mind? A one-line reply would help me "
            "decide what to build next."
        )

    return (
        f"{opener}\n\n"
        f"{question}\n\n"
        f"Thanks,\n"
        f"Iris\n"
        f"(founder, Analook · ex-COO AFFiNE 60k stars)\n"
    )


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    print(f"\n═══ EDM: {CAMPAIGN_ID} ═══")
    print(f"  Mode:     {'DRY-RUN' if DRY_RUN else 'LIVE SEND'}")
    print(f"  Cohort:   {COHORT}")
    print(f"  From:     {FROM_ADDR}")
    print(f"  Reply-to: {REPLY_TO}")
    print(f"  Subject:  {SUBJECT}")
    print(f"  Max cap:  {MAX_SEND or 'unlimited'}\n")

    # ─── Preflight: From-domain verification ─────────
    verified, info = resend_check_domain()
    if not verified:
        domain = FROM_ADDR.split("@", 1)[1].rstrip(">")
        print(f"  ⚠️  From-domain '{domain}' NOT VERIFIED in Resend.")
        print(f"      Resend domain status: {info.get('status') if info else 'NOT ADDED'}")
        print(f"      Add domain at https://resend.com/domains then verify DNS records.")
        if not FROM_FALLBACK:
            print(f"      → either run with --from-fallback to use iris@mail.analook.com,")
            print(f"      → or verify the domain first.")
            sys.exit(2)
        else:
            print(f"      (Using --from-fallback; mail.analook.com is verified)\n")
    else:
        print(f"  ✓ From-domain verified in Resend\n")

    # ─── Pull users ─────────
    profiles = sb_get("/rest/v1/profiles?select=id,email,plan_type,credits_used,credits_balance,created_at")
    reports = sb_get("/rest/v1/reports?select=user_id,url&order=created_at.desc&limit=500")

    # most recent url per user (for the opener)
    last_url_by_user = {}
    for r in reports:
        uid = r.get("user_id")
        if uid and uid not in last_url_by_user:
            last_url_by_user[uid] = r.get("url", "")

    # ─── Filter ─────────
    candidates = []
    for p in profiles:
        email = (p.get("email") or "").lower()
        if not email or email in IRIS_EMAILS:
            continue
        if p.get("plan_type") in ("pro", "team"):
            continue  # paid users get a separate workflow
        used = (p.get("credits_used") or 0) > 0
        if COHORT == "engaged" and not used:
            continue
        if COHORT == "never_used" and used:
            continue
        candidates.append({"id": p["id"], "email": email, "used": used,
                          "last_url": last_url_by_user.get(p["id"], "")})

    print(f"  Cohort '{COHORT}' candidate count: {len(candidates)}")

    # Dedup against already-sent
    try:
        sent = sb_get(f"/rest/v1/email_log?campaign_id=eq.{CAMPAIGN_ID}&select=user_id")
        already = {row["user_id"] for row in sent}
        before = len(candidates)
        candidates = [c for c in candidates if c["id"] not in already]
        print(f"  After dedup vs email_log: {len(candidates)} (skipped {before - len(candidates)} already sent)")
    except Exception:
        print("  (email_log dedup unavailable — proceeding)")

    if MAX_SEND:
        candidates = candidates[:MAX_SEND]
        print(f"  After --max cap: {len(candidates)}")

    if not candidates:
        print("\nNothing to do.")
        return

    # ─── Send ─────────
    sent_count = 0
    failed = []
    for i, c in enumerate(candidates, 1):
        email = c["email"]
        uid = c["id"]
        fn = first_name(email)
        text = render_text(fn, c["used"], c["last_url"])
        unsub = f"https://www.analook.com/unsubscribe.html?u={uid}&c={CAMPAIGN_ID}"

        payload = {
            "from": FROM_ADDR,
            "to": [email],
            "reply_to": REPLY_TO,
            "subject": SUBJECT,
            "text": text,  # plain text only — no html field, no buttons
            "headers": {
                # RFC 8058 one-click unsubscribe — keeps deliverability clean.
                "List-Unsubscribe": f"<{unsub}>, <mailto:unsubscribe@gingiris.com?subject=unsub-{uid}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
            "tags": [
                {"name": "campaign", "value": CAMPAIGN_ID},
                {"name": "cohort", "value": COHORT},
                {"name": "format", "value": "plain_text_reply_only"},
            ],
        }

        print(f"[{i}/{len(candidates)}] {email}  (used={c['used']})")

        if DRY_RUN:
            print(f"   text preview:\n      {text.replace(chr(10), chr(10)+'      ')}")
            continue

        try:
            resp = resend_send(payload)
            msg_id = resp.get("id", "?")
            print(f"   ✅ sent (resend id={msg_id})")
            try:
                sb_post("/rest/v1/email_log", [{
                    "campaign_id": CAMPAIGN_ID,
                    "user_id": uid,
                    "email": email,
                    "resend_message_id": msg_id,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                }])
            except Exception as e:
                print(f"   ⚠️ log skipped: {e}")
            sent_count += 1
            time.sleep(1.5)  # be polite to Resend
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
        print(f"\n  📈 To measure reply rate: in 5-7 days run the Gmail audit again")
        print(f"     with campaign_id={CAMPAIGN_ID}, then compare with the 0/100 baseline.")


if __name__ == "__main__":
    main()
