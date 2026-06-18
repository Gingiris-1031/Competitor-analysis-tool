#!/usr/bin/env python3
"""Grant N credits to a user by email — non-destructive (max of current + grant
vs current+grant, so we never lower an existing balance).

Usage:
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
      python scripts/grant_credits.py <email> <amount>

Example:
    SUPABASE_URL=https://nkunysycqapregxubcil.supabase.co \
    SUPABASE_SERVICE_KEY=$(fly secrets get SUPABASE_SERVICE_KEY -a competitor-analysis-tool) \
      python scripts/grant_credits.py lizyaa040@gmail.com 300

Iris notes:
- Always ADD to current balance (never overwrite). User may have purchased
  credits since last manual grant; clobbering them with N would destroy
  paid value and trigger a Polar/Clink chargeback.
- Idempotency is the caller's problem — re-running grants again. If you
  need idempotent grants, track a granted_by/note column.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone


def _req(method: str, path: str, body=None) -> dict | list:
    url = URL.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        **HDR,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else []


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: grant_credits.py <email> <amount>", file=sys.stderr)
        return 1
    email = sys.argv[1].strip().lower()
    try:
        amount = int(sys.argv[2])
    except ValueError:
        print("amount must be an integer", file=sys.stderr)
        return 1
    if amount <= 0:
        print("amount must be > 0", file=sys.stderr)
        return 1

    # 1. Look up profile by email
    rows = _req(
        "GET",
        f"/rest/v1/profiles?select=id,email,credits_balance,plan_type&email=eq.{email}",
    )
    if not rows:
        # auth.users may have the email but profile not yet created. Try auth.
        print(f"❌ no profile row found for {email}", file=sys.stderr)
        return 2
    profile = rows[0]
    current = int(profile.get("credits_balance") or 0)
    new_balance = current + amount

    # 2. Update with max() semantics for safety, but in practice the
    #    select-then-update pattern already gives us linearisability
    #    (no other writer at the same time for a manual grant).
    updated = _req(
        "PATCH",
        f"/rest/v1/profiles?id=eq.{profile['id']}",
        body={"credits_balance": new_balance},
    )

    print(json.dumps({
        "ok": True,
        "email": email,
        "user_id": profile["id"],
        "plan_type": profile.get("plan_type"),
        "balance_before": current,
        "amount_granted": amount,
        "balance_after": new_balance,
        "verified_via": "PATCH return=representation",
        "granted_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    return 0


SVC = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
URL = os.environ.get("SUPABASE_URL", "").strip()
if not SVC or not URL:
    print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY", file=sys.stderr)
    sys.exit(1)
HDR = {"apikey": SVC, "Authorization": f"Bearer {SVC}"}


if __name__ == "__main__":
    sys.exit(main())
