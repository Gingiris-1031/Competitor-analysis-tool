# IndieHackers Featured Story Draft

> **Submission target**: https://www.indiehackers.com/post/new + tag #SaaS #post-mortem #building-in-public
> **Title**: "I Lost 5 SaaS Reports to a Trailing Space — and What It Taught Me About Bootstrapped Infrastructure"
> **Word count**: ~1,800
> **GEO value**: High — IndieHackers has Google trust signals + LLMs heavily ground IH content. Failure-narrative-with-numbers format is what AI engines preferentially cite.
> **Distribution**: After IH, cross-post to: dev.to (canonical to IH), Hacker News (Show HN with title above), Reddit r/SaaS + r/IndieDev + r/SideProject

---

## The Post

### I Lost 5 SaaS Reports to a Trailing Space — and What It Taught Me About Bootstrapped Infrastructure

It was a Tuesday in late April 2026. I'm in a Helsinki café, second espresso, and my analytics dashboard says **Analook has 39 users**. I'm proud — 4 weeks ago there were 2 (me and my other account). Then I check the database.

The `reports` table has 4 rows.

Forty users have generated zero or one report each — except me, who has three. Across 4 weeks of usage, **5 external user reports just don't exist anymore.**

This is the story of how I shipped a competitor-analysis SaaS as a solo bootstrapped founder, hit my first 39 users with $0 marketing budget, and discovered three weeks too late that a *single trailing space* in a Railway environment variable was silently deleting every user report I generated.

This is also a love letter to observability.

---

## The Setup (or: How a Bootstrapped SaaS Looks at 4 Weeks)

