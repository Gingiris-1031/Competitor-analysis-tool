#!/usr/bin/env python3
"""Language-purity guard for EN reports.

Fetches live public reports whose meta.lang == "en" and asserts the report JSON
contains ZERO CJK characters. Catches the recurring class of bug where backend
modules leak hardcoded Chinese into English reports (survives report refactors
because it checks OUTPUT, not code). Exit 1 + prints exact field paths on leak.

Run in CI or manually:
    python scripts/check_report_lang_purity.py                # sample recent EN reports
    python scripts/check_report_lang_purity.py 1e6af2b3 ...   # specific report ids
"""
import json
import re
import sys
import urllib.request

BASE = "https://www.analook.com"
CJK = re.compile(r"[一-鿿]")
SAMPLE_N = int(__import__("os").environ.get("PURITY_SAMPLE", "5"))


def _get(url):
    return json.load(urllib.request.urlopen(url, timeout=30))


def scan(obj, path=""):
    hits = []
    if isinstance(obj, str):
        if CJK.search(obj):
            hits.append((path, obj.strip()[:70]))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            hits += scan(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += scan(v, f"{path}[{i}]")
    return hits


def _pick_en_ids(n):
    ids = []
    for r in (_get(f"{BASE}/api/public-reports").get("reports") or []):
        rid = r["id"]
        if str(rid).startswith("ga-"):
            continue
        try:
            rep = _get(f"{BASE}/api/report/{rid}")
        except Exception:
            continue
        if ((rep.get("report") or rep).get("meta") or {}).get("lang") == "en":
            ids.append(rid)
        if len(ids) >= n:
            break
    return ids


def main():
    ids = sys.argv[1:] or _pick_en_ids(SAMPLE_N)
    if not ids:
        print("no EN reports found to check")
        return 0
    total = 0
    for rid in ids:
        rep = _get(f"{BASE}/api/report/{rid}")
        r = rep.get("report") or rep
        if (r.get("meta") or {}).get("lang") != "en":
            print(f"  {rid}: not an EN report — skipping")
            continue
        hits = scan(r.get("sections") or {}, "sections") + scan(r.get("meta") or {}, "meta")
        if hits:
            total += len(hits)
            print(f"❌ {rid}: {len(hits)} CJK leak(s)")
            for p, s in hits[:40]:
                print(f"     {p}: «{s}»")
        else:
            print(f"✅ {rid}: 0 CJK")
    if total:
        print(f"\nFAIL: {total} CJK leak(s) in EN report(s) — English reports must be CJK-clean")
        return 1
    print("\nPASS: sampled EN reports are CJK-clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
