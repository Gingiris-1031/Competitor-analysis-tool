#!/usr/bin/env python3
"""
Analook 归因报告 — 把注册/激活/付费按「获客渠道」拆开

数据源（两路，交叉验证）：
  1. 客观首次触点：profiles.first_utm_source / first_referrer / first_landing_path
     （由 attribution.js 锁定 + /api/profile/attribution 写入，见
      migrations/2026_06_18_first_touch_attribution.sql）
  2. 自报调查：profiles.referral_source（migrations/2026_06_11_referral_source.sql）

Usage:
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/attribution_report.py
    # 线上：flyctl ssh console -a competitor-analysis-tool -C "python scripts/attribution_report.py"

回答的核心问题：「每周 +31 注册到底从哪来？哪个渠道出激活、出付费？某天的爆发是哪条链接？」
"""
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

SVC = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
URL = os.environ.get("SUPABASE_URL", "").strip()
if not SVC or not URL:
    print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY", file=sys.stderr)
    sys.exit(1)

IRIS_EMAILS = {
    "iris103195@gmail.com", "gingiris1031@gmail.com", "iris.wei@gingiris.com",
}
# QA / load-test artifacts that pollute the real counts.
def _is_test(email: str) -> bool:
    e = (email or "").lower()
    return ("@mailinator.com" in e) or ("lastestcloud+analook" in e) or ("analook_test_" in e)

HDR = {"apikey": SVC, "Authorization": f"Bearer {SVC}"}


def _fetch(path: str):
    req = urllib.request.Request(URL + path, headers=HDR)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _parse_iso(s: str):
    if not s:
        return None
    if "." in s and "+" in s:
        prefix, rest = s.split(".", 1)
        us, tz = rest.split("+", 1)
        s = f"{prefix}.{us[:6].ljust(6, '0')}+{tz}"
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ── Referrer host → channel ───────────────────────────────────────────────
_REF_RULES = [
    (("t.co", "twitter.com", "x.com"),            "twitter"),
    (("reddit.com", "redd.it"),                   "reddit"),
    (("news.ycombinator.com", "ycombinator"),     "hackernews"),
    (("google.",),                                "google_search"),
    (("bing.com", "duckduckgo.com"),              "search_other"),
    (("linkedin.com", "lnkd.in"),                 "linkedin"),
    (("producthunt.com",),                        "producthunt"),
    (("github.com",),                             "github"),
    (("dev.to",),                                 "devto"),
    (("huggingface.co",),                         "huggingface"),
    (("baidu.com", "zhihu.com", "juejin"),        "cn_search_social"),
    (("facebook.com", "instagram.com", "t.me"),   "social_other"),
]


def _channel(p: dict) -> str:
    """Normalize a profile's first-touch into one channel label."""
    src = (p.get("first_utm_source") or "").strip().lower()
    if src:
        return src  # explicit utm_source always wins
    ref = (p.get("first_referrer") or "").strip().lower()
    if ref:
        host = (urlparse(ref).netloc or ref).lower()
        for needles, label in _REF_RULES:
            if any(n in host for n in needles):
                return label
        return f"ref:{host[:40]}" if host else "direct"
    # No utm, no referrer.
    if p.get("first_touch_at"):
        return "direct"
    return "unknown(pre-infra)"  # signed up before attribution.js shipped


def _bar(n: int, total: int, width: int = 22) -> str:
    if not total:
        return ""
    filled = round(width * n / total)
    return "█" * filled + "·" * (width - filled)


