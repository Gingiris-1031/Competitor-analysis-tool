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


# Fields that carry VERBATIM QUOTES of external data (tweets, press headlines,
# search snippets, on-site slogans). When the analyzed product is Chinese
# (e.g. Amz123), these legitimately contain CJK in an EN report — that is
# evidence fidelity, not a template leak. The guard's job is templates.
QUOTE_FIELDS = {"title", "snippet", "text", "text_preview", "slogan",
                "description", "content", "quote", "body", "summary_quote",
                "primary_event", "event",
                # verbatim scrape of the ANALYZED SITE's own pages
                "meta_description", "nav_links", "h1s", "h2s", "headings",
                "headings_h1", "headings_h2", "headings_h3",
                "structure_summary", "og_title", "og_description"}

# Analook-generated fields that ALWAYS embed a verbatim foreign quote of the
# analyzed site (its own slogan/title). The English scaffold is correct; the
# CJK inside is the competitor's real on-site copy — evidence, not a leak.
QUOTE_EMBED_PATHS = (".evolution_summary", ".ai_insights.content",
                     ".attribution.summary", ".uncited_numbers")

# Quote openers: a CJK run right after English text + one of these = a quoted
# verbatim value inside an English template (not a template leak).
_OPENERS = ('"', "'", "“", "”", "‘", "’", "「", "『", "（", "(", "：", ":", "»", "«")


def _is_quote_path(path: str) -> bool:
    # Any path segment being a scrape/quote field means the value is external
    # data (e.g. facts.product.slogan.v — the {t,v} value of a scraped slogan).
    segs = [seg.split("[")[0] for seg in path.split(".")]
    if any(seg in QUOTE_FIELDS for seg in segs):
        return True
    return any(p in path for p in QUOTE_EMBED_PATHS)


def _is_template_plus_quote(s: str) -> bool:
    """'<english template><opener><verbatim CJK data>' — e.g.
    '🔥 Media/News buzz: 亚马逊选品工具…', 'Slogan changed: "AMZ123…"', or
    'From the first real version in 2024-11 (\"RustFS | MinIO国产化…\")'.
    The template half is English (correct); the CJK is quoted evidence.
    A genuine template leak has CJK with NO English+opener before it."""
    mm = CJK.search(s)
    if not mm:
        return False
    prefix = s[:mm.start()]
    import re as _re
    if not _re.search(r"[A-Za-z]", prefix):
        return False  # no English scaffold at all → real leak
    # English present AND an opener appears somewhere before the CJK run.
    return any(op in prefix for op in _OPENERS)


def scan(obj, path="", quotes=None):
    hits = []
    if isinstance(obj, str):
        if CJK.search(obj):
            if _is_quote_path(path) or _is_template_plus_quote(obj):
                if quotes is not None:
                    quotes.append((path, obj.strip()[:70]))
            else:
                hits.append((path, obj.strip()[:70]))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            hits += scan(v, f"{path}.{k}", quotes)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += scan(v, f"{path}[{i}]", quotes)
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
        quotes: list = []
        hits = scan(r.get("sections") or {}, "sections", quotes) + scan(r.get("meta") or {}, "meta", quotes)
        qnote = f" ({len(quotes)} CJK data-quote(s) — evidence verbatim, not counted)" if quotes else ""
        if hits:
            total += len(hits)
            print(f"❌ {rid}: {len(hits)} template CJK leak(s){qnote}")
            for p, s in hits[:40]:
                print(f"     {p}: «{s}»")
        else:
            print(f"✅ {rid}: 0 template CJK{qnote}")
    if total:
        print(f"\nFAIL: {total} CJK leak(s) in EN report(s) — English reports must be CJK-clean")
        return 1
    print("\nPASS: sampled EN reports are CJK-clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
