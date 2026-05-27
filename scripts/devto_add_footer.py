#!/usr/bin/env python3
"""
dev.to 批量 footer 导流脚本

为 dev.to/iris1031 所有已发布文章末尾追加一条「更多内容 → gingiris.tools」导流块。
目的：用 dev.to (DA 95+) 的曝光给新域名 gingiris.tools 导流 + 反向链接信号。

Safety:
- 只 PATCH **已发布** 文章 (published=True)
- 检测如果 body 已经包含 footer 标记，**跳过**（idempotent）
- 失败列表保留，可重试
- Rate-limit: 1 PATCH / 2.5 秒（dev.to 限 30 req/30s）

Usage:
    DEV_TO_API_KEY=... python scripts/devto_add_footer.py --dry-run
    DEV_TO_API_KEY=... python scripts/devto_add_footer.py --send
"""
import json
import os
import sys
import time
import urllib.request

DEV_KEY = "".join(c for c in os.environ.get("DEV_TO_API_KEY", "") if c.isprintable() and not c.isspace())
if not DEV_KEY:
    print("ERROR: set DEV_TO_API_KEY", file=sys.stderr)
    sys.exit(1)

DRY = "--dry-run" in sys.argv
SEND = "--send" in sys.argv
if not (DRY or SEND):
    print("Specify --dry-run or --send", file=sys.stderr); sys.exit(1)

FOOTER_MARKER = "<!-- gingiris-footer-v1 -->"

FOOTER_BLOCK = f"""

---

{FOOTER_MARKER}

### 📖 Read the full series at [gingiris.tools](https://gingiris.tools)

This article is part of [Gingiris Growth Tools](https://gingiris.tools) — Iris's collection of 90+ practical playbooks for SaaS marketing, open-source growth, Product Hunt launches, and AI agent workflows. Written from 4 years co-founding [AFFiNE](https://github.com/toeverything/AFFiNE) (60K+ GitHub stars), 30x Product Hunt #1 launches, and currently bootstrapping [Analook](https://www.analook.com) — a free AI competitor analysis tool.

**Connect**: [gingiris.com](https://gingiris.com) · [Skills on ClawHub](https://clawhub.ai/user/gingiris) · [Try Analook free](https://www.analook.com)
""".strip()


def api(method, path, body=None, retries=4):
    url = f"https://dev.to/api{path}"
    data = json.dumps(body).encode() if body else None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, method=method, data=data, headers={
                "api-key": DEV_KEY,
                "Content-Type": "application/json",
                "Accept": "application/vnd.forem.api-v1+json",
                "User-Agent": "gingiris-footer-bot/1.0",
            })
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 10 * (attempt + 1)
                print(f"  ⏳ 429, sleeping {wait}s...")
                time.sleep(wait)
                continue
            raise


def fetch_all_articles():
    """Paginate through all me/all articles."""
    out = []
    page = 1
    while True:
        batch = api("GET", f"/articles/me/all?per_page=100&page={page}")
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return out


def main():
    print(f"\n=== dev.to footer migration — {('DRY' if DRY else 'LIVE')} ===\n")

    print("Fetching all articles...")
    articles = fetch_all_articles()
    print(f"Total: {len(articles)}\n")

    published = [a for a in articles if a.get("published")]
    print(f"Published: {len(published)}")

    # Fetch full body for each (list endpoint truncates body)
    # Note: that's expensive. Let's fetch ONLY on patching.
    # Strategy: try a PATCH directly; if response has body_markdown without our marker, add it.

    skipped = 0
    queued = []
    for i, a in enumerate(published, 1):
        aid = a["id"]
        if i % 10 == 1:
            print(f"  scanning {i}/{len(published)}...")
        full = api("GET", f"/articles/{aid}")
        body = full.get("body_markdown", "") or ""
        if FOOTER_MARKER in body:
            skipped += 1
        else:
            queued.append((aid, full.get("title", "")[:60], body))
        time.sleep(1.2)  # be polite, avoid 429 on scan

    print(f"Already have footer (skip): {skipped}")
    print(f"To patch: {len(queued)}\n")

    if not queued:
        return

    sent = 0
    failed = []
    for i, (aid, title, body) in enumerate(queued, 1):
        new_body = body.rstrip() + "\n\n" + FOOTER_BLOCK + "\n"
        print(f"[{i}/{len(queued)}] id={aid}  {title}")
        if DRY:
            continue
        try:
            api("PUT", f"/articles/{aid}", {"article": {"body_markdown": new_body}})
            sent += 1
            time.sleep(2.5)  # dev.to rate limit
        except Exception as e:
            print(f"  ❌ {e}")
            failed.append((aid, str(e)[:100]))

    print(f"\n--- Summary ---")
    if DRY:
        print(f"Would patch: {len(queued)}")
    else:
        print(f"Patched: {sent}/{len(queued)}")
        if failed:
            print(f"Failed: {len(failed)}")
            for aid, err in failed[:5]:
                print(f"  {aid}: {err}")


if __name__ == "__main__":
    main()
