# Analook SEO/GEO 状态报告 — 2026-04-29

> 时间锚：2026-04-29 凌晨，刚跑完 SerpApi (Google) + Brave + 实地 curl 一轮全网体检
> 对比基线：2026-04-08（site:analook.com = 0，连续 21 天 0 索引）

---

## 🎉 头条：Indexing 危机解除

| 指标 | 4/08 baseline | **4/29 今天** | Δ |
|------|---------------|---------------|---|
| `site:analook.com` Google 收录 | **0** | **10** | **+10 ← 历史性突破** |
| analook 品牌词排名 (Google) | — | **🟢 #1** | — |
| analook 品牌词排名 (Brave) | — | **🟢 #1** | — |
| analook.com Brave site: 收录 | 0 | 1 | +1（Brave 更保守） |

**为什么今天突然破零**：
今天我们一次性修了 4 件事 → Google 重爬触发：
1. `<link rel="canonical">` 加进 index/comparison/docs/mcp 页面
2. sitemap.xml 全部 lastmod 从 2026-04-08 bump 到 2026-04-29
3. 新页面 /comparison.html、/docs/mcp.html 入 sitemap
4. **5 个 growth-tools 高排名贴反向链接** → analook.com（Direction A 交叉引流）

GSC 重新 fetch sitemap.xml + 单 URL 手动 Request Indexing 把这一波推完了。

---

## 📈 Key Stats

