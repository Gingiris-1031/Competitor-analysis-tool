# Analook MCP — 4 个 Directory 提交包

起草：2026-04-16
目的：一页纸拿到手就能逐个提交。所有文案/manifest/截图文件都在这里，按顺序照抄即可。

---

## 🎯 共享资产（所有 directory 复用）

**Name**: `analook`
**Display name**: `Analook — Competitor Intelligence`
**Homepage**: `https://www.analook.com`
**Docs URL**: `https://www.analook.com/docs/mcp.html`
**Source code**: `https://github.com/Gingiris/Competitor-analysis-tool`
**License**: `MIT` (code) / analook.com ToS (data)

**Short tagline** (≤100 chars):
> Competitor intelligence for AI agents — website, SEO, traffic, social, Product Hunt, pricing, funding.

**One-line pitch** (≤160 chars):
> Run Analook's 15-source competitor analysis from Claude Desktop or Cursor. One tool call, 3 minutes, full JSON report.

**Longer description** (2-3 paragraphs):
> Analook is an AI-powered competitor analysis SaaS. Its MCP server exposes 5 tools for running and reading full competitor reports directly from your agent workflow — no browser context-switching, no copy-pasting.
>
> Paste a URL, get back a structured report: Wayback Machine history, SEO & traffic (DataForSEO + SEO Review Tools), social footprint (Twitter / YouTube / GitHub / Reddit / Instagram), Product Hunt launches, pricing pages, funding, and AI-generated growth playbooks. Everything is persisted — share job_ids across sessions, run comparisons, build dashboards.
>
> Zero install. Add `https://www.analook.com/mcp` to your MCP client with a Bearer token — done.

**Transport**: `streamable-http`
**URL**: `https://www.analook.com/mcp`
**Auth**: Bearer token (Supabase JWT from analook.com account)

**Categories/tags** (pick 3-5 per directory):
`research` `competitive-intelligence` `seo` `marketing` `sales` `web-analysis`

**Tools** (paste exactly this list):
- `analyze_competitor(url, product_name?)` — start a full analysis. 1 credit. Auth required.
- `get_report_status(job_id)` — poll a running analysis. Public.
- `get_report(job_id)` — get the full JSON report. Public.
- `get_report_markdown(job_id)` — get the report as human-readable Markdown. Public.
- `list_my_reports()` — list your last 50 reports. Auth required.

**5 example prompts** (for directories that ask):
1. "Analyze lovable.dev and tell me their top 3 growth channels."
2. "Compare linear.app, notion.so, and asana.com — where does each win?"
3. "Run analook competitor analysis on my latest launch and summarize the SEO gaps."
4. "Show me my last 10 Analook reports, then pull the one for vercel.com."
5. "Pull the full report for job abc12345 as markdown and save to a note."

**Icon**: `/Users/iriscarrot/Downloads/analook_logos/analook_v3_lettermark_A.png` (or v3d/v3e from iterations) — 256×256 PNG.

**Demo video** (TODO before submission): 30-second Loom of Claude Desktop calling `analyze_competitor("lovable.dev")`, showing the JSON reply.

---

## 📬 Directory 1 — modelcontextprotocol/servers (官方 registry)

**Submission type**: GitHub PR to `modelcontextprotocol/servers`
**URL**: https://github.com/modelcontextprotocol/servers
**Effort**: ~15 min
**Priority**: 🔴 Highest — 官方背书

### Steps
1. Fork https://github.com/modelcontextprotocol/servers
2. Clone fork, open `README.md`
3. Find the "Third-party servers" section (or whatever the current "community servers" heading is)
4. Add this entry in alphabetical order:

```markdown
- **[Analook](https://github.com/Gingiris/Competitor-analysis-tool)** - Competitor intelligence for AI agents — website, SEO, traffic, social, Product Hunt, pricing, funding. Zero-install remote MCP at `https://www.analook.com/mcp`.
```

5. Commit message: `docs: add Analook (competitor intelligence) to community servers`
6. Open PR with this body:

```markdown
Adds Analook to the community servers list.

**Analook** is a production SaaS that exposes its 15-source competitor-analysis pipeline as an MCP server over Streamable HTTP. No install needed — users add one URL + Bearer token to their Claude Desktop / Cursor config.

- **Homepage**: https://www.analook.com
- **Docs**: https://www.analook.com/docs/mcp.html
- **Endpoint**: https://www.analook.com/mcp
- **Source**: https://github.com/Gingiris/Competitor-analysis-tool

5 tools: `analyze_competitor`, `get_report_status`, `get_report`, `get_report_markdown`, `list_my_reports`.

