#!/usr/bin/env python3
"""Daily seed-report generator for analook.com's public /reports/ gallery.

Every run picks up to N fresh products — Product Hunt's current #1 plus the top
GitHub-trending projects that have a real product homepage — and runs a real
analook competitor-analysis audit on each. The completed reports are public, so
they land in the /reports/ gallery and each becomes an indexable, AI-citable
/report/{id} page. This is the growth flywheel: trending products → fresh
long-tail SEO pages every single day, on autopilot.

Design notes
------------
* Pure stdlib (urllib) so it runs anywhere, including inside the analook Fly
  image (which already has PRODUCTHUNT_TOKEN + SUPABASE_SERVICE_KEY in env).
* Product Hunt only exposes tracker (/r/HASH) links; we resolve them by
  following the 302 with a browser UA (works from datacenter + local).
* GitHub trending has no API — we scrape the (server-rendered) trending page,
  then hit the GitHub REST API per repo to read its `homepage`. We keep only
  repos that point at a REAL external site (not github.io / github.com / a
  localhost-y staging host).
* Dedup: skips any domain already present in the reports table, so we never
  spend a credit re-analysing a product already in the gallery.
* Auth: analook's /api/analyze needs a logged-in user with credits. We keep one
  dedicated seed account, create it once via the Supabase admin API, and top up
  its credits with the service key before each run. Free-tier reports are forced
  is_public=true, so seed reports are public by construction.
* After creation we ping IndexNow so Bing/Yandex crawl the new pages same-day.
"""
from __future__ import annotations
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed")

