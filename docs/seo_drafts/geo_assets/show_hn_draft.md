# Show HN Submission Draft

> **Target**: https://news.ycombinator.com/submit
> **Best time to post**: Monday or Tuesday, 09:00-11:00 PT (UTC-7) → that's 17:00-19:00 Helsinki / 00:00-02:00 Kunshan
> **Account requirement**: HN account with non-zero karma submits to Show HN show as default. Brand-new accounts get sandboxed.

---

## Title (3 candidates, A/B think)

**A (RECOMMENDED — failure-narrative angle, highest HN compatibility)**
```
Show HN: I exposed my SaaS to AI agents in 200 lines (lost 5 reports to a Railway bug)
```

**B (technical angle)**
```
Show HN: Analook MCP — competitor analysis from Claude Desktop in a single tool call
```

**C (developer-tool angle)**
```
Show HN: A Remote MCP server for competitor analysis (FastAPI + 280 lines)
```

**Recommend A.** HN audience preferentially upvotes posts with:
- Specific failure numbers (5 reports lost)
- Concrete code volume (200 lines)
- Honest about the bug (trust signal)
- Title structure that's both a feature announcement AND a war story

---

## Text body (optional — most "Show HN: <title>" posts use just the URL field. But if you choose to add text):

```
Hi HN — I'm Iris, ex-AFFiNE COO, and I built Analook (analook.com) — an AI competitor-analysis tool — as a solo bootstrapped project.

Yesterday I shipped a Remote MCP server so you can run competitor teardowns from inside Claude Desktop / Cursor without context-switching. The endpoint is at analook.com/mcp, listed on the official MCP Registry (io.github.Gingiris/analook).

5 tools:
- analyze_competitor(url) — full teardown
- get_report_status / get_report / get_report_markdown
- list_my_reports

Config block goes in claude_desktop_config.json:
{
  "mcpServers": {
    "analook": {
      "url": "https://analook.com/mcp",
      "headers": {"Authorization": "Bearer <token>"}
    }
  }
}

The full story including 3 review-found bugs (progress schema crash, job_id collision, SSRF in URL parsing) and 1 prod-found bug (3-week silent failure due to a Railway env var with a trailing space that ate 5 user reports) is in this writeup:

[link to growth-tools blog post or IH story]

Source: github.com/Gingiris/Competitor-analysis-tool
Setup docs: analook.com/docs/mcp

Happy to answer technical questions about the FastMCP integration, Starlette middleware for Bearer auth into ContextVars, or how I caught the trailing-space bug.
```

## ⚠️ Iris pre-submission checklist

- [ ] **Use the URL field** as the primary submission — point it to the IndieHackers post (better than analook.com itself, because HN audience reads stories more than landing pages)
- [ ] **HN account karma check** — make sure account is at least a few days old with some prior submissions (avoid sandbox)
- [ ] **Timing** — Aim for **Tuesday 9-10am PT** (highest HN traffic, lowest competition). That's:
  - Helsinki: 19:00-20:00 Tuesday
  - Kunshan: 00:00-01:00 Wednesday
- [ ] **First 90 minutes are critical**: be available to reply to comments. HN auto-throttles posts with no author engagement.
- [ ] **No self-upvote ring** — HN detects this. Just be real.
- [ ] **If it doesn't take off in 2 hours** → try again the next Tuesday with a different title

## Backup plan if HN doesn't catch

- **Plan B**: Post to /r/SaaS as "I built a Remote MCP server for competitor analysis (lost 5 reports learning how)" — same body
- **Plan C**: Post to /r/IndieDev as "Postmortem: I exposed my SaaS to AI agents in 200 lines"
- **Plan D**: Wait 1 week, repost to HN with title B or C

---

# Twitter Launch Thread (10 推)

Post from @gingiris1031 (or whatever your X handle is). Same time-of-day rules as HN — Tuesday 9-10am PT.