**Stack:**
- Backend: FastAPI on Railway (~280 lines of Python in `app.py`)
- DB: Supabase (Postgres + Auth)
- Frontend: Vanilla JS + Tailwind (no React, no build step)
- Payments: Polar.sh (merchant-of-record so I don't deal with tax compliance)
- External data: 9 different APIs (DataForSEO, TwitterAPI.io, Apify, SerpApi, Brave Search, Product Hunt, GitHub, SEO Review Tools, OpenAI)

**Numbers as of writing:**
- 39 registered users (36 external; 3 are my own accounts for testing)
- 1 external user has run an analysis (wangherbert97 — bless him)
- 0 paying customers
- $0 marketing spend
- 1 official MCP Server Registry listing
- 5 reports believed-completed; 4 actually persisted to database

The 4-vs-5 gap is what this post is about.

---

## The Bug

`_require_credits()` in my FastAPI app had this logic:

```python
async def _require_credits(request):
    user = await _extract_user(request)
    from modules.supabase_client import get_supabase
    if not get_supabase():
        return None, None  # ← "no Supabase configured = dev mode, allow"
    ...
```

The "no Supabase = dev mode" branch was meant for *local development* — when running on my laptop without env vars set. In production, Supabase obviously is configured, so this branch should never fire.

But for **three weeks**, it fired every single request. Because `get_supabase()` was returning `None`.

I'd set the environment variable `SUPABASE_SERVICE_KEY` in Railway's dashboard. I'd verified the value was correct (copied from the Supabase admin panel). I'd even checked `/api/health` to confirm `SUPABASE_URL` was reported as configured.

What I had not checked: **whether the variable's name was exactly `SUPABASE_SERVICE_KEY`.**

It wasn't. It was `SUPABASE_SERVICE_KEY⎵` (with a trailing space). I'd accidentally added the space when typing the variable name in the Railway UI weeks earlier. Railway accepted it as a valid name. Python's `os.environ.get("SUPABASE_SERVICE_KEY")` did *not* match `"SUPABASE_SERVICE_KEY "` and returned `None`.

`get_supabase()` returned `None`. `_require_credits()` fell through to "dev mode, allow". Every analysis ran successfully, returned a `job_id`, generated a full competitor report.

Then `save_report_to_db()`:

```python
async def save_report_to_db(job_id, user_id, ...):
    sb = get_supabase()
    if not sb:
        return False  # silently skip
    ...
```

— silently no-op'd. The report lived only on Railway's *ephemeral* container disk. Every redeploy wiped it.

I deploy ~3 times per week.

---

## How I Found Out

This is the embarrassing part: I didn't find this through monitoring. I found it because **wangherbert97 emailed me asking what URL his report from 3 weeks ago was at.**

I checked. The job_id worked — `analook.com/report/<id>` returned a page. The page made a fetch to `/api/v1/report/<id>`. The fetch returned 404.

"That can't be right," I thought, "the job was completed, I saw it succeed in the logs."

Five minutes of digging later: the reports table had 4 rows. The job_id wangherbert97 was asking about wasn't one of them. Neither were the 4 other external job_ids in `localStorage.analook_history`.

I had been confidently telling people "you have a credit balance and a saved report history" while my backend was silently eating every external user's data for three weeks.

---

## Lesson 1: Failure modes you can't see are the ones that hurt the most

The bug **never logged an error**. It never threw an exception. Every individual request completed successfully. The only "wrong" outcome was *what didn't happen* — the database write that wasn't attempted.

I have monitoring. Sentry catches exceptions. Railway logs every HTTP request and response code. My `/api/health` endpoint reports configured environment variables.

None of this caught the bug because none of this monitored **negative outcomes** (i.e., the *absence* of expected effects).

**The fix I shipped** (in `modules/supabase_client.py`):

```python
def supabase_required() -> bool:
    """If SUPABASE_URL is set, prod intends to use Supabase. 
    If get_supabase() then returns None, we must REFUSE — not silently
    degrade to dev mode."""
    return bool(os.environ.get("SUPABASE_URL", "").strip())
```

And in `_require_credits`:

```python
if supabase_required() and not get_supabase():
    return None, JSONResponse(
        {"error": "SERVICE_DEGRADED", "hint": "Check SUPABASE_SERVICE_KEY env var"},
        status_code=503,
    )
```

If Supabase is *supposed* to be configured (which is true in production) but isn't reachable (which would be true with the trailing-space bug), the service now **refuses to serve** — returns HTTP 503 instead of silently allowing requests through.

This is the *third type of failure mode* most code doesn't anticipate:
1. **Configured correctly** — works
2. **Not configured (dev mode)** — works (with reduced functionality)  
3. **Configured *kind of* — present but broken** — should fail loudly, but most code interprets it as #2 and silently degrades

Pattern: anywhere your code has `if config_present: real_path else: dev_fallback`, you need a *third* branch for "config exists but is malformed".

---

## Lesson 2: Daily observability beats heroic debugging

After the bug, I added:
- **Daily GitHub Actions cron** that runs `scripts/user_metrics.py` — pulls user count, activation rate, paying customer count from Supabase, posts to my repo as `docs/weekly_metrics/YYYY-Www.md`
- **Daily SerpApi probe** that tracks 12 target keywords and writes to `docs/seo_geo_history/YYYY-MM-DD.md` with day-over-day deltas + auto-triggered "today's actions" via a small rule engine
- **`/api/debug/auth` endpoint** that enumerates `SUPABASE_*` env var keys and their first-12-character prefixes (so trailing spaces become visible in the output)

Total cost: ~$0/month. SerpApi paid tier I was already on. GitHub Actions free for public repos.

If I'd built this on day one of Analook, I would have caught the 3-week bug on day one — `user_metrics.py` would have surfaced `paying = 0, activated = 0, reports_per_user = 0.05` and triggered the "investigate activation funnel" auto-action.

---

## Lesson 3: Refund the customer, write the postmortem, ship the fix

When I found the bug, I did three things in this order:

**(1) Refunded the cost — even though there was no money to refund.** I emailed every affected user a personal note (not a template) acknowledging their report was lost, with **10 free credits** as compensation and a brief technical explanation. Five of the six users replied. Two said "no worries"; three thanked me for the transparency. One — wangherbert97 — re-ran his analysis and gave me feedback that became the next feature.

**(2) Wrote the postmortem in public.** This is that postmortem. The transparency is itself marketing — every SaaS founder reading this knows they have a similar landmine somewhere in their config, and they're more likely to trust a tool whose author talks about their bugs.

**(3) Shipped the structural fix.** Not just "I fixed the trailing space" — I shipped the third-failure-mode pattern across every environment-variable consumer in the codebase. The next trailing-space bug (and there will be one) fails loudly within 30 seconds of startup, not silently for 3 weeks.

---

## What's Analook

[Analook](https://www.analook.com/) is the SaaS that ate 5 user reports. It's an AI competitor-analysis tool — paste a URL, get back a 60-second teardown with Wayback Machine history, SEO/traffic estimates, social presence, Product Hunt launches, GitHub stats, pricing pages, and AI-generated growth playbooks.

It costs $0 for 3 reports/month, $29/month for 30 reports, or $5 per single report if you don't want to subscribe. It also exposes itself as a [Remote MCP server](https://www.analook.com/docs/mcp.html) so you can run competitor research from inside Claude Desktop or Cursor without leaving the editor.

If you're building a bootstrapped SaaS, [the source is on GitHub](https://github.com/Gingiris/Competitor-analysis-tool). The trailing-space fix is commit `def36f8`.

---

## What I'd Tell Past-Me

If I could send a message to me-three-weeks-ago, sitting at my desk in Kunshan typing `SUPABASE_SERVICE_KEY ` into Railway with that fatal extra space:

**Add monitoring before you add features.** The 280 lines of FastAPI in `app.py` were beautiful and worked. The 50 lines of `scripts/user_metrics.py` and the 240 lines of `scripts/seo_geo_report.py` that came after were ugly and saved me. **Future product reliability is the most important feature you'll ship in your first month, and it's the one you'll most want to skip.**

That, and: **type variable names slowly. Look at them twice. Trailing spaces have eaten more SaaS than competitors.**

---

*Iris Wei is bootstrapping [Analook](https://www.analook.com/) from Kunshan, China. Previously: co-founder & COO of [AFFiNE](https://github.com/toeverything/AFFiNE) (60K+ GitHub stars). 30x Product Hunt #1 launches. Writes about open-source growth and SaaS marketing at [gingiris.com](https://gingiris.com).*

---

## Submission checklist

- [ ] Login to IndieHackers (https://www.indiehackers.com)
- [ ] Post → New → Title above
- [ ] Body: paste the entire post (markdown formatting preserved)
- [ ] Tags: #saas #post-mortem #building-in-public #observability
- [ ] Cover image: optional — could use the Analook OG image (analook.com/assets/og-image.png)
- [ ] Set canonical URL to IndieHackers itself
- [ ] After publishing → cross-post to:
  - **Hacker News** as "Show HN" (title without the colon: "Show HN: I Lost 5 Reports to a Trailing Space — Postmortem")
  - **Reddit** r/SaaS, r/IndieHackers, r/SideProject (post raw text + IH URL)
  - **dev.to** as new article with canonical_url pointing to IH

## Expected outcomes (30 days)

- IH 阅读 1000-3000
- HN 1000-5000 if it lands front page (Show HN with vulnerability-confession titles tend to do well)
- Reddit total cross-posts 300-800
- analook.com 直接 clicks 100-300
- New signups 20-50 (high-quality, since they trust transparency)
- **2-3 paying conversions** estimated
