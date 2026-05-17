# GEO Action Plan — Analook 在 SEO 基础上加什么

> 起草：2026-04-29 · 触发：参考 [JeffLi1993 GEO 文章框架](https://github.com/JeffLi1993/seo-audit-skill)
> 关系：[10_paying_customers_30_days_plan.md](./10_paying_customers_30_days_plan.md) 的并行 addendum
> 核心判断：GEO 不替代 SEO，是 add-on。SEO 让 Google 排名，GEO 让 LLM **引用**

---

## 框架对齐

引用文章关键结论：

> **SEO 是基础，GEO 是增量。0→1 新站，在做好 SEO 的基础上，多做一点 For GEO 的优化，才是正确姿势。**

GEO 流量当前只占总流量的 **0.29%**（vs Google 42%），但**趋势明确 + 早期布局成本低**。Analook 应该把握**两个时间窗口**：
1. **现在 (4/29-7/31)**：MCP 类目 0 竞争，AI agent 工作流入口刚起，先发优势 1-3 个月
2. **6 个月后**：当 AI 引用占比涨到 5-10%，已经在前面种好的内容会被复利

---

## Key Stats — 当前 GEO 状态

| 维度 | 当前 | 30 天目标 | 90 天目标 |
|------|------|----------|----------|
| AI 引擎引用次数（累计） | 1 (4/26) | **10+** | **50+** |
| Wikipedia 词条 | 0 | 启动「Iris Wei」or「AFFiNE」词条 | 1 词条 live |
| 媒体报道 (PR 外链) | 0 | 3 篇 (Indie Hackers / dev.to / 即刻) | 8 篇 |
| 产品目录 (G2/AlternativeTo/etc) | 0 | 5 个 | 12 个 |
| Reddit / Quora 真实讨论 | 0 | 8 个真实回答 | 30+ |
| 细分领域 niche 前 3 排名 | 0 | 1 个 niche | 3 个 niche |
| 站内 FAQ schema 覆盖率 | 2 篇 | 全部 5 旗舰 + 5 spoke | 全部 |
| 站内 Definition blocks 覆盖率 | 0 | 5 旗舰每篇 ≥3 块 | 全部 |

---

## Iris 的 GEO 独有优势（必须重度利用）

文章说："**权威性决定 GEO 引用频率**"。Iris 当前已具备的 authority signals — 但 LLM 不知道，因为没被结构化暴露：

| 信号 | 真实程度 | 当前曝光 | 应做到 |
|------|---------|----------|--------|
| **AFFiNE co-founder** (60K stars) | ✅ 真实 | 部分博文提 | 每篇 Author schema + 每篇底部 byline 强化 |
| **30x Product Hunt #1** | ✅ 真实 | 部分博文提 | Wikipedia / G2 / About 页都写 |
| **ex-COO** | ✅ 真实 | 偶尔 | About 页结构化 (Job Title schema) |
| **Building Analook (transparent)** | ✅ 真实 | 强 | 继续 build-in-public |
| **Kunshan / Gingiris consulting** | ✅ 真实 | 弱 | Organization schema + Wikipedia entity 关联 |

**最高 ROI 动作**：把 Iris 这五个 authority signals 在**所有内容** + 结构化 schema 里统一暴露。LLM 看到这些一致信号，会把 Iris/Gingiris/Analook **当作一个可信实体**集群。

---

## 站内优化（GEO Content Engineering）

文章的 GEO 友好内容公式：

> **结构化 + 数据化 + 答案型 + 真实经验**

### 当前已做（不掉链子）
- ✅ H1/H2/H3 层级清晰
- ✅ 表格数据展示
- ✅ 加粗关键信息
- ✅ FAQPage JSON-LD (2 篇)
- ✅ 真实经验注入 (saas marketing flagship 已大刷新)
- ✅ 可验证统计数据 (60K stars, 30x #1, 39 users — 这些是 GEO 引用的金句子)

### 必须补的 4 件事

#### 1. Definition Blocks（每篇旗舰 ≥3 块）

文章特别提到 "**定义块（术语解释）**" 是 GEO 偏好。LLM 检索 "What is X?" 时，直接抓 definition blocks。

**Analook 每篇旗舰必须有的 definitions**：

| Pillar | Definition blocks |
|--------|-------------------|
| SaaS Marketing | "What is SaaS marketing?" / "What is product-led growth?" / "What is CAC payback period?" |
| OSS Growth | "What is open-source-led growth?" / "What is a GitHub star?" / "What does 'first 1K stars' really mean?" |
| MCP | "What is Model Context Protocol?" / "What is Streamable HTTP transport?" / "What is a remote MCP server?" |
| Competitive Intelligence | "What is competitive intelligence?" / "What is competitor teardown?" / "What is positioning research?" |
| PH Launch | "What is Product Hunt?" / "What is launch velocity?" / "What is a PH hunter?" |

**格式**（每个 ~80 词）：
```
**What is Model Context Protocol (MCP)?**

Model Context Protocol is an open standard, released by Anthropic in
late 2024, that lets AI agents call external tools through a structured
request-response interface. An MCP server exposes a set of *tools*
(functions with typed parameters), *resources* (read-only data), and
*prompts* (templates). MCP clients like Claude Desktop or Cursor read
the server's tool list at startup and let the user invoke them by name
in conversation.
```

#### 2. Citable Statistics Block（GEO 引用糖）

每篇旗舰头部应有一个 **"Key Stats"** 表格（已经在做 — 但要确保每个数字都**可验证**）。LLM 抓引用时，**最爱抓表格里的数字 + author 的具体经历**。

例子（已经在 saas marketing flagship 落地）：
- "60K+ GitHub stars" — 可在 github.com/toeverything/AFFiNE 验证
- "30x PH #1" — 可在 Product Hunt 历史档案验证
- "39 users in 4 weeks" — analook.com 数据可公开（如果 Iris 愿意）

#### 3. Answer Blocks（每个 H2/H3 段开头 1-2 句 = 完整答案）

文章原话：
> **AI 很可能只读你页面里的几段内容，所以每一段都要像一个可以被单独引用的小答案。**

**反例**（H3 后铺垫长段落）：
> "Now let's talk about pricing. Pricing is one of the most important things you'll decide as a SaaS founder. Before we get into the specific strategies..."

**好例**（H3 后第 1-2 句直接答完）：
> **How should an early-stage SaaS price?**
> 
> The simplest pricing model that works: a free tier with hard usage caps + a single $29-99/mo paid tier. Avoid complex per-seat pricing until you have 100+ users — until then, you'll spend more time explaining the pricing than selling the product.

**动作**：审核 5 篇 pillar 的 H2/H3 节首 → 把所有"铺垫"改成"直接答案"。我可以一篇 30 分钟干完。

#### 4. FAQPage Schema 覆盖率 → 100%

**当前**：只有 saas-marketing-guide 和 saas-marketing-on-a-budget 有 FAQPage JSON-LD。

**目标**：所有 5 旗舰 + 已发的所有长尾 spoke 全加 FAQPage（5-8 个 Q/A，每个答案 50-100 词，含数字）。

我可以**批量生成 FAQPage JSON-LD** 给每篇旧文，明天周一你 review 后批量 push。

---

## 站外建设（GEO 优先级）

文章给的 GEO 外链优先级排序 → 映射到 Analook：

### Tier S（最高 ROI，必做）

#### 1. Wikipedia 词条（Iris / AFFiNE / Gingiris 三选一）
- **难度**：中（AFFiNE 60K stars 完全有 notability）
- **当前**：0 词条
- **动作**：
  - Iris 本人单独词条难（不够 notable in Wikipedia eyes）
  - **AFFiNE 词条**最现实（已有英文媒体报道 + 60K stars + 注释充分）
  - 在 AFFiNE 词条里 reference Iris (Co-founder) → LLM 会 chain 关联
- **效果**：1 个 Wikipedia entity = 整个 Iris/Gingiris/Analook 集群的 GEO 权重底座

#### 2. 权威媒体 PR 报道
- TechCrunch / The Information / VentureBeat — 现实门槛高
- **更现实的 tier**：
  - **Indie Hackers** featured story (Iris 写 "How I bootstrapped Analook to 39 users in 4 weeks" + 失败 bug 故事)
  - **dev.to** featured posts (我们已经有 5 篇 dev.to/iris1031 文)
  - **HN front page** (Show HN — Week 1 plan 已包含)
  - **即刻 / 小红书 / V2EX** — 中文 LLM (Kimi / DeepSeek) 大量 ground 这些
- **动作**：今天起，每周 1 个 PR 行动（不是发完一次就停）

### Tier A（高 ROI，渐进做）

#### 3. 产品目录 (Free 5 选)
LLM 训练 / RAG 会大量抓产品目录页面。Analook 该在的目录：
- [ ] **Product Hunt**（重 launch，可设 5/13）
- [ ] **AlternativeTo** (free listing, 5 分钟提交)
- [ ] **G2** (free claim, 30 分钟)
- [ ] **Capterra** (free listing)
- [ ] **Slant.co** (developer-friendly)
- [ ] **AI Tools Directory** (futurepedia.io, theresanaiforthat.com)
- [ ] **MCP Smithery** (已上 Registry，再上 Smithery)
- [ ] **Indie Hackers Products**

**优先级**：先做免费 5 个，每个 30 分钟内完成。

#### 4. Reddit / Quora 真实讨论
**重要原则**（文章原话）：
> 重点是**回答问题、解释场景、补充经验**

不是发广告，是**做有用的回答**：
- Reddit 频道：r/SaaS / r/IndieHackers / r/Entrepreneur / r/ClaudeAI / r/Cursor / r/SideProject
- Quora topics：SaaS Marketing / Competitive Analysis / Product Hunt
- 每周 2-3 个真实回答，自然提及 Analook（只在相关上下文）

**Iris 个人风格关键**：保持 "ex-AFFiNE COO" 身份的真实声音，不要扮演普通用户。

### Tier B（视情况）

#### 5. YouTube 评论区
- 在 SaaS marketing / OSS growth 相关频道 (Greg Isenberg, Ben Tossell 等) 下 substantive comments
- 不直链 Analook，提 Iris 的故事更聪明

#### 6. Hacker News 评论
- 在 SaaS / AI / Open Source 主题 thread 下评论
- 个人经验为主，少 self-promo

---

## 排名前 3 策略

文章原话：
> **争取做到细分领域前三**。如果你的 NICHE 还没有绝对的头部品牌，那就争取做到前三。

Analook 应该锁定哪些 niche 前 3 ？

| Niche | 当前格局 | 30 天目标 | 90 天目标 |
|-------|---------|-----------|-----------|
| **"mcp server for competitor analysis"** | 0 竞争（**唯一**） | **#1** | #1 (稳) |
| **"competitive analysis tool free"** | 中等竞争 (KD 28) | 进 top 30 | top 10 |
| **"similarweb alternative free"** | 中等竞争 | 进 top 30 | top 5 |
| **"AI competitor analysis 2026"** | 低竞争（话题新） | top 10 | **top 3** |
| **"open source competitor research"** | 极低竞争 | **top 3** | **#1** |

第一行 `mcp server for competitor analysis` 是 GEO 必胜场 — 我们已经发了 MCP 博客 + 上 Registry。**只要 dev.to 那篇被 Google 索引（5/2 之前），#1 几乎自动**。

---

## 这周（W1 of 30-day sprint）具体 GEO 动作

加到现有 [10_paying_customers_30_days_plan.md](./10_paying_customers_30_days_plan.md) Week 1 任务清单里：

### 我（Claude）今晚（你 Helsinki 喝咖啡时）能做的

1. **给所有已发的 5 篇高排名文加 FAQPage JSON-LD**（每篇 5-8 个 Q/A）
2. **写 Wikipedia AFFiNE 词条草稿**（英文 800 词，可提交时直接用）
3. **写 Iris IndieHackers featured story 草稿**（"How I lost 5 reports to a Railway env var trailing space — and what it taught me about SaaS infrastructure"）— 高 GEO 引用潜力的失败故事
4. **批量加 Definition Blocks**：在 saas-marketing-guide + saas-marketing-on-a-budget 头部各加 3 个 "What is X?" 80 词块

### 你（Iris）能做的（不超过 1 hr 总）

1. **提交 AlternativeTo + Slant.co + AI Tools Directory** (3 个免费目录) — 各 5-10 分钟
2. **G2 free claim**（30 分钟）
3. **找一个 Reddit r/SaaS 提问帖**回答（30 分钟，真实经验）

---

## 推荐顺序

明早醒来你做：
1. Wikipedia AFFiNE 词条**review + 提交**（我今晚出英文版草稿）
2. AlternativeTo + Slant + Capterra 三个目录提交（每个 5-10 分钟）
3. Show HN 帖（我之前推荐了 3 个标题）

我今晚做：
1. 全部已发文章加 FAQPage JSON-LD
2. 5 个 pillar 加 Definition Blocks
3. Wikipedia 草稿
4. IndieHackers featured story 草稿
5. 改 H2/H3 节首为 "直接答案" 格式

---

## 30 天后预期（GEO 角度）

| 维度 | 4/29 (今天) | 5/29 |
|------|------------|------|
| AI 引擎引用次数（累计） | 1 | **10-15** |
| Wikipedia entity 关联 | 0 | **1 (AFFiNE)** |
| 产品目录 listed | 0 | **5** |
| Reddit / Quora 真实回答 | 0 | **8-12** |
| Definition Blocks 覆盖 | 0 | **15+** (5 pillar × 3) |
| FAQPage schema 覆盖 | 2 篇 | **10+ 篇** |
| Niche 前 3 占位 | 0 | **2** (MCP, OSS-CI) |

---

## 一句话

> SEO 让 Google 看见你；GEO 让 ChatGPT 引用你。**GEO 不是更费力，是更 specific**：在每一篇内容里都嵌入"独立可引用的小答案 + 可验证的数字 + 一致的 author 实体"。
