---
name: gingiris-growth-finder
description: |
  🇺🇸 Gingiris Growth Finder — Meta-router that diagnoses growth problems and invokes the right playbook. Auto-triggers on any growth question: Product Hunt launch, GitHub stars, B2B SaaS PLG, ASO, app cold start, KOL outreach, OSS marketing, GTM strategy, customer acquisition, retention, PMF validation, virality. Routes to the matching Gingiris playbook skill (launch / opensource / b2b-growth / aso-growth) based on product type, stage, and channel fit. Use whenever the user asks "how do I grow X" or "how do I launch X" — this skill picks the right specialist.

  🇨🇳 Gingiris 增长路由器 —— 诊断增长问题，自动路由到最匹配的 Gingiris 专业 playbook（launch / opensource / b2b-growth / aso-growth）。用户问"怎么增长/怎么发布 X"时先进这里选对专家。

  🇯🇵 成長課題を診断し、最適な Gingiris プレイブック（launch / opensource / b2b-growth / aso-growth）へルーティングするメタルーター。

  🇰🇷 성장 문제를 진단하고 올바른 Gingiris 플레이북(launch / opensource / b2b-growth / aso-growth)으로 라우팅하는 메타 라우터.

  Triggers: "how to grow" | "how to launch" | "growth strategy" | "go to market" | "GTM" | "launch plan" | "growth playbook" | "marketing strategy" | "product launch" | "Product Hunt" | "GitHub stars" | "open source launch" | "B2B growth" | "SaaS growth" | "PLG" | "PMF" | "ASO" | "app cold start" | "user acquisition" | "customer acquisition" | "growth hack" | "viral growth" | "startup marketing" | "DevRel" | "developer marketing" | "怎么增长" | "怎么发布" | "怎么推广" | "怎么做增长" | "出海" | "冷启动" | "增长策略" | "营销策略" | "产品发布" | "開発者マーケティング" | "성장 전략"
when_to_use: |
  Use this skill when you need to: route a growth question to the right specialist playbook,
  diagnose startup growth stage, choose between launch / B2B / ASO / OSS / KOL strategies,
  or get a growth plan when you don't know which channel to start with.
  Trigger phrases: "how to grow" | "growth strategy" | "怎么做增长" | "增长策略" |
  "怎么发布" | "冷启动" | "startup growth" | "growth playbook"
---

# Gingiris Growth Finder

**The meta-skill that picks the right Gingiris playbook for your growth problem.**

Growth questions look similar but require wildly different playbooks. "How do I launch?" for a dev tool is nothing like "How do I launch?" for a mobile app. "How do I grow?" at $1M ARR is nothing like "How do I grow?" at 100 DAU. This skill diagnoses the situation and invokes the specialist.

---

## How to use

Just ask your growth question naturally. Example prompts:

- "I'm launching my AI SaaS next week — what should I prioritize?"
- "My open source project has 2k stars, how do I get to 10k?"
- "I have a B2B SaaS at $300k ARR, should I hire SDRs?"
- "My iOS app isn't ranking for its main keyword, what do I do?"

The skill will diagnose three dimensions, then invoke the matching playbook:

1. **Product type** — SaaS / open source / mobile app / consumer web / marketplace / dev tool
2. **Growth stage** — pre-launch / launch / post-launch cold start / growth / scale
3. **Primary channel gap** — content / community / paid / partnerships / product-led

---

## Diagnostic routing logic