# ── Config (all overridable via env) ─────────────────────────────────────────
BASE            = os.environ.get("ANALOOK_BASE", "https://www.analook.com").rstrip("/")
SB_URL          = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY          = os.environ.get("SUPABASE_SERVICE_KEY", "")
PH_TOKEN        = os.environ.get("PRODUCTHUNT_TOKEN", "")
GH_TOKEN        = os.environ.get("GITHUB_TOKEN", "")  # optional, raises rate limit
INDEXNOW_KEY    = os.environ.get("INDEXNOW_KEY", "ceb743f3910e42b0ab39db1c7481abb8")
SEED_EMAIL      = os.environ.get("SEED_EMAIL", "seed-bot@analook.internal")
SEED_PASSWORD   = os.environ.get("SEED_PASSWORD", "")  # required
DAILY_COUNT     = int(os.environ.get("SEED_DAILY_COUNT", "3"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# Hosts we never want to seed: code hosts, and PaaS/preview staging domains
# (they produce ugly derived product names + carry little standalone SEO value).
_BAD_HOST = re.compile(
    r"(github\.io|github\.com|gitlab\.com|localhost|127\.0\.0\.1|example\.com|"
    r"producthunt\.com|readthedocs\.io|\.local$|"
    r"onrender\.com|vercel\.app|netlify\.app|netlify\.com|pages\.dev|"
    r"herokuapp\.com|railway\.app|fly\.dev|streamlit\.app|"
    r"web\.app|firebaseapp\.com|glitch\.me|replit\.(app|dev)|surge\.sh)", re.I)


def _req(url, *, data=None, headers=None, method=None, timeout=25, allow_redirects=True):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data).encode()
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    opener = urllib.request.build_opener()
    if not allow_redirects:
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(req, timeout=timeout)


def _domain(url: str) -> str:
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    host = urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
    return re.sub(r":(443|80)$", "", host)


# ── Candidate sources ────────────────────────────────────────────────────────
def resolve_ph_redirect(r_url: str) -> str | None:
    """Follow a producthunt.com/r/HASH tracker link to the real product URL."""
    try:
        resp = _req(r_url, timeout=20)
        final = resp.geturl()
        if final and "producthunt.com" not in final:
            # strip ?ref=producthunt querystring + any :443/:80 default port
            p = urllib.parse.urlparse(final)
            host = re.sub(r":(443|80)$", "", p.netloc)
            return f"{p.scheme}://{host}{p.path}".rstrip("/") or f"{p.scheme}://{host}"
    except Exception as e:
        log.warning("PH redirect resolve failed (%s): %s", r_url[:60], e)
    return None


def ph_top(n: int = 5) -> list[dict]:
    """Return today's top-voted PH posts with a resolved real website."""
    if not PH_TOKEN:
        log.info("no PRODUCTHUNT_TOKEN — skipping Product Hunt")
        return []
    q = ('{ posts(order: VOTES, first: %d) { edges { node { name tagline '
         'votesCount productLinks { url type } } } } }' % n)
    try:
        resp = _req("https://api.producthunt.com/v2/api/graphql",
                    data={"query": q},
                    headers={"Authorization": f"Bearer {PH_TOKEN}",
                             "Content-Type": "application/json"})
        edges = json.load(resp)["data"]["posts"]["edges"]
    except Exception as e:
        log.warning("PH API failed: %s", e)
        return []
    out = []
    for ed in edges:
        node = ed["node"]
        web = next((l["url"] for l in node.get("productLinks", []) if l.get("type") == "Website"), None)
        if not web:
            continue
        real = resolve_ph_redirect(web)
        if real and not _BAD_HOST.search(_domain(real)):
            out.append({"name": node["name"], "url": real,
                        "source": f"PH #{len(out)+1} ({node.get('votesCount')} votes)"})
    return out


def gh_trending(n: int = 12) -> list[dict]:
    """Scrape GitHub trending (daily) → keep repos with a real product homepage."""
    try:
        html = _req("https://github.com/trending?since=daily").read().decode("utf-8", "replace")
    except Exception as e:
        log.warning("GitHub trending fetch failed: %s", e)
        return []
    repos, seen = [], set()
    for m in re.finditer(r'href="/([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)"', html):
        repo = m.group(1)
        if repo in seen or "/" not in repo:
            continue
        if re.search(r"^(trending|topics|collections|sponsors|login|features|about|apps)/", repo):
            continue
        seen.add(repo)
    out = []
    gh_headers = {"Accept": "application/vnd.github+json"}
    if GH_TOKEN:
        gh_headers["Authorization"] = f"Bearer {GH_TOKEN}"
    for repo in list(seen)[:n]:
        try:
            info = json.load(_req(f"https://api.github.com/repos/{repo}", headers=gh_headers))
        except Exception:
            continue
        hp = (info.get("homepage") or "").strip()
        if not hp or not hp.startswith("http"):
            continue
        if _BAD_HOST.search(_domain(hp)):
            continue
        out.append({"name": info.get("name") or repo.split("/")[-1],
                    "url": hp, "source": f"GitHub trending ({info.get('stargazers_count')}★)"})
    return out


# ── Dedup against what's already in the gallery ──────────────────────────────
def existing_domains() -> set[str]:
    if not (SB_URL and SB_KEY):
        return set()
    try:
        url = f"{SB_URL}/rest/v1/reports?select=url&limit=1000"
        rows = json.load(_req(url, headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}))
        return {_domain(r.get("url") or "") for r in rows if r.get("url")}
    except Exception as e:
        log.warning("existing_domains query failed: %s", e)
        return set()


# ── Seed account + audit runner (real /api/analyze path) ─────────────────────
def ensure_seed_credits(target: int = 30) -> str | None:
    """Ensure the seed account exists + has credits; return an access token."""
    if not (SB_URL and SB_KEY and SEED_PASSWORD):
        log.error("missing SUPABASE_URL / SUPABASE_SERVICE_KEY / SEED_PASSWORD")
        return None
    admin = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}", "Content-Type": "application/json"}
    # Try to log in first; create the account if that fails.
    def _login():
        try:
            r = _req(f"{SB_URL}/auth/v1/token?grant_type=password",
                     data={"email": SEED_EMAIL, "password": SEED_PASSWORD},
                     headers={"apikey": SB_KEY, "Content-Type": "application/json"})
            return json.load(r)
        except Exception:
            return None
    auth = _login()
    if not auth or not auth.get("access_token"):
        try:
            _req(f"{SB_URL}/auth/v1/admin/users", data={
                "email": SEED_EMAIL, "password": SEED_PASSWORD, "email_confirm": True}, headers=admin)
            log.info("created seed account %s", SEED_EMAIL)
        except Exception as e:
            log.warning("seed account create (may already exist): %s", e)
        auth = _login()
    if not auth or not auth.get("access_token"):
        log.error("seed login failed")
        return None
    uid = auth["user"]["id"]
    # Top up credits so we can run the day's batch.
    try:
        _req(f"{SB_URL}/rest/v1/profiles?id=eq.{uid}",
             data={"credits_balance": target}, headers={**admin, "Prefer": "return=minimal"},
             method="PATCH")
    except Exception as e:
        log.warning("credit top-up failed: %s", e)
    return auth["access_token"]


