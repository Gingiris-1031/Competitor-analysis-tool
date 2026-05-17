# Plan: 10 Paying Customers in 30 Days (via SEO/GEO + Distribution Multipliers)

> 起草：2026-04-29 (Iris @ Helsinki, Sunday noon)
> 目标：5/29 之前 **10 个真实付费客户**
> 当前：39 注册 / 1 激活 / 0 付费

---

## 现实诚信检查

**先承认一件事**：纯 SEO/GEO 在 30 天内让一个**刚被 Google 索引 2 周**的 SaaS 拿到 10 付费 — **数学上不成立**。

新站 Google 通常有 **3-6 个月 sandbox 期**。即使我们今天 push 10 篇旗舰文，4 周内 organic traffic 最多 200-500/月。按行业标准 SaaS 漏斗 (5% signup → 40% activation → 50% paid conversion at limit)，这种流量只能产出 **1-2 paid**。

所以 10 paid 的 plan = **SEO/GEO 打底 (基础设施) + 4 个 multiplier channels (产能)**。SEO/GEO 是长期复利，但 30 天看 → 必须配合其他渠道。

---

## 漏斗反推

```
目标: 10 paid (5/29)
  ↑ 30-40% paid conversion (用户撞 free tier 上限)
  ↑ ~25 用户撞上限 (活跃用过 ≥3 reports)
  ↑ 40% activation (注册 → 至少跑 1 report)
  ↑ ~65 新注册
  ↑ 5% signup conversion
  ↑ ~1300 unique visitors (analook.com)
```

**所以底线指标**：30 天内 analook.com 拿到 **1300 unique visitors**，其中 **65 注册**，**25 活跃用户**，**10 付费**。

平均每天 = 43 visits / 2 signups / 0.8 active / 0.33 paid。

---

## Key Stats — 当前可用的 Distribution Lever

| 渠道 | 当前规模 | 30 天能榨出多少流量到 analook |
|------|----------|----------------------------|
| growth-tools 自有博客 | 155 月活，66 indexed | **~30-50 clicks/月** (3% CTR from cross-links) |
| dev.to/iris1031 | 30+ 文章，每篇平均 200-500 阅读 | **~50-100 clicks/月** (新 MCP 文 + saas marketing) |
| Twitter/X 个人号 | 估算 2-3K 关注 | **~100-300 clicks** (1 launch tweet + 5 build-in-public 帖) |
| 即刻 / 小红书 | 估算 | **~50-150 clicks** (1 launch + 3 案例帖) |
| Reddit r/SaaS r/IndieDev 等 | — | **~200-800 clicks** (3 strategic posts) |
| HN Show / Show HN | — | **~500-3000 clicks** (1 well-timed post) ← biggest single lever |
| Product Hunt 二次 launch | — | **~500-2000 clicks** (1 launch) |
| Email 36 沉睡用户 (EDM) | 36 contacts | **~10-15 returning clicks** |
| AI 引擎引用 (ChatGPT/Perplexity) | 1 次 (4/26) | **~30-100 clicks/月** (long-tail high-intent) |
| 直接外联 (1:1 cold) | 0 | **~30 conversations → 10 trials → 2-3 paid** |

**累计天花板（如果全部做满）**：1500-7000 流量 + 高质量直接外联。

**理性假设**：做到上面一半 + 转化率不崩 = **10 paid 是合理目标，不是空想**。

---

## 30 天 Sprint（4 周拆解）

### Week 1 (4/29 - 5/5) — **基础设施 + 启动**

**已经做完（今天）**：
- ✅ saas marketing flagship 大刷新（+1800 词，Analook 案例）
- ✅ saas-marketing-on-a-budget spoke（2348 词，dev.to 同步）
- ✅ 5 个 cross-link from growth-tools → analook.com
- ✅ MCP Registry 上架（io.github.Gingiris/analook）
- ✅ canonical + sitemap freshness
- ✅ daily SEO cron + weekly user metrics 自动跑

**本周还要做**（必须，没商量）：

| 任务 | 谁做 | 预期 |
|------|------|------|
| 修 apex SSL (`https://analook.com` → www) | 我写 FastAPI middleware + 你 Railway 配 custom domain | 修完所有 HTTPS 分享链接生效 |
| Pricing 页 conversion check | 你 review | 看 "Free 3/月" 限制是否触发明显升级 CTA |
| EDM 启动 — 给 36 沉睡用户发"补 10 credits"邮件 | 你注册 Resend + 配 DNS，我写脚本 | **预期回流 5-8 人**，1-2 paid |
| Show HN 帖 "I built a Remote MCP server for competitor analysis in 200 lines" | 你周一/周二早 PT 时间发 | **预期 500-3000 流量 + 5-15 signups** |
| Twitter launch thread (10 推) | 你写，我帮起草 | 复用 saas marketing + MCP 文要点 |