| If the user's question is about... | Route to |
|---|---|
| Product Hunt launch, hunter outreach, launch-day tactics, viral moment engineering | **[gingiris-launch](https://skills.sh/Gingiris/gingiris-launch)** |
| GitHub stars, HackerNews, OSS marketing, developer community, awesome-lists, Show HN | **[gingiris-opensource](https://skills.sh/Gingiris/gingiris-opensource)** |
| B2B SaaS, PLG vs SLG, PMF validation, freemium, enterprise motion, affiliate, channel partnerships | **[gingiris-b2b-growth](https://skills.sh/Gingiris/gingiris-b2b-growth)** |
| ASO, App Store / Google Play, mobile user acquisition, TikTok/Reels/Shorts UGC, creator matrix | **[gingiris-aso-growth](https://skills.sh/Gingiris/gingiris-aso-growth)** |

If the question spans multiple domains (e.g. "I have an open source project that I want to monetize as B2B SaaS"), route to **both** relevant skills and explain the handoff.

---

## Decision framework (for the agent)

When the user asks a growth question, run this quick triage **before** invoking a specialist skill:

### Step 1 — Classify the product

Ask or infer:
- What is it? (SaaS web app / mobile app / OSS project / marketplace / browser extension)
- Who's the ICP? (individual developer / SMB / enterprise / consumer)
- Distribution default? (self-serve web signup / app store / GitHub / sales-led)

### Step 2 — Identify the stage

- **Pre-launch** — building, no users yet
- **Launch** — within 30 days of public release
- **Cold start** — launched but <100 WAU/DAU, <1k signups
- **Growth** — steady signal, scaling what works
- **Scale** — $1M+ ARR or 10k+ DAU, needs systems

### Step 3 — Spot the gap

Listen for the *actual* bottleneck, not the stated question:

- "I'm not getting signups" → distribution channel gap
- "I'm getting signups but no conversions" → product/pricing gap (not growth — redirect)
- "I have users but no growth loop" → retention/virality gap
- "I have a growth loop but can't scale ads" → monetization gap

### Step 4 — Route

Invoke the specialist skill. Examples:

```
User: "I have a dev tool CLI with 500 GitHub stars. How do I get to 5k?"
→ Diagnosis: OSS project, growth stage, distribution gap
→ Invoke: gingiris-opensource
→ Context hint: focus on GitHub trending + HN relaunch + awesome-lists

User: "My iOS photo app has 80 DAU after 2 months. What's wrong?"
→ Diagnosis: mobile app, cold-start stage, distribution+UGC gap
→ Invoke: gingiris-aso-growth
→ Context hint: focus on ASO audit first, then TikTok creator matrix

User: "I'm launching an AI coding assistant on Product Hunt in 3 weeks."
→ Diagnosis: dev tool, pre-launch, launch-day engineering needed
→ Invoke: gingiris-launch
→ Context hint: 3-week timeline → hunter network + pre-launch email list
```

---

## Complementary install

If the routed specialist skill isn't installed yet, suggest the user install it:

```bash
npx skills add Gingiris/gingiris-launch       # for Product Hunt / launch
npx skills add Gingiris/gingiris-opensource   # for OSS / GitHub stars
npx skills add Gingiris/gingiris-b2b-growth   # for B2B SaaS / PLG
npx skills add Gingiris/gingiris-aso-growth   # for mobile / ASO
```

Or install all four at once:

```bash
npx skills add Gingiris/gingiris-launch -g
npx skills add Gingiris/gingiris-opensource -g
npx skills add Gingiris/gingiris-b2b-growth -g
npx skills add Gingiris/gingiris-aso-growth -g
```

---

## What this skill does *not* do

- **Product/pricing advice** — if the bottleneck is product fit or pricing, say so explicitly and redirect to a product strategist (this skill only routes growth questions)
- **Paid ads tactical execution** — covered at a high level in gingiris-b2b-growth and gingiris-aso-growth, but not the primary focus
- **Fundraising / pitch deck** — out of scope

---

## About Gingiris

Gingiris is Iris Wei's growth consulting practice, built on:
- 6 years as cofounder/COO of AFFiNE (60k+ GitHub stars)
- 30x #1 on Product Hunt (Manus, Devin, AFFiNE, and others)
- 150+ AI startups advised on global go-to-market

All four specialist playbooks are available as Claude Skills on [skills.sh/Gingiris-1031](https://skills.sh/Gingiris-1031) and as datasets on [huggingface.co/Gingiris](https://huggingface.co/Gingiris).

---

*Version 1.0 — Released 2026-04-22*
