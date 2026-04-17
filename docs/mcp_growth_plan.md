# Analook MCP → 50 用户增长计划

> 起草：2026-04-16
> 目标：8 周内，让 50 个真实用户把 Analook MCP 配进他们的 Claude Desktop / Cursor，并至少调用过 1 次 `analyze_competitor`。
> 负责人：Iris · 单人 5–10h/周

---

## Key Stats（基线）

| 指标 | 今日 | 8 周目标 |
|---|---:|---:|
| MCP 独立配置用户（Bearer token 有效调用） | 0 | 50 |
| MCP 日活用户（DAU） | 0 | 8 |
| MCP directory 收录数 | 0 | 4+ |
| 站外反链提到 "Analook MCP" | 0 | 20+ |
| `/docs/mcp` 月访问 UV | — | 600 |

---

## 判断前提（4 月中旬时点）

- Claude Desktop 的 Remote MCP 支持稳定至少 6 个月了，用户习惯养成（不再"装 plugin 是极客行为"）
- MCP directory 生态初步成型——modelcontextprotocol.io 官方 registry、Smithery、mcp.so、Cline 的 marketplace 都在跑
- **决定性事实**：我们是目前**唯一**一个给"竞品分析"做 MCP 的 SaaS（搜了 Smithery + mcp.so + GitHub topic=mcp-server，没看到对标）。这个窗口不会开太久
- 所以策略是：**先占类目关键词 + 先写 setup 教程 + 先进 directory**，用 SEO/GEO 长尾承接未来半年的需求，而不是靠一次 launch 的爆发

---

## 核心假设 ÷ 验证方式

| 假设 | 怎么验证 | 失败判据（要转向） |
|---|---|---|
| 用 Claude Desktop/Cursor 做产品研究的人存在一批，愿意把竞品分析嵌进 agent workflow | 看前 20 个用户是不是这类画像 | 第 4 周仍 <10 用户且来源分散 |
| "竞品 MCP" 比 "竞品 SaaS" 对 AI 原生用户更好卖（他们烦于切 tab） | MCP 用户 → Pro 付费转化率 ≥ Web 用户 × 1.5 | 第 8 周 MCP 付费转化率 ≤ Web |
| SEO 长尾词可承接（"mcp for competitor analysis"、"claude desktop competitor research"） | 2 周内排名进前 20 | 4 周仍在前 50 之外 |

---

## 分渠道拆解（8 周 × 5 个动作）

### 动作 1：MCP Directory 占位（Week 1，一次性）

目标收录：**4 个 directory**，全部放在第一周跑完。