**Week 1 目标**：
- 50 新 signups (累计 89)
- 10 active
- **1-2 paid** (主要来自 Show HN 高意图流量)

### Week 2 (5/6 - 5/12) — **内容速度 + 渠道扩展**

| 任务 | 投入 | 预期产出 |
|------|------|--------|
| 写 PH playbook freshness update（如果 5/2 后还 off-100） | 2h | 7 天内回 top 30 |
| 写 PH hunter selection spoke（1200 字） | 3h | 长尾词收入 |
| 写 PH pre-launch community spoke（1500 字） | 3h | 长尾词 |
| Reddit r/SaaS 发 1 篇高质量 case study "How I got 39 SaaS users in 4 weeks" | 0.5h + monitor | 200-500 流量 |
| 小红书 + 即刻发 launch 帖 (中文双站) | 1h | 50-150 中文用户 |
| 邀请 2-3 个 SaaS 同行 / OSS 同行用 Analook (互推) | 2h cold reach | 5-10 高质量 signups |
| 启动 Twitter build-in-public daily | 30min/day | 渐进 follower 增长 |

**Week 2 目标**：
- 40 新 signups (累计 129)
- 25 active
- **2-3 paid**

### Week 3 (5/13 - 5/19) — **杠杆放大 + GEO 启动**

| 任务 | 杠杆点 |
|------|-------|
| 写 Open Source Growth pillar（3500 字，AFFiNE 60K 故事） | 这篇可能是单篇 inbound 之王，dev.to / HN 都吃 |
| Reddit + HN + dev.to 同步发布 | 估 1000-3000 流量 single day |
| 启动 ChatGPT/Perplexity 引用追踪（每周跑 5 个 prompts 看是否被引） | GEO 闭环 |
| 给 wangherbert97 (唯一活跃外部用户) 发感谢邮件 + 邀请用 Pro | 个案，但**唯一真实付费 evidence** |
| 准备 Smithery 提交 | MCP 类目长尾 |

**Week 3 目标**：
- 50 新 signups (累计 179)
- 50 active
- **3-4 paid**

### Week 4 (5/20 - 5/29) — **冲刺 + 数据闭环**

| 任务 | |
|------|---|
| 写 MCP pillar 重写 + 2 spokes（Claude Desktop setup + Cursor examples） | dev.to MCP 类目 0 竞争窗口 |
| Product Hunt 二次 launch（如果 Week 1 Show HN 没爆，这是最后一发） | 1500-3000 流量 |
| Email 已注册但未付费用户 personalized upgrade nudge | 转化已激活但未付费的 ~15 人 |
| 写 "First 30 days running a SaaS" build-in-public 长文 | 自我引流 + 信任建立 |
| 周末复盘 + 决定下个月路线 | |

**Week 4 目标**：
- 30 新 signups (累计 209)
- 30 active
- **3-4 paid**（高漏斗收尾 + Pro 转化）

---

## 4 Channels × 30 天预期（保守 → 乐观 → 拼命）

| Channel | 保守 | 中性 | 拼命 |
|---------|------|------|------|
| SEO direct (analook.com indexed pages) | 1 paid | 2 paid | 3 paid |
| GEO (AI citations + dev.to/iris1031) | 1 paid | 2 paid | 4 paid |
| Reddit/HN/PH distribution spikes | 2 paid | 4 paid | 6 paid |
| Direct outreach + EDM (沉睡用户) | 2 paid | 3 paid | 5 paid |
| **TOTAL** | **6** | **11** | **18** |

**中性路径 = 11 paid** → 略超目标。所以这个 plan 是**可达但需要每周稳定执行**。

---

## 关键 SEO/GEO 目标（5/29 verifiable）

| KPI | 4/29 | 5/29 目标 |
|-----|------|-----------|
| site:analook.com Google 索引数 | 10 | **30+** |
| 排名 top 30 的关键词数 | ~3 | **15+** |
| 排名 top 10 的关键词数 | ~1 (品牌词) | **5** (含 saas marketing, mcp server for saas, on a budget, etc.) |
| AI 引擎引用次数 (累计) | 1 | **10+** |
| dev.to/iris1031 文章 follower follows | ? | **+100** |
| analook.com 月独立访客 | 0 | **800-1500** |

---

## 转化漏斗优化（必修，否则流量浪费）

这些 5/5 前必做：

### 1. Pricing 页（你 review 现状）
- 当前：Free 3/月，Pro $29/月 30 reports，Team $99/月，Single $5
- 检查：免费用户撞上限时有没有强引导 CTA？
- 加：social proof（你的 30x PH、AFFiNE 60K 都该上）
- 加：testimonial（找 wangherbert97 要一条引言）