def run_audit(token: str, url: str) -> str | None:
    """Fire /api/analyze and poll to completion. Returns job_id or None."""
    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        start = json.load(_req(f"{BASE}/api/analyze", data={"url": url, "lang": "en"}, headers=hdr))
    except Exception as e:
        log.warning("analyze start failed for %s: %s", url, e)
        return None
    job = start.get("job_id")
    if not job:
        log.warning("no job_id for %s: %s", url, start)
        return None
    for _ in range(60):  # up to ~5 min
        time.sleep(5)
        try:
            st = json.load(_req(f"{BASE}/api/status/{job}", headers=hdr))
        except Exception:
            continue
        s = st.get("status")
        if s == "completed":
            return job
        if s == "failed":
            log.warning("audit failed for %s", url)
            return None
    log.warning("audit timed out for %s", url)
    return None


def ping_indexnow(job_ids: list[str]):
    if not job_ids:
        return
    urls = [f"{BASE}/report/{j}" for j in job_ids] + [f"{BASE}/reports/", f"{BASE}/zh/reports/"]
    payload = {"host": "www.analook.com", "key": INDEXNOW_KEY,
               "keyLocation": f"{BASE}/{INDEXNOW_KEY}.txt", "urlList": urls}
    try:
        _req("https://api.indexnow.org/indexnow",
             data=payload, headers={"Content-Type": "application/json; charset=utf-8"})
        log.info("IndexNow pinged %d URLs", len(urls))
    except Exception as e:
        log.warning("IndexNow ping failed: %s", e)


# ── Orchestrate ──────────────────────────────────────────────────────────────
def pick_candidates(count: int) -> list[dict]:
    have = existing_domains()
    log.info("gallery already has %d domains", len(have))
    picked, used = [], set(have)
    # 1) Product Hunt #1 first (Iris's explicit priority).
    for c in ph_top(5):
        d = _domain(c["url"])
        if d and d not in used:
            picked.append(c); used.add(d)
            break
    # 2) Fill the rest from GitHub trending.
    for c in gh_trending(15):
        if len(picked) >= count:
            break
        d = _domain(c["url"])
        if d and d not in used:
            picked.append(c); used.add(d)
    return picked[:count]


def main():
    log.info("=== analook seed-reports run (target %d) ===", DAILY_COUNT)
    cands = pick_candidates(DAILY_COUNT)
    if not cands:
        log.info("no fresh candidates today — nothing to do")
        return 0
    for c in cands:
        log.info("candidate: %s  <%s>  [%s]", c["name"], c["url"], c["source"])
    token = ensure_seed_credits(target=max(30, DAILY_COUNT * 3))
    if not token:
        log.error("could not obtain seed token — aborting")
        return 1
    done = []
    for c in cands:
        log.info("→ analysing %s (%s)", c["name"], c["url"])
        job = run_audit(token, c["url"])
        if job:
            done.append(job)
            log.info("  ✓ %s → /report/%s", c["name"], job)
        else:
            log.info("  ✗ %s skipped", c["name"])
    ping_indexnow(done)
    log.info("=== done: %d/%d reports created ===", len(done), len(cands))
    return 0


if __name__ == "__main__":
    sys.exit(main())