| Directory | 状态 | 行动 |
|---|---|---|
| [modelcontextprotocol.io](https://modelcontextprotocol.io) 官方 registry | 待提交 | 开 PR 到 `modelcontextprotocol/servers` repo，加到 "Third-party servers" |
| [Smithery.ai](https://smithery.ai) | 待提交 | 上传 manifest，tag: `research`, `seo`, `competitor-analysis` |
| [mcp.so](https://mcp.so) | 待提交 | 直接在站内表单提交 |
| [Cline marketplace](https://cline.bot) | 待提交 | 同上 |

每个 directory 提交都要把 icon / tagline / 5 个示例 prompt 准备好：

> *Tagline 草稿*：Run Analook's 15-source competitor analysis from inside Claude Desktop or Cursor. One tool call, 3 minutes, full JSON report with SEO / traffic / social / Product Hunt data.

**预期转化**：每个 directory 稳定引来 1–3 用户/月。4 个 × 2 个月 ≈ **15 用户**

### 动作 2：Launch 内容三连（Week 1–2）

一篇技术向 + 一篇产品向 + 一个 30 秒 demo，同步发 4 个地方：

**内容 A — 技术向**：《Adding a Remote MCP to our SaaS in 200 lines — here's the 3 bugs we hit》
- 发布：dev.to/iris1031 → Hacker News "Show HN" → Twitter thread
- 锚点：ship flow + 独立 reviewer 找出的 3 个 bug（progress schema / job_id collision / SSRF）、lifespan 坑、starlette 版本冲突
- 读者：AI/SaaS 工程师；痛点是"给自家 SaaS 加 MCP 该从哪开始"
- 差异化：**不教你写 hello world**，教你避开真实踩过的坑

**内容 B — 产品向**：《我把竞品分析塞进了 Claude Desktop——下次再没人问我对手在干嘛》
- 发布：即刻 + 小红书 + Twitter（中英两版，放 growth-tools 博客）
- 锚点：用户故事 — 过去每周开 15 个 tab 刷对手，现在 "hey claude, 分析下这 3 家然后告诉我我在哪掉队"
- CTA：配置链接 → /docs/mcp

**内容 C — 30 秒 demo 视频**
- 录屏 Claude Desktop 调用 Analook MCP → 3 min 后看报告，快进剪到 30s
- 挂：Twitter 主推 + Loom + YouTube short + 博客嵌入
- 文案：*"Claude just analyzed 3 of my competitors while I made coffee. This is the MCP config." ↓ 附配置截图 ↓*

**预期转化**：HN 中峰（20-50 名）→ 500 UV；Twitter thread 300 UV；即刻/小红书 200 UV。综合 **10–15 用户**

### 动作 3：SEO/GEO 长尾占位（Week 2 起，持续）

目标关键词（按优先级）：

| 关键词 | 月搜索量估计 | 当前排名 | 目标 |
|---|---:|---:|---:|
| mcp server for competitor analysis | 低 但精准 | — | 第 1 |
| claude desktop competitor research | 低 但精准 | — | 前 3 |
| analook mcp | 品牌词 | — | 第 1 |
| remote mcp examples saas | 中 | — | 前 10 |
| cursor mcp competitive intel | 低 但精准 | — | 前 5 |

战术：
- `/docs/mcp` 页本身做 SEO 优化：H1 含关键词、FAQ schema、sitemap 注册、首屏 300 词内容
- growth-tools 博客（Gingiris/growth-tools）新增 2 篇：《MCP for SaaS 出海 — 为什么 2026 年你必须有一个》+《Cursor 用户的 12 个必装 MCP，#7 改变了我做竞品的方式》
- 用 SerpApi 两周追一次排名（已接入 analook 流程），跟踪表合并进 seo_tracker_baseline

**预期转化**：8 周后 SEO 日 UV ≈ 20，转化率 5% → **~8 用户**

### 动作 4：社区点对点（Week 2–6，每周 3–5 次）

不是发广告，是**在对的场子答对的问题**：

- **Cursor Discord** "#showcase"：发 demo 视频 + 简短用例
- **Claude Discord** & Reddit r/ClaudeAI：回答 "有没有能做竞品分析的 MCP" 类帖子
- **n8n 社区**：MCP 能插 n8n workflow，目标用户画像重合度高
- **即刻 AI agent 圈子**：中文市场，小红书同步
- **Indie Hackers**：发 "Building in public — 为啥给 SaaS 加 MCP"

**原则**：一次最多 1–2 个平台，不群发；所有帖子带 `/docs/mcp` 链接；回复要先给价值再给链接。

**预期转化**：每周平均 3 个精准用户 × 4 周 = **~12 用户**

### 动作 5：1-to-1 定向邀请（Week 3–5）

50 人名单，手动触达：

- 过往 Analook Web 用户里有 GitHub profile 的（看 OSS 活跃度） → 10 人
- Twitter 上发过"Claude MCP / Cursor MCP"推文的 ≥ 100 粉 builder → 20 人
- 做 AI 产品的独立开发者、SaaS 创始人 → 10 人
- 出海社区（"出海笔记"、Gingiris 旧联系人） → 10 人

**消息模板**（英文版，1-to-1 改词）：
> Hey {name} — saw your {specific tweet/repo about MCP / agent workflows}. We just shipped a Remote MCP for Analook (competitor analysis tool). Since you use {Claude Desktop / Cursor}, curious if it'd fit your workflow. Free Pro access for early feedback — here's the config: {link}. No obligation, just want to know if this is useful to someone who's not me.

**预期转化**：50 触达 × 15% 配置成功率 × 60% 真跑一次 = **~5 真用户**

---

## 8 周周历

| 周 | 主要交付 | 累计用户目标 |
|---|---|---:|
| 1 | 4 directory 全提交；`/docs/mcp` SEO 优化；demo 视频成片 | 5 |
| 2 | 内容 A（dev.to + HN）；内容 B（博客中英）；关键词追踪起线 | 12 |
| 3 | Cursor Discord + r/ClaudeAI 首批答题；1-to-1 前 15 人 | 20 |
| 4 | **中间复盘**：看 50 目标是否在轨；决定要不要加 Pro 免费促销 | 28 |
| 5 | 1-to-1 剩下 35 人；加一篇 "MCP 进阶玩法"博客 | 36 |
| 6 | n8n / IH 社区露出；如果有用户发推就转发并回谢 | 42 |
| 7 | 收集前 40 用户的反馈 → 写 `feedback_mcp_users.md` 入 memory | 46 |
| 8 | 发"50 用户总结"帖（产品向 + 数据透明） → 复用做下一轮 launch | 50 |

---

## 风险 & Plan B

| 风险 | 概率 | Plan B |
|---|---|---|
| MCP 生态发展不如预期，用户基数本身就少 | 低 | 不改方向，延长周期到 12 周 |
| Token 1 小时过期是硬伤，转化漏斗漏水 | 中 | 优先级拉满，Week 3 前上 long-lived API key |
| HN 不火，内容没声量 | 高 | 不重发，走 SEO 长线；靠 directory + 社区兜底 |
| 竞品 N 周内也出 MCP | 中 | 加速写"为什么是 Analook 而不是 X"对比内容 |
| 用户装了但不用 | 中 | 第二次触达：邮件 + "你的 `list_my_reports` 是空的，要不要试试 analyze linear.app？" |

---

## 每周 Review 问自己 3 个问题

1. 这周加了几个**有效用户**（配置 + 至少跑一次）？
2. 这周新增的**长尾资产**（博客、视频、directory 收录、外链）是什么？
3. 前 20 个用户里，有没有画像跟我预期不一样的？（→ 更新假设）

---

## Appendix A：directory manifest 模板

**Smithery / mcp.so 公共字段**：
- Name: `analook`
- Display name: `Analook — Competitor Intelligence`
- Short description: `AI competitor analysis for agents — website, SEO, traffic, social, Product Hunt, pricing, funding, Wayback history.`
- Long description: 见 `/docs/mcp` 页首段
- Homepage: `https://analook.com`
- Transport: `streamable-http`
- URL: `https://analook.com/mcp`
- Tools: `analyze_competitor`, `get_report_status`, `get_report`, `get_report_markdown`, `list_my_reports`
- Categories: `research`, `sales`, `marketing`, `seo`, `competitive-intelligence`
- License: `MIT`（代码 repo）/ SaaS ToS（数据）
- Auth: `Bearer token (Supabase JWT)`

## Appendix B：前 5 个 Directory 提交 Checklist

- [ ] Icon 256×256 PNG (复用 analook_logos v3)
- [ ] 5 个示例 prompt 准备好
- [ ] README.md 里加 "MCP" section（带 `/docs/mcp` 链接 + 配置示例）
- [ ] GitHub repo topic 加：`mcp`, `mcp-server`, `competitive-analysis`, `ai-agents`
- [ ] 确认 `https://analook.com/mcp` 在生产稳定至少 72 小时（我们刚 push，需观察）

---

**一句话总结**：占类目 + 写教程 + 进 directory 是 8 周里的 80/20。爆款不是 plan A，SEO/GEO + 社区常驻是 plan A。