```
1/

I shipped my first Remote MCP server today.

Now you can run competitor analysis from inside Claude Desktop:

"hey Claude, teardown lovable.dev"

→ 3 minutes later, full report inside the conversation. No tab-switching. No copy-paste.

It cost me 5 reports to ship. Thread 🧵

2/

Background: I'm building Analook (analook.com) — a competitor analysis tool. Solo bootstrapped. 39 users in 4 weeks of $0 marketing.

Last week, I exposed Analook's 5 tools (analyze_competitor, get_report, etc.) as MCP tools.

Spec-compliant. On the official MCP Registry. 280 lines of Python.

3/

The architecture:

FastMCP's streamable_http_app() → mounted on existing FastAPI at /mcp
Starlette middleware → grabs Authorization: Bearer → stashes in ContextVar
Each tool reads token → verifies via Supabase → runs same code path as the HTTP API

Boring. Reliable. Done in a weekend.

4/

But three bugs almost shipped.

Bug 1: progress schema mismatch. MCP tool wrote `progress: "starting..."` (string). HTTP path expected `progress: {website, social, social, ...}` (dict). First user request would have crashed silently in the background task.

5/

Bug 2: job_id collision. I used uuid4().hex[:8] for the MCP-issued IDs. Worked fine — until you realized HTTP-path jobs ALSO use the shared dict. Two users get same job_id → user A sees user B's report.

That's not a crash. That's a privacy leak.

Caught in review. Now uses full UUID.

6/

Bug 3: SSRF in URL parsing. The MCP `analyze_competitor` tool takes a URL. Stdlib urlparse accepts:
- file:///etc/passwd
- javascript:alert(1)  
- http://localhost:8080/admin

Without scheme allowlisting, an attacker could have made my server fetch local files.

7/

All three caught BEFORE deploy because I run independent code review on every commit. The agent that writes is the wrong agent to review.

But one bug got past review and into production: SUPABASE_SERVICE_KEY in Railway had a TRAILING SPACE in the variable name.

8/

You can't see trailing spaces in Railway's UI. So os.environ.get("SUPABASE_SERVICE_KEY") returned None for THREE WEEKS.

Supabase client failed to init silently. _require_credits fell through to "dev mode, allow". save_report_to_db() no-op'd.

5 user reports lost. Forever.

9/

The fix: any time you have `if config_present: real else: dev_fallback`, you need a THIRD branch for "config exists but is broken". 

Code: 
- if SUPABASE_URL is set AND get_supabase() is None → return 503 SERVICE_DEGRADED
- never silently degrade in prod

10/

Try it yourself:

Drop this in claude_desktop_config.json:

{
 "mcpServers": {
  "analook": {
   "url": "https://analook.com/mcp",
   "headers": {"Authorization": "Bearer <token>"}
  }
 }
}

Source: github.com/Gingiris/Competitor-analysis-tool
Docs: analook.com/docs/mcp
Full post: [growth-tools URL]

Built (transparently) by @gingiris1031. /end
```

---

## ⚠️ Iris twitter pre-publish checklist

- [ ] **Replace `@gingiris1031` with your actual X handle** in tweet 10
- [ ] **Replace `[growth-tools URL]` in tweet 10** with the actual URL of the mcp-server-saas-200-lines blog post on gingiris.github.io after Jekyll builds it
- [ ] **Tweet 1 must be ≤280 chars** — I'm right at the limit; check before posting
- [ ] **Add a quote-tweet of tweet 1 from your @analook account** (if you have one) for cross-account reach
- [ ] **Pin tweet 1** to your profile for 7 days after posting
- [ ] **Reply to first 20 reactions** within 30 minutes — Twitter's algorithm rewards immediate engagement

## Best time to post

Optimal: **Tuesday 16:00-18:00 ET (US East Coast)** which is:
- Helsinki: 23:00-01:00 Tuesday→Wednesday  
- Kunshan: 04:00-06:00 Wednesday morning

Sub-optimal but acceptable: **Wednesday 09:00-11:00 PT** (same as HN timing).

---

## Expected outcomes (combined HN + Twitter, 7 days)

| Metric | Conservative | Expected | Optimistic |
|--------|------|----------|------------|
| HN front page (top 30) | 20% chance | 50% chance | 90% chance |
| Total cross-post + HN combined views | 5,000 | 25,000 | 100,000 |
| analook.com clicks | 200 | 800 | 3,000 |
| New signups | 10 | 40 | 150 |
| **Paying conversions** | **1-2** | **3-5** | **8-12** |
| GitHub stars on Competitor-analysis-tool | +5 | +50 | +500 |

**Best case**: this single distribution event = half of the 30-day "10 paying customers" target.
