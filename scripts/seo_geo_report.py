#!/usr/bin/env python3
"""
Analook 每日 SEO/GEO 巡检 + 行动建议生成器

每日 GitHub Actions 跑：
1. 用 SerpApi 拉 12 个核心关键词的当前排名
2. 对比昨天快照（docs/seo_geo_history/YYYY-MM-DD.json）
3. 计算 day-over-day Δ
4. 跑规则引擎匹配 ACTIONS（条件 → 具体 todo）
5. 输出 Markdown 周报 + 持久化今日 JSON 快照

配套：scripts/user_metrics.py（用户漏斗）+ 这份（流量入口）= 完整每日健康检查。

Usage:
    SERPAPI_KEY=... python scripts/seo_geo_report.py [--no-write]
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = os.environ.get("SERPAPI_KEY", "").strip()
if not API:
    print("ERROR: set SERPAPI_KEY", file=sys.stderr)
    sys.exit(1)

# ── 配置 ───────────────────────────────────────────────────────────────────
# 每个查询的 (query, owner host filter, label, target_top, target_window_days)
# owner 用来从 organic 中找 "我们的页面" — 任一 host 命中都算。
QUERIES = [
    # P0 商业意图 — 长期目标 top 10
    ("competitive analysis tool",                ["analook.com"],                                    "P0 商业词",      30, 90),
    ("competitor analysis tool",                 ["analook.com"],                                    "P0 商业词",      30, 90),
    ("similarweb alternative",                   ["analook.com"],                                    "alt-竞品词",     30, 60),

    # 🆕 MCP 类目 — 我们独占，目标快速进 top
    ("mcp server for competitor analysis",       ["analook.com", "dev.to/iris1031"],                 "MCP 独占",       10, 30),
    ("claude desktop competitor research",       ["analook.com", "dev.to/iris1031"],                 "MCP 独占",       10, 30),
    ("remote mcp examples saas",                 ["analook.com", "dev.to/iris1031"],                 "MCP 类目",       20, 30),

    # 旗舰内容词 — 已经排过的，监控震荡
    ("product hunt launch playbook",             ["gingiris.github.io", "dev.to/iris1031"],          "旗舰内容",       10, 7),
    ("best social media listening tools startups",["gingiris.github.io"],                            "旗舰内容",       15, 14),
    ("developer community directory",            ["gingiris.github.io"],                             "旗舰内容",        5, 7),
    ("go to market strategy 2026",               ["gingiris.github.io"],                             "旗舰内容",       30, 21),

    # 待写正文的送分题
    ("saas marketing",                           ["gingiris.github.io"],                             "🎯 KD1 送分",     20, 14),

    # 索引计数（特殊：site: 查询，统计返回数）
    ("site:analook.com",                         ["analook.com"],                                    "索引计数",        15, 14),
]

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "docs" / "seo_geo_history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _serpapi(q: str, retries: int = 2) -> dict:
    """SerpApi with retry + sanity check.

    Single calls occasionally return 0 results due to transient API issues
    or rate limiting — that produced a false-positive P0 ("index dropped to
    0!") alert on 2026-05-17. For `site:` queries we retry up to `retries`
    times before accepting an empty result.
    """
    import time
    enc = urllib.parse.quote(q)
    url = f"https://serpapi.com/search.json?q={enc}&engine=google&num=20&api_key={API}"
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                last = json.loads(r.read())
            organic = last.get("organic_results", []) or []
            # For site: queries, treat 0 results as suspicious — retry.
            # For regular queries, 0 results is a valid (off-100) answer.
            if q.startswith("site:") and len(organic) == 0 and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            return last
        except Exception:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    return last or {}


def _find_pos(organic: list, hosts: list[str]) -> tuple[int | None, str | None]:
    for r in organic:
        link = r.get("link", "") or ""
        for h in hosts:
            if h in link:
                return r.get("position"), link
    return None, None


def _emoji(pos: int | None, target: int) -> str:
    if pos is None:
        return "⚫"
    if pos <= 10:
        return "🟢"
    if pos <= target:
        return "🟡"
    return "🔴"


def _delta(today: int | None, yesterday: int | None) -> str:
    if today is None and yesterday is None:
        return ""
    if today is None:
        return f"⬇ off-100 (was #{yesterday})"
    if yesterday is None:
        return f"🆕 #{today}"
    diff = yesterday - today  # positive = improvement
    if diff == 0:
        return "→0"
    sign = "↑" if diff > 0 else "↓"
    return f"{sign}{abs(diff)}"


# ── 行动规则引擎 ───────────────────────────────────────────────────────────
# (condition_fn, priority "P0|P1|P2", title, body)
# 每个 rule 拿到 today 和 yesterday 的 snapshot dict，返回 True 触发 action

def _today_pos(today: dict, q: str) -> int | None:
    return today.get(q, {}).get("pos")

def _today_count(today: dict, q: str) -> int:
    return today.get(q, {}).get("count", 0)


ACTIONS = [
    # —— P0 ——
    # Index-count P0s need cross-snapshot confirmation. A single SerpApi
    # blip can return 0 results (happened 2026-05-17), so the rule asks
    # for sustained low values rather than a one-shot snapshot.
    (
        lambda t, y: (
            _today_count(t, "site:analook.com") < 5
            and y is not None
            and _today_count(y, "site:analook.com") < 5
        ),
        "P0",
        "🚨 analook.com 索引数持续 < 5 (≥2 天)",
        "Google 索引断崖 — 已连续 ≥2 天低于 5。立即 GSC → URL Inspection 重新提交首页 + /comparison + /docs/mcp。\n"
        "根因排查顺序：(1) sitemap.xml HTTP 200 (2) 首页 view-source 无 noindex (3) robots.txt 无新 Disallow (4) Cloudflare/Railway 没拦截 Googlebot。",
    ),
    (
        lambda t, y: (
            y is not None
            and (_today_count(y, "site:analook.com") - _today_count(t, "site:analook.com")) >= 8
            and _today_count(t, "site:analook.com") < 3
        ),
        "P0",
        "📉 analook.com 索引断崖跌（昨日≥8、今日<3）",
        "今日索引数比昨日少 8+ 且今日 < 3。这通常意味着真实 de-indexing 事件（非 SerpApi 抖动）。\n"
        "立即验证：`curl 'https://serpapi.com/search.json?q=site:analook.com&api_key=...'` 复测，再排查 24h 内 commits。",
    ),
    (
        lambda t, y: (
            _today_pos(t, "product hunt launch playbook") is None
            and y is not None
            and (_today_pos(y, "product hunt launch playbook") or 999) < 50
        ),
        "P0",
        "🆘 PH playbook 一夜暴跌出 100",
        "旗舰文从 top-50 跌出榜。检查：dev.to canonical_url 是否被改、growth-tools 文是否被 spam-flag。\n"
        "动作：手动 GSC 重新 inspect dev.to URL；若 24h 内不回，写一篇 freshness update 段落 push。",
    ),

    # —— P1 ——
    (
        lambda t, y: _today_pos(t, "saas marketing") is None,
        "P1",
        "📍 saas marketing 仍 off-100",
        "KD 1 SV 1.3K 送分题。2026-04-29 已大幅刷新 saas-marketing-guide.md (+1800 词，Analook 案例)\n"
        "+ dev.to 同步。预计 5/6-5/12 进 top 30，5/13-5/19 进 top 10。\n"
        "如果 5/13 仍 off-100，考虑：(a) GSC URL Inspection 推一下；(b) 加更多反向链接；(c) 检查 canonical 是否正确。",
    ),
    (
        lambda t, y: any(
            _today_pos(t, q) is None
            for q in ("mcp server for competitor analysis", "claude desktop competitor research")
        ),
        "P1",
        "📣 MCP 独占词仍 off-100",
        "MCP 类目 0 竞争窗口期 1-3 个月。dev.to 文已发布需 GSC 推一下 + 在 r/ClaudeAI / r/cursor 各发一帖带链接。",
    ),
    (
        lambda t, y: (
            _today_pos(t, "developer community directory") is not None
            and _today_pos(t, "developer community directory") > 10
        ),
        "P1",
        "⚠️ developer community directory 跌出 top 10",
        "原 #3 → #7 → ?。需要 freshness 信号。打开该文加 2026 update 段落 + 1-2 个新 case study，重 push。",
    ),

    # —— P2 ——
    (
        lambda t, y: y and all(
            _delta_int(_today_pos(t, q), _today_pos(y, q)) <= -5
            for q in ("product hunt launch playbook", "best social media listening tools startups")
            if _today_pos(t, q) is not None and _today_pos(y, q) is not None
        ),
        "P2",
        "📊 多个旗舰词同跌 ≥ 5 位",
        "可能是 Google SERP 整体重洗（不是你的内容问题）。继续观察 3 天，如不回升再行动。",
    ),
]


def _delta_int(today: int | None, yesterday: int | None) -> int:
    """Day-over-day rank change. Positive = improvement, negative = drop.
    Off-100 treated as 100 for math.
    """
    t = today if today is not None else 100
    y = yesterday if yesterday is not None else 100
    return y - t


def main():
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_path = HISTORY_DIR / f"{today_iso}.json"

    write = "--no-write" not in sys.argv

    # Find yesterday's snapshot (most recent file before today)
    yesterday = None
    yesterday_date = None
    if HISTORY_DIR.exists():
        prev_files = sorted([f for f in HISTORY_DIR.glob("*.json") if f.stem < today_iso])
        if prev_files:
            yesterday_date = prev_files[-1].stem
            yesterday = json.loads(prev_files[-1].read_text())

    # Probe today
    today = {}
    for query, hosts, label, target, _ in QUERIES:
        try:
            d = _serpapi(query)
        except Exception as e:
            today[query] = {"error": str(e)[:100], "label": label, "target": target}
            continue

        organic = d.get("organic_results", []) or []
        if query.startswith("site:"):
            today[query] = {
                "count": len(organic),
                "label": label,
                "target": target,
                "pos": None,
            }
        else:
            pos, link = _find_pos(organic, hosts)
            today[query] = {
                "pos": pos,
                "link": link,
                "label": label,
                "target": target,
                "top1": (organic[0].get("title", "")[:60] if organic else ""),
            }

    # Persist today's snapshot
    if write:
        today_path.write_text(json.dumps(today, indent=2, ensure_ascii=False))

    # ── Render report ──────────────────────────────────────────────────
    out = []
    out.append(f"# Analook SEO/GEO 每日巡检 — {today_iso}")
    out.append("")
    if yesterday_date:
        out.append(f"_对比基准：{yesterday_date}_")
    else:
        out.append("_首次跑，无昨日基准_")
    out.append("")

    # Triggered actions FIRST (Iris 看的第一屏)
    out.append("## 🎯 今日 Action（按优先级）")
    out.append("")
    triggered = []
    for cond, prio, title, body in ACTIONS:
        try:
            if cond(today, yesterday):
                triggered.append((prio, title, body))
        except Exception:
            pass
    if not triggered:
        out.append("✅ **所有指标在阈值内，无紧急 action**。继续按 30 天目标推进。")
    else:
        # Sort P0 → P1 → P2
        order = {"P0": 0, "P1": 1, "P2": 2}
        triggered.sort(key=lambda x: order.get(x[0], 9))
        for prio, title, body in triggered:
            out.append(f"### [{prio}] {title}")
            out.append("")
            for line in body.split("\n"):
                out.append(f"> {line}")
            out.append("")
    out.append("")

    # Key Stats — 一表全览
    out.append("## 📊 Key Stats（今日 vs 昨日）")
    out.append("")
    out.append("| 关键词 | 标签 | 今日 | 昨日 | Δ | 目标 |")
    out.append("|--------|------|------|------|---|------|")
    for query, hosts, label, target, _ in QUERIES:
        t = today.get(query, {})
        y = yesterday.get(query, {}) if yesterday else {}
        if query.startswith("site:"):
            tcnt = t.get("count", 0)
            ycnt = y.get("count", 0) if y else 0
            delta = f"{tcnt-ycnt:+d}" if y else "🆕"
            out.append(f"| `{query}` | {label} | **{tcnt}** | {ycnt} | {delta} | ≥{target} |")
        else:
            tpos = t.get("pos")
            ypos = y.get("pos") if y else None
            tstr = f"#{tpos}" if tpos else "off-100"
            ystr = f"#{ypos}" if ypos else "off-100"
            delta = _delta(tpos, ypos)
            emoji = _emoji(tpos, target)
            out.append(f"| {query} | {label} | {emoji} {tstr} | {ystr} | {delta} | top {target} |")
    out.append("")

    # Top movers
    movers = []
    if yesterday:
        for query, _, _, _, _ in QUERIES:
            if query.startswith("site:"):
                continue
            tpos = today.get(query, {}).get("pos")
            ypos = yesterday.get(query, {}).get("pos")
            d = _delta_int(tpos, ypos)
            if abs(d) >= 5:
                movers.append((d, query, tpos, ypos))
    if movers:
        out.append("## 🚀 今日大波动（≥5 位）")
        out.append("")
        movers.sort(key=lambda m: -m[0])
        for d, q, tpos, ypos in movers:
            arrow = "↑" if d > 0 else "↓"
            out.append(f"- **{arrow} {abs(d)}**: `{q}` — {ypos or 'off-100'} → {tpos or 'off-100'}")
        out.append("")

    # Footer
    out.append("---")
    out.append("")
    out.append(f"_生成于 {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')} · 数据源：SerpApi (Google US, num=20)_")
    out.append(f"_脚本：[scripts/seo_geo_report.py]({today_path.relative_to(ROOT)})_")

    print("\n".join(out))


if __name__ == "__main__":
    main()
