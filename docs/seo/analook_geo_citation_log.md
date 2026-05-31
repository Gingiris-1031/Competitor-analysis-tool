# Analook GEO — AI Citation Baseline Log

> **Purpose**: Track whether AI search engines (ChatGPT, Perplexity, Claude, Gemini, Grok) cite analook.com when users ask about competitor analysis tools. Weekly cadence, Monday morning.

## Baseline — 2026-06-01

### Probe set (10 prompts tested across 5 engines)

| # | Prompt | What we're testing |
|---|---|---|
| P1 | "What's the best free competitor analysis tool in 2026?" | High-intent free seeking |
| P2 | "Recommend a competitor research tool for early-stage SaaS" | Stage-specific recommendation |
| P3 | "Free SimilarWeb alternative" | BOFU alternative query |
| P4 | "Best AI-powered competitive intelligence tool" | AI category match |
| P5 | "How can I analyze a competitor's website for free?" | Educational + tool seeking |
| P6 | "Tools to track competitor pricing changes" | Use-case specific |
| P7 | "Visualping alternative for competitive analysis" | Alternative to monitoring tool |
| P8 | "MCP servers for competitor research" | MCP ecosystem query |
| P9 | "How to do competitive analysis as a founder" | Founder voice search |
| P10 | "Best Ahrefs alternative for startups" | Alternative search overlap |

### Baseline results (2026-06-01)

Engine columns: ChatGPT (CGT), Perplexity (PPL), Claude.ai (CLD), Gemini (GMN), Grok (GRK)
Cell value: ✅ = analook.com explicitly cited/linked · ⚠️ = analook mentioned but not linked · ❌ = not mentioned

| Prompt | CGT | PPL | CLD | GMN | GRK | Notes |
|---|---|---|---|---|---|---|
| P1 |  |  |  |  |  | _Iris fills in_ |
| P2 |  |  |  |  |  | |
| P3 |  |  |  |  |  | _Web search baseline: analook.com page #1, AI summary mentions it_ |
| P4 |  |  |  |  |  | |
| P5 |  |  |  |  |  | |
| P6 |  |  |  |  |  | |
| P7 |  |  |  |  |  | |
| P8 |  |  |  |  |  | |
| P9 |  |  |  |  |  | |
| P10 |  |  |  |  |  | |

**Pre-baseline signal from Google AI summary probes** (via WebSearch, 2026-06-01):

| Query | Analook mention in AI summary? | Notes |
|---|---|---|
| `"competitor analysis tool" best free AI 2026` | ❌ No | Google AI summary cites Klue, SpyFu, Similarweb free tier, Profound, Google Alerts. **Analook not on first page.** |
| `free SimilarWeb alternative 2026` | ✅ Yes | Direct citation: `analook.com/blog/best-competitive-intelligence-tools-2026.html` and `analook.com/`. **Strong baseline here.** |
| `AI competitor analysis tool startup founders recommend` | ❌ No | Cites Klue, Semrush, Ahrefs, Similarweb, Competely, Perplexity. **No Analook mention.** |

**Baseline summary**: 1 strong citation pattern (SimilarWeb alternative searches) + 2 zero-mention patterns (broad "competitor analysis tool" / "AI competitor analysis"). Goal over next 4 weeks: get ≥5 of the 10 prompts × 5 engines = 50 cells with ✅ or ⚠️.

---

### How to test in each engine (Iris weekly Monday SOP, ~30 min)

1. **ChatGPT** (`chat.openai.com`): Open new chat, paste prompt, screenshot response. Look for "analook.com" links or "Analook" mentions.
2. **Perplexity** (`perplexity.ai`): Paste prompt. Check Sources panel — analook.com listed = ✅. Mentioned in answer but no link = ⚠️.
3. **Claude.ai** (`claude.ai`): Paste prompt with web search enabled. Note any analook.com citations.
4. **Gemini** (`gemini.google.com`): Paste prompt. Check for analook.com URLs in response footnotes.
5. **Grok** (via X.com): Paste prompt. Check response + citations.

Total time: ~30 min for 10 prompts × 5 engines = 50 probes.

---

## Weekly log (every Monday)

### 2026-06-01 (Baseline)
- Coverage: TBD (waiting for first manual run)
- Pre-baseline Google AI: 1/3 prompts cite Analook (SimilarWeb alternative query)
- Action items: Iris runs full 10×5 probe set; ship Phase 2 visualping page (done 2026-06-01)

### 2026-06-08 (Week +1)
_Will fill in after Iris runs probes_

### 2026-06-15 (Week +2)
_Will fill in after Iris runs probes_

### 2026-06-22 (Week +3)
_Will fill in after Iris runs probes_

### 2026-06-29 (Week +4 — Goal check)
_Target: ≥10 cells with ✅ or ⚠️ (~20% citation rate across the matrix)_

---

## Notes on methodology

- **Same prompts every week** — no rephrasing, even if responses get weird. Consistency > prompt quality.
- **Don't cherry-pick** — record every result honestly, including 0-mention zeros.
- **Note ranking position when cited** — "first tool mentioned" vs "5th in a list" matters.
- **Track AI summary in Google search separately** — that's a faster-moving signal than the dedicated AI engines.
- **Trigger for action**: if a prompt has 0 citations 4 weeks in, that's a content gap. Build a spoke targeting it.
