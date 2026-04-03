<div align="center">

<img src="https://raw.githubusercontent.com/Gingiris/Competitor-analysis-tool/main/static/assets/logo.png" alt="Analook Logo" width="120" />

# Analook — 竞品情报分析工具

### 30 秒看透任何竞品 · AI-powered competitor intelligence for indie hackers & growth teams

[![GitHub stars](https://img.shields.io/github/stars/Gingiris/Competitor-analysis-tool?style=social)](https://github.com/Gingiris/Competitor-analysis-tool/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Gingiris/Competitor-analysis-tool?style=social)](https://github.com/Gingiris/Competitor-analysis-tool/network/members)
[![GitHub watchers](https://img.shields.io/github/watchers/Gingiris/Competitor-analysis-tool?style=social)](https://github.com/Gingiris/Competitor-analysis-tool/watchers)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Website](https://img.shields.io/badge/Live-analook.com-blue)](https://www.analook.com)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/Gingiris/Competitor-analysis-tool/pulls)
[![Last Commit](https://img.shields.io/github/last-commit/Gingiris/Competitor-analysis-tool?color=blue)](https://github.com/Gingiris/Competitor-analysis-tool/commits/main)
[![Deployed on Railway](https://img.shields.io/badge/Deploy-Railway-blueviolet)](https://railway.app)

**[English](#english) | [中文](#中文版)**

</div>

> 💡 **出海增长咨询 · 1v1 Session 约课 $200** — [Telegram @Iris_carrot](https://t.me/Iris_carrot)
>
> 或访问 **[gingiris.com](https://gingiris.com/en)** — Iris 的出海增长咨询，1:1 指导、开源项目运营、企业顾问服务

## Table of Contents

- [What is Analook](#what-is-analook)
- [Live Demo](#-live-demo)
- [Analysis Modules](#-analysis-modules)
- [AI Insights Depth](#-ai-insights-depth)
- [Quick Start](#-quick-start)
- [Deploy Your Own](#-deploy-your-own)
- [API Integrations](#-api-integrations)
- [Work With Iris](#-work-with-iris)
- [About the Author](#about-the-author)
- [中文版](#中文版)

---

> 🌱 **Philosophy**
>
> *"做竞品分析不是为了抄，是为了找到别人没做好的地方。"* — Competitor research isn't about copying — it's about finding the gaps they left open.
>
> *"数据会说话，但你得先知道问对问题。"* — Data speaks, but only if you ask the right questions.
>
> *"30 秒看懂一个产品，30 天超越它。"* — Understand a product in 30 seconds. Surpass it in 30 days.

---

> 💼 **Work With Iris**
>
> **1. Strategic Consultation (1v1)**
> | Session | Price | Best For |
> |:--------|:------|:---------|
> | Quick Call (30 min) | $150 USD | Specific questions, quick diagnosis |
> | Deep Dive (60 min) | $300 USD | Full strategy review, detailed roadmap |
>
> **2. Advisory Retainer**
> | Plan | Price | Includes |
> |:-----|:------|:---------|
> | Monthly Retainer | $1,500 USD/mo | Up to 5 hours strategic consultation + milestone reviews |
>
> **3. Playbooks & Templates**
> | Package | Price | Contents |
> |:--------|:------|:---------|
> | Starter Pack | $29 USD | Core methodology + essential tools |
> | Flagship Bundle | $199 USD | Complete SOP, competitor research framework, templates |
>
> 📩 [Contact @Iris_carrot on Telegram](https://t.me/Iris_carrot) — Crypto/USDT and Wire Transfer accepted

---

## What is Analook?

**Analook** is an open-source AI-powered competitor intelligence tool built by [Iris](https://gingiris.com), former cofounder & COO of [AFFiNE](https://github.com/toeverything/AFFiNE) (60k+ stars).

Enter any product URL. In ~30 seconds, Analook runs a **7-module parallel analysis pipeline** and returns a structured deep-dive report — growth strategy, traffic signals, social footprint, ProductHunt history, AI insights, and more.

Built for:
- **Indie hackers** validating a market before building
- **Growth teams** benchmarking against competitors
- **Investors** doing quick pre-DD intelligence
- **Founders** preparing a launch in a crowded niche

### Analysis Results Include

| Signal | What You Learn |
|--------|----------------|
| 🌐 Website History | When launched, how fast it grew, Wayback timeline |
| 📈 Traffic & SEO | Monthly visits, top channels, keyword gaps |
| 🐦 Twitter / X | Followers, engagement rate, content strategy |
| 🚀 Product Hunt | Launch scores, positioning, community response |
| 💡 AI Deep Dive | ICP, business model, growth flywheel, tactical recs |
| 📡 Propagation | Peak traffic events, viral moments, channel breakdown |
| 🧠 Growth Strategy | Early-stage strategy reconstruction from public signals |

---

## 🔗 Live Demo

**[analook.com](https://www.analook.com)** — Free to use. No login required.

Try with: `lovable.dev` · `linear.app` · `notion.so` · `cursor.com`

---

## 📦 Analysis Modules

| Module | File | Description |
|--------|------|-------------|
| Website History | `modules/website_history.py` | Wayback Machine CDX API, first-seen date, snapshot timeline |
| Traffic & SEO | `modules/traffic_analysis.py` | DataForSEO — monthly visits, channels, top pages, keywords |
| Social Media | `modules/social.py` | Apify Twitter scraper — followers, engagement, recent content |
| Product Hunt | `modules/producthunt.py` | PH GraphQL API — launches, scores, upvotes, reviews |
| Growth Analysis | `modules/growth_analysis.py` | Traffic peak detection, event correlation, growth stage |
| AI Summary | `modules/ai_summary.py` | 7-section structured analysis via TeamoRouter + DeepSeek fallback |
| Report Builder | `app.py` | FastAPI orchestrator — parallel pipeline, job state, streaming |

---

## 🧠 AI Insights Depth

Analook's AI module goes beyond surface-level summaries. Each report includes:

1. **产品定位与 ICP** — Target user profiles, market positioning, who actually pays
2. **商业模式拆解** — Pricing model, conversion hypothesis, revenue estimate range
3. **增长密码** — 4–6 data-backed growth strategies with evidence
4. **增长飞轮** — Product-specific flywheel reconstruction
5. **内容与传播策略** — Channel mix, content types, launch propagation model
6. **给后来者的战术建议** — 5 actionable recommendations you can execute this week
7. **风险与机会** — Red flags and market gaps, with data citations

Powered by **TeamoRouter** (primary) and **DeepSeek** (fallback), with max 4,000 token output per report.

---

## ⚡ Quick Start

```bash
git clone https://github.com/Gingiris/Competitor-analysis-tool.git
cd Competitor-analysis-tool
pip install -r requirements.txt
```

Create a `.env` file:

```env
TEAMOROUTER_API_KEY=sk-teamo-...
DEEPSEEK_API_KEY=sk-...
DATAFORSEO_B64=base64(email:password)
PRODUCTHUNT_TOKEN=...
APIFY_API_TOKEN=apify_api_...
```

Run locally:

```bash
uvicorn app:app --reload --port 8000
```

Visit `http://localhost:8000`

---

## 🚀 Deploy Your Own

One-click deploy on **Railway**:

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template)

**Steps:**
1. Fork this repo
2. Create a new Railway project → connect your fork
3. Add the environment variables above in Railway → Settings → Variables
4. Railway auto-deploys on every push to `main`

The app is Dockerized and uses **Nixpacks** on Railway (Python 3.13).

---

## 🔌 API Integrations

| Service | Purpose | Notes |
|---------|---------|-------|
| [TeamoRouter](https://teamo.ai) | Primary LLM | Routes to best available model |
| [DeepSeek](https://deepseek.com) | Fallback LLM | Cost-efficient backup |
| [DataForSEO](https://dataforseo.com) | Traffic & SEO data | Monthly visits, channels, keywords |
| [Apify](https://apify.com) | Twitter/X scraping | `apidojo/twitter-profile-scraper` actor |
| [ProductHunt](https://producthunt.com/v2/oauth/token) | Launch history | PH GraphQL API |
| [Wayback Machine](https://web.archive.org) | Website history | CDX API + timemap |

---

## ⭐ Star This Repo

If Analook saved you hours of manual research, a ⭐ helps others discover it!

---

## About the Author

**Iris (生姜iris)** — Former cofounder & COO of [AFFiNE](https://github.com/toeverything/AFFiNE) (60k+ GitHub stars). Now running **[Gingiris](https://gingiris.com)** — an open-source go-to-market and global expansion consulting practice.

- 🐦 Twitter: [@WeiYipei](https://twitter.com/WeiYipei)
- 💬 Telegram: [@Iris_carrot](https://t.me/Iris_carrot)
- 🌐 Website: [gingiris.com](https://gingiris.com/en)

**Related Playbooks:**
- [gingiris-launch](https://github.com/Gingiris/gingiris-launch) — GTM strategy for AI products & startups
- [gingiris-b2b-growth](https://github.com/Gingiris/gingiris-b2b-growth) — B2B SaaS PLG/SLG growth playbook
- [gingiris-opensource](https://github.com/Gingiris/gingiris-opensource) — Open source launch marketing

---

## 中文版

### Analook 是什么？

**Analook** 是一个开源 AI 竞品情报工具，由 [AFFiNE](https://github.com/toeverything/AFFiNE)（60k+ stars）联创 & 前 COO Iris 构建。

输入任意产品网址，30 秒内生成一份结构化竞品深度报告——包含增长策略、流量信号、社交足迹、ProductHunt 历史、AI 洞察等全套数据。

### 适合谁用？

- **独立开发者** — 开始动手前快速验证市场
- **增长团队** — 对标竞品，找到差距
- **投资人** — Pre-DD 快速情报收集
- **创始人** — 在红海市场找到进攻角度

### 核心分析模块

| 模块 | 数据来源 | 输出内容 |
|------|---------|---------|
| 🌐 网站历史 | Wayback Machine | 上线时间、成长速度、快照时间线 |
| 📈 流量 & SEO | DataForSEO | 月访问量、流量渠道、关键词矩阵 |
| 🐦 Twitter/X | Apify | 粉丝数、互动率、内容策略 |
| 🚀 Product Hunt | PH GraphQL | 发布记录、评分、社区反馈 |
| 💡 AI 深度分析 | TeamoRouter | ICP 画像、商业模式、增长飞轮、战术建议 |
| 📡 传播分析 | 综合 | 流量峰值事件、渠道来源、传播节点 |
| 🧠 早期增长策略 | 综合 | 从公开信号反推产品早期增长路径 |

### 快速部署

```bash
git clone https://github.com/Gingiris/Competitor-analysis-tool.git
cd Competitor-analysis-tool
pip install -r requirements.txt
# 配置 .env 文件后：
uvicorn app:app --reload --port 8000
```

**Railway 一键部署：** Fork 本 repo → Railway 连接 → 添加环境变量 → 自动部署 ✅

### 关于作者

Iris（生姜iris），AFFiNE 联创 & 前 COO，现运营 [Gingiris](https://gingiris.com) 开源出海增长咨询。

- 出海咨询预约：[gingiris.com](https://gingiris.com/en)
- Telegram：[@Iris_carrot](https://t.me/Iris_carrot)
- Twitter：[@WeiYipei](https://twitter.com/WeiYipei)