def main():
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Probe: are the first-touch columns present yet?
    try:
        profiles = _fetch(
            "/rest/v1/profiles?select=id,email,plan_type,created_at,"
            "referral_source,referral_other,"
            "first_utm_source,first_utm_medium,first_utm_campaign,"
            "first_referrer,first_landing_path,first_touch_at"
        )
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            print("⚠️  first_touch_* columns not found — run migration first:")
            print("    migrations/2026_06_18_first_touch_attribution.sql "
                  "(paste into Supabase SQL editor)")
            sys.exit(2)
        raise

    reports = _fetch("/rest/v1/reports?select=user_id,created_at&limit=5000")

    # Real (non-Iris, non-test) profiles keyed by id.
    prof = {p["id"]: p for p in profiles
            if (p.get("email") or "").lower() not in IRIS_EMAILS
            and not _is_test(p.get("email"))}
    total = len(prof)

    activated_ids = {r["user_id"] for r in reports if r.get("user_id")}
    def _activated(uid): return uid in activated_ids
    def _paid(p): return p.get("plan_type") in ("pro", "team")

    # ── Channel breakdown: signups / activated / paid ────────────────────
    sign = Counter()
    act = Counter()
    paid = Counter()
    for uid, p in prof.items():
        ch = _channel(p)
        sign[ch] += 1
        if _activated(uid):
            act[ch] += 1
        if _paid(p):
            paid[ch] += 1

    out = []
    out.append(f"# Analook 归因报告 — {now.strftime('%Y-%m-%d %H:%M')} UTC")
    out.append("")
    out.append(f"_真实外部用户 {total}（已剔除 Iris 3 账号 + test 账号）_")
    out.append("")

    captured = sum(1 for p in prof.values() if p.get("first_touch_at"))
    answered = sum(1 for p in prof.values() if p.get("referral_source"))
    out.append(f"- 首次触点已捕获（客观）: **{captured}/{total}** "
               f"({round(100*captured/total,1) if total else 0}%)")
    out.append(f"- 自报调查已回答: **{answered}/{total}** "
               f"({round(100*answered/total,1) if total else 0}%)")
    out.append("")

    out.append("## 渠道漏斗（客观首次触点）")
    out.append("")
    out.append("| 渠道 | 注册 | 占比 | 激活 | 激活率 | 付费 |")
    out.append("|------|----:|:-----|----:|:------|----:|")
    for ch, n in sign.most_common():
        a = act.get(ch, 0)
        pd = paid.get(ch, 0)
        arate = f"{round(100*a/n)}%" if n else "—"
        out.append(f"| `{ch}` | {n} | {_bar(n,total)} | {a} | {arate} | {pd} |")
    out.append("")

    # ── Per-day signups (last 14d) with dominant channel — explains bursts ─
    out.append("## 每日新增（近 14 天，含当日主渠道）")
    out.append("")
    by_day = defaultdict(list)
    for uid, p in prof.items():
        ts = _parse_iso(p.get("created_at", ""))
        if ts and ts >= now - timedelta(days=14):
            by_day[ts.strftime("%Y-%m-%d")].append(_channel(p))
    out.append("| 日期 | 新增 | 渠道分布 |")
    out.append("|------|----:|---------|")
    for day in sorted(by_day, reverse=True):
        chans = Counter(by_day[day])
        dist = ", ".join(f"{c}×{k}" for c, k in chans.most_common())
        flag = " 🔥" if len(by_day[day]) >= 10 else ""
        out.append(f"| {day}{flag} | {len(by_day[day])} | {dist} |")
    out.append("")

    # ── Cross-check: objective channel vs self-report ────────────────────
    out.append("## 交叉验证：客观渠道 × 自报来源")
    out.append("")
    out.append("| 自报来源 | 人数 | 对应客观渠道（top） |")
    out.append("|----------|----:|---------------------|")
    by_self = defaultdict(list)
    for p in prof.values():
        if p.get("referral_source"):
            by_self[p["referral_source"]].append(_channel(p))
    for self_src in sorted(by_self, key=lambda k: -len(by_self[k])):
        objs = Counter(by_self[self_src])
        top = ", ".join(f"{c}×{k}" for c, k in objs.most_common(3))
        out.append(f"| {self_src} | {len(by_self[self_src])} | {top} |")
    out.append("")

    # ── Top landing pages & campaigns ────────────────────────────────────
    land = Counter((p.get("first_landing_path") or "—") for p in prof.values()
                   if p.get("first_touch_at"))
    camp = Counter((p.get("first_utm_campaign") or "—") for p in prof.values()
                   if p.get("first_utm_campaign"))
    if land:
        out.append("## Top 落地页（首次触点）")
        out.append("")
        for path, n in land.most_common(8):
            out.append(f"- `{path}` × {n}")
        out.append("")
    if camp:
        out.append("## Top utm_campaign")
        out.append("")
        for c, n in camp.most_common(8):
            out.append(f"- `{c}` × {n}")
        out.append("")

    # ── Action hints ─────────────────────────────────────────────────────
    out.append("## 关注点")
    out.append("")
    if captured / total < 0.5 if total else True:
        out.append(f"- ⏳ 客观捕获仅 {round(100*captured/total) if total else 0}% — "
                   "需等新注册累积（attribution.js 只对部署后的新访客生效）")
    # Best activating channel (min 3 signups)
    best = [(ch, act.get(ch,0)/n) for ch, n in sign.items() if n >= 3]
    if best:
        ch, rate = max(best, key=lambda x: x[1])
        out.append(f"- 🏆 激活率最高的渠道（≥3 注册）：`{ch}` ({round(100*rate)}%) — 加投这个")
    if paid:
        pch = paid.most_common(1)[0]
        out.append(f"- 💰 出付费的渠道：`{pch[0]}`（{pch[1]} 付费）— 复制它")
    else:
        out.append("- 💰 暂无任何渠道出付费 — 付费瓶颈与渠道无关，去查 paywall/定价")

    print("\n".join(out))


if __name__ == "__main__":
    main()