### 2. /comparison 页 conversion check（V2 上线了吗？）
- 这是高 intent 流量入口（"Crayon vs Klue" 之类长尾词）
- 检查：是不是 demo-able 不登录就能跑？

### 3. Onboarding 引导
- 注册后第一屏要有 "跑你第一份分析 (示例：lovable.dev)"
- 当前激活率 2.8% 太低，**这个不修，10 paid 不可能**

### 4. Credit exhaustion 弹窗
- 第 3 个 report 跑完时 → 不能默默挡，要弹"已用完免费额度，$5 单 report 或 $29 升级"
- 这是 paid conversion 的关键 trigger

---

## 每周一固定 cadence（怎么知道走没走在路上）

每周一早 09:07 北京时间（GitHub Actions 自动跑）：
1. 看 `docs/weekly_metrics/2026-Www.md`（用户漏斗）
2. 看 `docs/seo_geo_history/YYYY-MM-DD.md`（流量数据）
3. 对照下面这 5 个数：

| 周末 | 累计 signups | 累计 active | 累计 paid | 还差几个 | 行动 |
|------|------|------|------|------|------|
| 5/5 (W1 end) | 89 | 10 | 1-2 | 8-9 | Week 2 全力发 |
| 5/12 (W2 end) | 129 | 25 | 4-5 | 5-6 | 看哪个 channel ROI 最高，集中砸 |
| 5/19 (W3 end) | 179 | 50 | 7-8 | 2-3 | 个别 nudge + 二次 launch |
| 5/26 (W4 end) | 209 | 80 | 10+ | ≤0 | ✅ |

**如果 5/12 累计 < 4 paid** → 路线偏离，进急救模式（all-in 1 个 channel）。

---

## ⚠️ 风险与 backup

### Risk 1: Show HN 没爆
**Backup**：5/15 之前 Product Hunt launch（路线 B），上一波流量 1500-3000。

### Risk 2: SEO 全部 off-100
**Backup**：第 2 周开始重金做 1-to-1 outreach（手写 60 封邮件 / 周）。

### Risk 3: Onboarding 还是激活率 2.8%
**Backup**：临时改首页 default flow — 直接预填一个 demo URL 让用户秒看报告，登录改到"想保存才登录"。

### Risk 4: Stripe/Polar 支付通道有 bug
**Backup**：今晚就做一次"假装付款" test，确认 $5 / $29 都跑得通（这个真不行 = 直接 0 paid）。

---

## 🎯 你（Iris）本周（W1）的 6 件具体事

1. **修 apex SSL**（Railway 加 `analook.com` custom domain，我会写 redirect middleware）
2. **Pricing + onboarding review** — 自己跑一遍注册到付费流程，列出每个摩擦点
3. **Stripe/Polar 测试一次真支付**（用 test card 跑 $5 Single Report，确认收得到钱）
4. **Resend 注册 + DNS 配置**（24h 内）— 周末就给 36 沉睡用户发邮件
5. **Show HN 帖准备**（标题候选：见下方）
6. **Twitter launch thread 起草**（我帮草稿，你回 Kunshan 改第二遍）

我（在你睡觉 / 喝咖啡时）能做的：
- 写 Show HN 标题 + 正文草稿 (3 候选)
- 写 Twitter 10 推 launch thread
- 写 PH playbook freshness 段落（如果 5/2 还 off-100）
- 写 PH hunter spoke + PH pre-launch spoke (Week 2 任务提前)
- 配 FastAPI redirect middleware
- 加 schema.org JSON-LD 到所有新 spoke (GEO booster)

---

## Show HN 标题候选（你周一早 PT 时间发）

A. **"Show HN: A Remote MCP server for competitor analysis (200 lines, the 3 bugs we caught)"**

B. **"Show HN: Analook — paste a competitor URL, get an AI teardown via MCP in your Claude Desktop"**

C. **"Show HN: I exposed my SaaS to AI agents in 200 lines (and lost 5 reports to a Railway bug)"**

→ 我推荐 **C**（最 HN 友好的 storytelling、最具体的失败数字、最少 promo 味）。

---

## 一句话总结

> **SEO/GEO 是 30 天打底，但 10 paid 真正靠的是 "distribution spikes + EDM 沉睡用户激活 + 1-to-1 outreach"。**
> SEO/GEO 给你的是月 6 之后的复利。distribution 给你的是月 6 之前的活路。两条腿走，缺一不可。

---

## 下次 review

每周一早北京 09:07，GitHub Actions 跑完报告后我跟你对账。

第一次对账：**5/6**（W1 结束）。

如果到时候 paid = 0 → 重新拆解，把 W2 任务 all-in 到 1 个 channel。
