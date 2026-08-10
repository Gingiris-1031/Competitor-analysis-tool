# Analook SEO Ranking & Conversion Dashboard

Weekly cadence: update before the weekly meeting using the same Google US / English / desktop tracking setup. Compare the latest complete 7-day GSC window with the previous 7 days.

## Weekly headline

| Week ending | Top 10 keywords | Top 20 keywords | Non-brand clicks | Target-page impressions | Target-page CTR | CTA clicks | Sign-ups | AI citations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08-07 baseline | 0 | 0 | Pending (88 total-site clicks shown in GSC) | Pending (141K total-site impressions shown in GSC) | Pending (~0.06% total-site rough baseline) | Pending GA4 | Pending GA4 | Pending |

> The 88 clicks and 141K impressions are total-site figures visible in GSC, not non-brand or four-page totals. Replace them with exported page/query data when available.

## Four-keyword scoreboard

| Keyword | Landing page | Volume | KD | Current rank | WoW | Top 10? | Impressions | Clicks | CTR | CTA clicks | Sign-ups | Next action |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---|
| semrush alternative | `/alternatives/semrush.html` | 1.3K | 0 | #76 | — | No | Pending | Pending | Pending | Pending | Pending | Strengthen BOFU intent and links; target Top 20 |
| competitive analysis template | `/blog/competitive-analysis-template-2026.html` | 1.6K | 14 | Off-100 | — | No | Pending | Pending | Pending | Pending | Pending | Template + examples cluster; target Top 20 |
| competitive analysis tools | `/research/best-competitor-analysis-tools-2026.html` | 1.3K | 20 | Off-100 | — | No | Pending | Pending | Pending | Pending | Pending | Add evidence and comparison methodology |
| competitive intelligence | `/blog/best-competitive-intelligence-tools-2026.html` | 1.9K | 15 | Off-100 | — | No | Pending | Pending | Pending | Pending | Pending | Align definition and workflow intent |

## Weekly meeting decisions

1. Which keyword moved closest to Top 10, and what caused the movement?
2. Which page gained impressions but failed to gain clicks?
3. Which CTA generated clicks and completed sign-ups?
4. Which one P0 change will be shipped this week?
5. Did any target page fail indexing, canonical, sitemap, or AI-citation checks?

## Success rules

- Ranking without non-brand clicks is not a win.
- Clicks without meaningful CTA engagement are incomplete.
- Primary 30-day target: all four keywords measured consistently, 3–4 in Top 20, and at least 1–2 in Top 10.
- Do not change the tracked keyword set during the first 30-day sprint unless the search intent is proven wrong.
- Record the change date for every title, content, internal-link, or CTA experiment and allow at least 14 days before judging CTR unless there is a technical error.

## CTA attribution

- `utm_source=seo`
- `utm_medium=organic`
- `utm_campaign=seo-[keyword-cluster]`
- `utm_content=cta-nav|cta-tldr|cta-mid|cta-foot|cta-pricing`

GA4 should report the funnel: organic landing session → CTA click → sign-up start → sign-up complete. Until events are configured, UTM landing sessions are a temporary proxy, not a conversion metric.
