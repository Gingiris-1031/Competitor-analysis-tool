#!/usr/bin/env python3
"""
Analook 周报生成器 — 用户增长 / 激活 / 付费 / 报告活跃度

Usage:
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/user_metrics.py

Output: human-readable Markdown to stdout. Can be piped to email / Slack /
appended to docs/seo_tracker_baseline.md.

Iris baseline (2026-04-29):
  - 39 registered, 36 external (3 = Iris's own accounts)
  - 1 external user has run ≥1 report (wangherbert97@gmail.com)
  - Activation rate: 2.8% (1/36)
  - Paying users: 0
  - Reports persisted to Supabase: 4 total (3 = Iris)
"""
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone


SVC = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
URL = os.environ.get("SUPABASE_URL", "").strip()
if not SVC or not URL:
    print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY", file=sys.stderr)
    sys.exit(1)

# Iris's own accounts — exclude from "real users" stats
IRIS_EMAILS = {
    "iris103195@gmail.com",
    "gingiris1031@gmail.com",
    "iris.wei@gingiris.com",
}

HDR = {"apikey": SVC, "Authorization": f"Bearer {SVC}"}


def _fetch(path: str) -> list | dict:
    req = urllib.request.Request(URL + path, headers=HDR)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    # Supabase returns: 2026-04-19T09:21:56.22105+00:00 — variable µs digits
    # break standard fromisoformat. Truncate µs to 6 digits.
    if "." in s and "+" in s:
        prefix, rest = s.split(".", 1)
        us, tz = rest.split("+", 1)
        s = f"{prefix}.{us[:6].ljust(6, '0')}+{tz}"
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def main():
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    users = _fetch("/auth/v1/admin/users?per_page=500").get("users", [])
    profiles = {p["id"]: p for p in _fetch(
        "/rest/v1/profiles?select=id,email,plan_type,credits_balance,credits_used,credits_monthly_quota,created_at"
    )}
    reports = _fetch("/rest/v1/reports?select=id,user_id,url,product_name,created_at&limit=2000")

    external_users = [u for u in users if (u.get("email") or "").lower() not in IRIS_EMAILS]
    total = len(external_users)

    # Activation: ran ≥1 report
    report_per_user = Counter()
    last_report_per_user = {}
    for r in reports:
        uid = r.get("user_id")
        if not uid:
            continue
        report_per_user[uid] += 1
        ts = _parse_iso(r.get("created_at", ""))
        if ts and (uid not in last_report_per_user or ts > last_report_per_user[uid]):
            last_report_per_user[uid] = ts

    activated_users = [u for u in external_users if report_per_user.get(u["id"], 0) > 0]
    active_this_week = [u for u in external_users
                        if last_report_per_user.get(u["id"]) and last_report_per_user[u["id"]] >= week_ago]

    # Paid: plan_type in (pro, team) AND email != Iris (since we manually
    # gave Iris pro plan with 999999 credits)
    paid_users = [u for u in external_users
                  if profiles.get(u["id"], {}).get("plan_type") in ("pro", "team")]

    # Signups by week
    new_this_week = [u for u in external_users
                     if _parse_iso(u.get("created_at", "")) and _parse_iso(u["created_at"]) >= week_ago]

    # Reports breakdown
    external_reports = [r for r in reports
                        if r.get("user_id") and (profiles.get(r["user_id"], {}).get("email", "")).lower() not in IRIS_EMAILS]
    reports_this_week = [r for r in external_reports
                         if _parse_iso(r.get("created_at", "")) and _parse_iso(r["created_at"]) >= week_ago]

    # Top URLs analyzed
    url_counter = Counter(r.get("url", "")[:60] for r in external_reports if r.get("url"))

    # ── Output ──────────────────────────────────────────────────────────────
    out = []
    out.append(f"# Analook 周报 — {now.strftime('%Y-%m-%d')}")
    out.append("")
    out.append(f"_(对比 7 天前 {week_ago.strftime('%Y-%m-%d')} → 今天 {now.strftime('%Y-%m-%d')}；不含 Iris 自己 3 个账号)_")
    out.append("")
    out.append("## Key Stats")
    out.append("")
    out.append("| 指标 | 当前 | 本周新增 |")
    out.append("|------|------|---------|")
    out.append(f"| 外部注册用户 | **{total}** | +{len(new_this_week)} |")
    act_pct = round(100 * len(activated_users) / total, 1) if total else 0
    out.append(f"| 激活用户（≥1 report） | **{len(activated_users)}** ({act_pct}%) | +{sum(1 for u in activated_users if _parse_iso(u.get('created_at','')) and _parse_iso(u['created_at']) >= week_ago)} |")
    out.append(f"| 本周活跃（最近 7 天跑过分析） | **{len(active_this_week)}** | — |")
    paid_pct = round(100 * len(paid_users) / total, 1) if total else 0
    out.append(f"| 付费用户（pro/team） | **{len(paid_users)}** ({paid_pct}%) | — |")
    out.append(f"| 外部用户报告总数 | **{len(external_reports)}** | +{len(reports_this_week)} |")
    out.append("")

    if new_this_week:
        out.append("## 本周新注册")
        out.append("")
        for u in new_this_week:
            email = u.get("email", "—")
            created = (u.get("created_at") or "")[:10]
            rcount = report_per_user.get(u["id"], 0)
            note = f" · {rcount} reports" if rcount else " · 未激活"
            out.append(f"- `{created}` **{email}**{note}")
        out.append("")

    if active_this_week:
        out.append("## 本周活跃用户")
        out.append("")
        for u in active_this_week:
            email = u.get("email", "—")
            last = last_report_per_user[u["id"]].strftime("%Y-%m-%d")
            count = report_per_user[u["id"]]
            out.append(f"- **{email}** — 最后用 {last}，累计 {count} reports")
        out.append("")

    if url_counter:
        out.append("## Top 5 被分析的竞品")
        out.append("")
        for url, n in url_counter.most_common(5):
            out.append(f"- `{url}` × {n}")
        out.append("")

    # Funnel snapshot
    out.append("## 漏斗")
    out.append("")
    out.append(f"```")
    out.append(f"注册 ({total}) → 激活 ({len(activated_users)}) → 付费 ({len(paid_users)})")
    out.append(f"          ↓ {act_pct}%        ↓ {round(100 * len(paid_users) / max(len(activated_users),1), 1)}%")
    out.append(f"```")
    out.append("")

    # Action items based on numbers
    out.append("## 关注点")
    out.append("")
    if act_pct < 10:
        out.append(f"- 🚨 激活率 {act_pct}% 低于阈值（10%）— 需要加 onboarding")
    if len(paid_users) == 0 and total >= 30:
        out.append("- 💰 0 付费转化 — 该看 pricing 页面 / 升级路径是不是断了")
    if len(new_this_week) == 0:
        out.append("- 📉 本周 0 新增 — 增长来源断了，需要补 launch")
    elif len(new_this_week) >= 10:
        out.append(f"- 🎉 本周 {len(new_this_week)} 新增 — 哪个渠道爆了？记录归因")

    print("\n".join(out))


if __name__ == "__main__":
    main()