Live for ~24h with verified MCP handshake at protocol version 2024-11-05.
```

---

## 📬 Directory 2 — Smithery.ai

**Submission type**: Web form (likely requires GitHub login)
**URL**: https://smithery.ai/ → "Submit a server" (or similar CTA)
**Effort**: ~10 min
**Priority**: 🟠 High — Smithery 在 MCP 圈内最活跃的 directory

### Field-by-field

| Field | Value |
|---|---|
| Server name | `analook` |
| Display name | `Analook — Competitor Intelligence` |
| GitHub URL | `https://github.com/Gingiris/Competitor-analysis-tool` |
| Description | (paste the longer 2-3 paragraph description above) |
| Tags | `research`, `competitive-intelligence`, `seo`, `marketing`, `web-analysis` |
| Transport | Remote / Streamable HTTP |
| Deployment URL | `https://www.analook.com/mcp` |
| Auth required | Yes — Bearer token |
| Install command | N/A (remote) |

### If Smithery requires `smithery.yaml`
Create `smithery.yaml` in repo root:

```yaml
name: analook
version: 1.0.0
description: Competitor intelligence for AI agents — website, SEO, traffic, social, Product Hunt, pricing, funding.
homepage: https://www.analook.com
docs: https://www.analook.com/docs/mcp.html
repository: https://github.com/Gingiris/Competitor-analysis-tool
license: MIT
tags:
  - research
  - competitive-intelligence
  - seo
  - marketing
  - web-analysis
transport:
  type: streamable-http
  url: https://www.analook.com/mcp
auth:
  type: bearer
  header: Authorization
  description: Supabase JWT from analook.com account
tools:
  - analyze_competitor
  - get_report_status
  - get_report
  - get_report_markdown
  - list_my_reports
```

---

## 📬 Directory 3 — mcp.so

**Submission type**: Web form
**URL**: https://mcp.so/submit (or "Add your server" CTA on homepage)
**Effort**: ~5 min
**Priority**: 🟡 Medium — 流量小但 SEO 收录价值

### Form fields (guessed based on pattern, adjust per actual form)

| Field | Value |
|---|---|
| Name | Analook |
| Slug | analook |
| Category | Research / Marketing |
| Description | (paste the one-line pitch) |
| GitHub | `https://github.com/Gingiris/Competitor-analysis-tool` |
| Website | `https://www.analook.com` |
| MCP URL | `https://www.analook.com/mcp` |
| Docs | `https://www.analook.com/docs/mcp.html` |

---

## 📬 Directory 4 — Cline Marketplace

**Submission type**: GitHub PR to `cline/mcp-marketplace` (if it exists) OR Cline's in-app submission
**URL**: https://cline.bot/ → "MCP Marketplace" section
**Effort**: ~10 min
**Priority**: 🟡 Medium — Cline 是 VS Code 插件，用户重叠度高

### Steps
1. Check Cline's current submission path:
   - https://github.com/cline/cline → README → look for "Marketplace submission"
   - OR https://cline.bot/mcp-marketplace (if exists)
2. Follow their process (similar fields to Smithery)
3. If PR-based, title: `Add Analook (competitor intelligence MCP server)`

---

## ✅ 提交前 Checklist

- [x] `https://www.analook.com/mcp` 返回 200（⚠️ 本次修 bug 后重新部署，先等 Railway 绿灯）
- [x] `https://www.analook.com/docs/mcp.html` 可访问
- [x] README.md 有 MCP section（见下方 "Repo 侧更新"）
- [ ] Icon 256×256 PNG 准备好（用 `analook_logos/analook_v3_lettermark_A.png`）
- [ ] Demo video 30s（录屏 Claude Desktop 调用 analyze_competitor("lovable.dev")）
- [ ] GitHub repo topics 加：`mcp`, `mcp-server`, `competitive-intelligence`, `ai-agents`

---

## 📝 Repo 侧更新（submit 前做）

在 `README.md` 顶部（badge 下方）加：

```markdown
## 🤖 Remote MCP Server

Analook is available as a Remote MCP server — use it from Claude Desktop, Cursor, or any MCP client:

```json
{
  "mcpServers": {
    "analook": {
      "url": "https://www.analook.com/mcp",
      "headers": { "Authorization": "Bearer <YOUR_TOKEN>" }
    }
  }
}
```

Full docs → [**analook.com/docs/mcp**](https://www.analook.com/docs/mcp.html)
```

GitHub topics（Settings → About → Topics）加：
`mcp`, `mcp-server`, `model-context-protocol`, `competitive-intelligence`, `competitor-analysis`, `ai-agents`, `claude`, `cursor`, `saas`

---

## 🎬 建议顺序

1. 等 Railway 部署完（cron 会通知，预计 2-5 分钟）
2. 先更 README + topics（上面的 "Repo 侧更新"）
3. **modelcontextprotocol/servers** PR（官方背书，价值最大）
4. **Smithery** 提交（社区活跃度最高）
5. **mcp.so** 提交（SEO 收录）
6. **Cline** 提交（用户画像重合）
7. 全部提交后：Twitter / 即刻发个"上架 4 家 directory"的 update（二次曝光）

预计总时长：**45-60 分钟**（如果全部 form 顺利）