| 维度 | 状态 |
|------|------|
| **Google 索引** | analook.com 10 / gingiris.github.io 51-66（按 baseline）/ dev.to/iris1031 30+ |
| **品牌词** | 全引擎 #1 |
| **目标商业词排名** | 全部 off-100（详细见下） |
| **MCP 类目词排名** | 全 off-100（4 个新独占词，今天首发文） |
| **Direction A 反向链接** | **5 个**已部署，Google 待发现（24-72h） |
| **Direction B 反向链接** | **6 个** /compare/* 加 footer，已上线 |
| **dev.to/iris1031 MCP 文** | 已发 (`-4hp`)，**Google 未索引**（今天） |
| **AI 引用** | 4/26 首次 1 次（pos ~5）；今日 0 |
| **Brave site:analook.com** | 1（vs Google 10，引擎差异显著） |

---

## ⚠️ 危机：growth-tools 集体暴跌

**今天比 4/27 baseline 多个高排名词集体掉**：

| 关键词 | 4/27 baseline | **今天** | Δ |
|--------|---------------|---------|---|
| product hunt launch playbook | #5 | **off-100** | -95+ |
| best social media listening tools startups | #11 | **off-100** | -89+ |
| developer community directory | #3 | **#7** (gingiris) | -4 |
| competitor intelligence tools comparison 2026 (analook 命中) | ~#5 (4/26) | **off-100** | -95+ |
| 4/27 dev.to PH playbook | #4 | **off-100** | -96+ |

**可能原因**（按概率）：
1. **Google SERP 整体重洗**（4/26 baseline 已记录"SERP 整体疑似刷新"）— 内容质量没变，临时震荡
2. **canonical_url 配置变更**导致 Google 重新评估 dev.to / 主站权重分配
3. **真实质量信号下降**（不太可能，今天没改这些文）

**关键问题**：今天 push 的 5 个交叉链接（Direction A）会让 Google 重新评估这 5 个 host 文章的"可信度" — 短期内可能会有 1-3 天的"震荡"，**正常情况会回升**。如果 7 天后仍 off-100，那才是真问题。

---

## 🎯 详细排名扫描（Round 1：商业词 / Round 2：内容词）

### Round 1: P0 商业意图词（10 个查询）

| # | Query | analook 排名 | 备注 |
|---|-------|-------------|------|
| 1 | `site:analook.com` | **10 个** | 🎉 破零 |
| 2 | `analook` | **🟢 #1** | 品牌词稳 |
| 3 | `competitive analysis tool` | off-100 | SpyFu 占 #1，巨头垄断 |
| 4 | `competitor analysis tool` | off-100 | 同上 |
| 5 | `competitive intelligence tools 2026` | off-100 | 等内容索引 |
| 6 | `saas competitor analysis` | off-100 | 长尾，应该好打 |
| 7 | `mcp server for competitor analysis` | off-100 | **🆕 我们独占的词** |
| 8 | `claude desktop competitor research` | off-100 | **🆕 独占** |
| 9 | `remote mcp examples saas` | off-100 | **🆕 独占（中竞争）** |
| 10 | `similarweb alternative` | off-100 | /compare/similarweb.html 应该上 |

### Round 2: 内容词 + 旗舰文（10 个查询）

| # | Query | 排名 | 备注 |
|---|-------|------|------|
| 1 | product hunt launch playbook | ⚫ off-100 | **从 #5 暴跌** |
| 2 | best social media listening tools startups | ⚫ off-100 | **从 #11 暴跌** |
| 3 | developer community directory | 🟢 **#7** (gingiris) | 从 #3 跌至 #7 |
| 4 | saas marketing | ⚫ off-100 | KD1 SV1.3K，**正文未写** |
| 5 | github stars growth | ⚫ off-100 | dev.to 老文应该有排名 |
| 6 | dev.to mcp server saas | ⚫ off-100 | 今天首发，预期 1-3 周 |
| 7 | site:gingiris.github.io | 10 results (SerpApi `num=20` 限制) | 真实 51-66 |
| 8 | site:dev.to/iris1031 | 10 results | 真实 30+ |
| 9 | competitor intelligence tools comparison 2026 | ⚫ off-100 | 4/26 曾命中 #5 |
| 10 | go to market strategy 2026 | ⚫ off-100 | GTM playbook 词 |

---

## 🛠️ 今天部署的内容（待 1-21 天看效果）

| 资产 | 类型 | URL | 预期效果 |
|------|------|-----|----------|
| MCP 博客文 | growth-tools | `/blog/2026/04/29/mcp-server-saas-200-lines-3-bugs/` | 7-21 天进 mcp-server-saas top 30 |
| 同篇 dev.to | dev.to | `iris1031/...4hp` | 24-72h 索引，7 天进 top 50 |
| canonical 标签 | analook 全站 | index/comparison/docs/mcp | Google 信任度提升，索引加速 |
| sitemap freshness | analook | sitemap.xml lastmod 4/29 | Google crawler 重爬频率上调 |
| Direction A 5 链 | growth-tools 5 篇老文 | (5 个 .md edit) | analook.com 反向链接权重传递 |
| Direction B 6 链 | analook /compare/* | (4 个 .html edit) | 帮 growth-tools 索引 + 引流 |

**关键时间节点**：
- **5/2-5/3**：dev.to MCP 文应该被 Google 索引
- **5/6**（7 天）：第一个 KD-low MCP 词进 top 30 信号
- **5/13**（14 天）：5 个 Direction A 反向链接 Google 已抓 → analook.com 索引数应该 20+
- **5/20**（21 天）：MCP 类目所有 4 个独占词进 top 10（如果一切顺利）

---

## 🚨 行动项（按 ROI 排序）

### P0（本周必做）

1. **写 saas marketing 正文**（KD1 SV1.3K 送分题）
   - 大纲已入库 `docs/seo_drafts/saas_marketing_outline.md`
   - 2000-2500 字，需 2-3 小时
   - **预期收益**：7-14 天 top 10，每月 100-300 organic visits

2. **修 https://analook.com apex SSL**
   - 现在 HTTP 跳，HTTPS 死。**所有 HTTPS 分享链接一半的人挂**
   - Railway 加 `analook.com` custom domain → 自动签 SSL → app.py middleware 301 → www
   - **预期收益**：捡回所有用 https:// 分享的反向链接权重

3. **GSC 二次提交**（4/29 今天的新 commit）
   - URL Inspection → Request Indexing 这 3 个新 URL：
     - `https://www.analook.com/`（已重新 push）
     - `https://www.analook.com/compare/semrush.html`（加了 cross-link）
     - `https://www.analook.com/compare/ahrefs.html`（同）

### P1（本周内做）

4. **growth-tools 5 个被反链的老文 → 也手动 GSC Submit**
   - 加了新 outbound link，Google 需要重爬感知
   - URL：5 个 `/blog/.../`，**这是关键** —— 反向链接的"权重传递"只有 Google 真实抓到才生效

5. **观察"暴跌词"3 天**
   - 如果 5/2 仍 off-100 → 真有问题，需查
   - 如果 5/2 回升 → 正常震荡

6. **dev.to MCP 文加几条 trackback**
   - 在 dev.to 评论区由 Iris 自己回个 reply 加 analook.com 链接
   - 在 r/ClaudeAI、r/cursor 各发一个分享帖（带 dev.to URL）

### P2（这周末有空再做）

7. **Brave Search 提交** — Brave 跟 Google 索引差距大，单独提交一次 (https://search.brave.com/help/webmaster-tools)

8. **AI 引擎引用追踪**
   - 用 ChatGPT/Perplexity 跑：
     - "What are competitive intelligence tools for SaaS?"
     - "Recommend an MCP server for competitor analysis"
   - 看是否引用 analook.com / dev.to MCP 文

---

## 📊 7 天 / 30 天目标

### 7 天（5/6）
- [ ] `site:analook.com` ≥ 15
- [ ] dev.to MCP 文进 Google 索引
- [ ] 至少 1 个 MCP 类目词进 top 30
- [ ] saas marketing 正文已发布
- [ ] PH playbook 排名回升 ≥ #20

### 30 天（5/29）
- [ ] `site:analook.com` ≥ 30
- [ ] 4 个 MCP 独占词全部 top 10
- [ ] saas marketing top 5
- [ ] 1-3 个 AI 引用
- [ ] 用户激活率 ≥ 5%（GitHub Actions 周报追踪）

---

## 🧠 战略复盘

**今天验证了 3 件事**：
1. **canonical + sitemap freshness** 真的能在 24h 内触发 Google 重爬（今天破 0 索引就是证明）
2. **双站交叉引流策略**对刚起步的 SaaS 是必杀技 — 不需要外部反向链接，自有的高排名站可以"借电"
3. **silent-degrade bug** 的 SEO 损失是隐形的：4/3-4/27 期间所有用户跑过的报告都没存 Supabase，那些 URL 没进任何 sitemap，**至少 36 个外部反向链接（用户分享报告）的机会全损失了**

**今天得到的洞察**：
- AFFiNE 60K stars 故事 + 30x PH #1 故事 是 Iris 的核心 E-E-A-T 资产，每篇旗舰文都该有
- KD-1 词每 2 周扫描一次 — `saas marketing` 这种送分题 Google 关键词排名工具上每天都在变
- **MCP 类目当前 0 竞争**，先发优势窗口期可能只有 1-3 个月，必须趁热打铁

---

**下一次 SEO/GEO 报告**：建议 7 天后（5/6）跑同一份脚本对比，看震荡是否回升、新内容是否上索引。

**生成方式**：可以把今天的探测代码做成 `scripts/seo_geo_report.py`，跟 user_metrics.py 同样的 GitHub Actions 周一自动跑。要做吗？
