"""AI 商业洞察总结模块 — 基于采集数据生成竞品分析总结

Two-pass synthesis architecture (added 2026-06-11):
  Pass 1 — _extract_facts_pass1(): convert raw data dicts into a
           normalized facts JSON with explicit `source` attribution
           per fact (homepage / dataforseo / wayback / producthunt /
           github / inference / unknown). Cheap, structured-output
           LLM call — no prose, can't hallucinate freely.
  Pass 2 — generate_ai_summary(): prose synthesis bound to the
           facts JSON. The prompt forbids any claim not citing a
           fact key like [fact:traffic.monthly_visits]. Numeric
           drift is caught by the fact-check regex below.
  Pass 3 — _apply_confidence_markers(): post-processes the prose
           to convert [fact:KEY] markers into colored confidence
           badges:
             🟢 (multi-source verified)
             🟡 (single source)
             🔴 (inference / no source)
           So users see at-a-glance which claims to trust vs verify.

Falls back gracefully: if Pass 1 fails, we use the original
context-string flow and just attach a "confidence:unknown" tag.
"""
import asyncio
import httpx
import json
import logging
import os
import re

log = logging.getLogger(__name__)


# ─── Pass 1: Facts extraction ────────────────────────────────────────────────
# Pulls a STRUCTURED facts dict from the raw data modules. Each value carries
# an explicit `source` field so Pass 2's prose can render a confidence badge
# next to every claim. Deterministic — no LLM in this step. The LLM in Pass 2
# is constrained to only use facts that appear here.

_INFERENCE = "inference"   # LLM-derived, no direct source
_UNKNOWN   = "unknown"     # data was missing
SOURCE_RANK = {  # higher number = higher trust in cross-source resolution
    "dataforseo":   4,
    "github":       4,
    "tinyfish":     4,
    "producthunt":  4,
    "homepage":     3,
    "wayback":      3,
    "social":       3,
    _INFERENCE:     1,
    _UNKNOWN:       0,
}


def _f(value, source):
    """Wrap a fact value with its source for downstream resolution."""
    if value in (None, "", [], {}):
        return None
    return {"v": value, "src": source}


def _extract_facts(product_name: str, url: str, website: dict, social: dict,
                   traffic: dict, producthunt: dict, pricing: dict = None,
                   github_oss: dict = None, growth_analysis: dict = None,
                   traffic_peaks: dict = None) -> dict:
    """Pass-1 fact extraction. Returns a tagged facts JSON.

    Each leaf carries {v: value, src: source}. The keys are stable and
    referenced from prose via `[fact:dotted.path]` markers, e.g.
    `[fact:traffic.monthly_visits]`.
    """
    facts: dict = {"product": {"name": product_name, "url": url}}

    # ── Product / website ────────────────────────────────────────────────
    ws = website or {}
    cur = ws.get("current_site", {}) or ws.get("current", {}) or {}
    if cur.get("slogan"):
        facts.setdefault("product", {})["slogan"] = _f(cur["slogan"], "homepage")
    if cur.get("meta_description"):
        facts["product"]["meta_description"] = _f(
            cur["meta_description"][:300], "homepage"
        )
    feats = cur.get("features") or {}
    active = [k for k, v in feats.items() if v]
    if active:
        facts["product"]["features_on_homepage"] = _f(active[:15], "homepage")
    if ws.get("first_seen"):
        facts["product"]["first_seen"] = _f(ws["first_seen"], "wayback")
    if ws.get("total_snapshots"):
        facts["product"]["wayback_snapshots"] = _f(ws["total_snapshots"], "wayback")

    # ── Pricing ──────────────────────────────────────────────────────────
    pr = pricing or {}
    if pr.get("tiers"):
        # Normalize tier shape (different fetchers produce different keys).
        tiers = []
        for t in pr["tiers"][:8]:
            if isinstance(t, dict):
                tiers.append({
                    k: t.get(k) for k in ("name", "price", "period", "features")
                    if t.get(k) is not None
                })
        if tiers:
            facts["pricing"] = {"tiers": _f(tiers, "homepage")}
        if pr.get("has_free_tier") is not None:
            facts.setdefault("pricing", {})["has_free_tier"] = _f(
                pr["has_free_tier"], "homepage"
            )

    # ── Traffic / DataForSEO ─────────────────────────────────────────────
    tr = traffic or {}
    rank = tr.get("domain_rank") or {}
    tf: dict = {}
    if rank.get("organic_traffic"):
        tf["monthly_organic_visits"] = _f(rank["organic_traffic"], "dataforseo")
    if rank.get("total_keywords"):
        tf["total_keywords"] = _f(rank["total_keywords"], "dataforseo")
    if rank.get("keywords_top1"):
        tf["keywords_top1"] = _f(rank["keywords_top1"], "dataforseo")
    if rank.get("keywords_top10"):
        tf["keywords_top10"] = _f(rank["keywords_top10"], "dataforseo")
    if rank.get("estimated_paid_cost"):
        tf["equiv_paid_ad_cost_usd_per_month"] = _f(
            rank["estimated_paid_cost"], "dataforseo"
        )
    bl = tr.get("backlinks") or {}
    if bl.get("backlinks"):
        tf["backlinks"] = _f(bl["backlinks"], "dataforseo")
    if bl.get("referring_domains"):
        tf["referring_domains"] = _f(bl["referring_domains"], "dataforseo")
    if bl.get("domain_rank"):
        tf["domain_rank"] = _f(bl["domain_rank"], "dataforseo")
    history = tr.get("historical", {}).get("history") or []
    if history:
        tf["history_6mo"] = _f([
            {"date": h.get("date"),
             "traffic": h.get("organic_traffic"),
             "keywords": h.get("keywords")}
            for h in history[-6:]
        ], "dataforseo")
    if tf:
        facts["traffic"] = tf

    # Top keywords (separate node for prose to cite individually)
    kw = (tr.get("top_keywords") or {})
    kw_list = kw.get("keywords") if isinstance(kw, dict) else None
    if isinstance(kw_list, list) and kw_list:
        nb = kw.get("non_branded_keywords") or []
        display = (nb[:5] + [k for k in kw_list if k not in nb])[:8] if nb else kw_list[:8]
        facts["top_keywords"] = _f(
            [{"keyword": k.get("keyword"),
              "position": k.get("position"),
              "search_volume": k.get("search_volume")}
             for k in display if isinstance(k, dict)],
            "dataforseo",
        )

    # ── Social ───────────────────────────────────────────────────────────
    sm = social or {}
    channels = sm.get("channels") or {}
    soc: dict = {}
    for ch, data in channels.items():
        if isinstance(data, dict):
            followers = data.get("followers") or data.get("subscribers") or data.get("count")
            if followers:
                soc[ch] = {"followers": _f(followers, "social"),
                           "handle":    _f(data.get("handle"), "social")}
    if soc:
        facts["social"] = soc

    # ── Product Hunt ─────────────────────────────────────────────────────
    ph = producthunt or {}
    launches = ph.get("launches") or []
    if launches:
        first = launches[0] if isinstance(launches[0], dict) else {}
        facts["producthunt"] = {
            "launch_count":   _f(len(launches), "producthunt"),
            "first_launch":   _f(first.get("launched_at"), "producthunt"),
            "total_upvotes":  _f(sum(l.get("votes_count", 0) for l in launches), "producthunt"),
            "best_rank":      _f(min((l.get("rank", 999) for l in launches if l.get("rank")), default=None), "producthunt"),
        }
    if ph.get("comments_total"):
        facts.setdefault("producthunt", {})["comments_total"] = _f(
            ph["comments_total"], "producthunt"
        )

    # ── GitHub ───────────────────────────────────────────────────────────
    gh = github_oss or {}
    if gh.get("stars") is not None:
        facts["github"] = {
            "stars": _f(gh["stars"], "github"),
            "forks": _f(gh.get("forks"), "github"),
            "contributors": _f(gh.get("contributors_count"), "github"),
            "open_issues":  _f(gh.get("open_issues"), "github"),
            "last_commit":  _f(gh.get("last_commit_date"), "github"),
        }

    # ── Growth peaks ─────────────────────────────────────────────────────
    peaks = (traffic_peaks or {}).get("peaks") or []
    if peaks:
        facts["traffic_peaks"] = _f(
            [{"date": p.get("date"),
              "value": p.get("value"),
              "spike_multiplier": p.get("multiplier")}
             for p in peaks[:5]],
            "dataforseo",
        )

    # Drop any leaf where _f returned None (empty value cleanup).
    def _strip_none(d):
        if isinstance(d, dict):
            return {k: _strip_none(v) for k, v in d.items() if v is not None}
        return d
    return _strip_none(facts)


# ─── Pass 3: Confidence-badge post-processor ────────────────────────────────


_FACT_REF_RE = re.compile(r"\[fact:([a-zA-Z0-9_.]+)\]")


def _resolve_source(facts: dict, dotted: str) -> str:
    """Walk facts by dotted path. Return the `src` of the leaf, or _UNKNOWN."""
    cur = facts
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list):
            return _UNKNOWN
        else:
            return _UNKNOWN
    if isinstance(cur, dict) and "src" in cur:
        return cur["src"]
    return _UNKNOWN


def _resolve_fact_value(facts: dict, dotted: str):
    """Walk facts by dotted path. Return the `v` value of the leaf, or None.

    Different from _resolve_source — that returns the source label;
    this returns the actual value the LLM should have written.
    """
    cur = facts
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    if isinstance(cur, dict) and "v" in cur:
        return cur["v"]
    return None


# ─── Pass 2.5: Numeric fact-check ───────────────────────────────────────────
# After the LLM emits prose with [fact:KEY] citations, we double-check that
# the NUMBER it wrote before each marker actually matches the value in the
# facts JSON. The LLM occasionally rounds, fabricates a "close" number, or
# introduces a range when the fact is exact. Pass 2.5 catches those and
# REPLACES the wrong text with the canonical value, so the user always
# sees the source-of-truth number even if the LLM drifted.


# Captures things like:
#   "12,000 [fact:traffic.monthly_visits]"
#   "12K [fact:traffic.monthly_visits]"
#   "约 12000 [fact:traffic.monthly_visits]"
#   "$3,200 [fact:traffic.equiv_paid_ad_cost_usd_per_month]"
#   "8 个 [fact:traffic.keywords_top10]"
#   "2026-04-15 [fact:producthunt.first_launch]"
_NUM_BEFORE_FACT_RE = re.compile(
    r"(?P<lead>[$¥€£￥]?\s*"
    r"(?P<num>[\d][\d,]*(?:\.\d+)?(?:\s*[%KMB]|\s*万|\s*亿|\s*-\s*[\d][\d,]*)?)\s*)"
    r"(?:个|篇|条|次|名|位|月|days?|weeks?|months?|years?|hrs?|hours?|minutes?|days)?\s*"
    r"\[fact:(?P<key>[a-zA-Z0-9_.]+)\]"
)


def _parse_loose_number(s: str):
    """Parse a number string the LLM might have written: '12,000', '12K',
    '$3,200', '约 1.2万', '8'. Returns a float, or None on parse failure.
    Discards $ signs, commas, and trailing 个/篇/条 etc.
    """
    if not isinstance(s, str):
        return None
    raw = s.strip()
    # Strip currency / leading symbols
    raw = re.sub(r"^[\$¥€£￥约~]+\s*", "", raw)
    # Range? Take the lower bound for comparison.
    if "-" in raw:
        raw = raw.split("-")[0].strip()
    # Suffix multiplier
    mult = 1.0
    m = re.match(r"^([\d.,]+)\s*([KMB万亿]?)\s*$", raw)
    if not m:
        # try just the number part
        m2 = re.search(r"([\d][\d,]*(?:\.\d+)?)", raw)
        if not m2:
            return None
        try:
            return float(m2.group(1).replace(",", ""))
        except ValueError:
            return None
    num_s, suffix = m.group(1), m.group(2)
    try:
        n = float(num_s.replace(",", ""))
    except ValueError:
        return None
    if suffix == "K":
        n *= 1_000
    elif suffix == "M":
        n *= 1_000_000
    elif suffix == "B":
        n *= 1_000_000_000
    elif suffix == "万":
        n *= 10_000
    elif suffix == "亿":
        n *= 100_000_000
    return n


def _format_canonical(value):
    """Format a fact value for inline display. Numbers get thousand-separators."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


# Drift > this fraction triggers replacement. 1.5% absorbs harmless rounding
# (12000 → 12K written as "12.0K" then re-read as 12000) but catches the
# "200K" LLM hallucination when the fact says 12000.
_NUMERIC_DRIFT_TOLERANCE = 0.015


def _verify_numeric_claims(prose: str, facts: dict) -> tuple:
    """Scan prose for `NUMBER [fact:KEY]` patterns and verify each NUMBER
    matches `facts[KEY].v`. On mismatch, rewrite to the canonical number
    with a ⚠️ marker so the user sees both the corrected value AND that
    we caught an LLM drift.

    Returns: (rewritten_prose, list_of_fixes) where fixes is
        [(key, written, canonical), ...]
    """
    fixes: list = []
    if not prose or not facts:
        return prose, fixes

    def repl(m):
        written_full = m.group("lead").strip()
        written_num = m.group("num").strip()
        key = m.group("key")
        canonical = _resolve_fact_value(facts, key)
        if canonical is None:
            # Fact key doesn't resolve — leave for confidence pass to flag 🔴
            return m.group(0)

        # Skip date / string facts — we only verify numerics here.
        if not isinstance(canonical, (int, float)):
            return m.group(0)

        w = _parse_loose_number(written_num)
        c = float(canonical)
        if w is None:
            return m.group(0)

        # Drift check
        denom = max(abs(c), 1.0)
        drift = abs(w - c) / denom
        if drift <= _NUMERIC_DRIFT_TOLERANCE:
            return m.group(0)  # close enough — accept LLM's formatting

        # Mismatch — record & rewrite
        fixes.append({
            "key": key,
            "llm_wrote": written_full,
            "canonical": _format_canonical(canonical),
            "drift_pct": round(drift * 100, 1),
        })
        log.warning(
            "Numeric drift: key=%s llm=%r canonical=%r drift=%.1f%%",
            key, written_full, canonical, drift * 100,
        )
        # Replace just the leading number, keep the [fact:] marker for
        # the confidence pass to render its badge.
        canonical_str = _format_canonical(canonical)
        return f"{canonical_str}⚠️ [fact:{key}]"

    rewritten = _NUM_BEFORE_FACT_RE.sub(repl, prose)
    return rewritten, fixes


# Uncited-number sniff: catches NUMBERS that look specific (≥4 digits or
# K/M/万/亿 magnitude) but have NO [fact:] marker nearby. These are the
# highest hallucination risk — the LLM bypassed the citation rule.
_UNCITED_LARGE_NUM_RE = re.compile(
    r"(?<![\d.])(\d{1,3}(?:[,\d]{3,}|(?:\.\d+)?[KMB万亿])\b)(?![\d.])"
)


def _scan_uncited_numbers(prose: str, window: int = 60) -> list:
    """Return a list of {value, position} for large numbers not followed
    within `window` chars by a [fact:] citation. Caller can flag them or
    leave them — we don't auto-rewrite (we don't know the truth).
    """
    if not prose:
        return []
    suspicious: list = []
    for m in _UNCITED_LARGE_NUM_RE.finditer(prose):
        tail = prose[m.end():m.end() + window]
        if "[fact:" not in tail:
            suspicious.append({
                "value":  m.group(0),
                "pos":    m.start(),
                "context": prose[max(0, m.start() - 30):m.end() + 30],
            })
    return suspicious


def _confidence_emoji(src: str) -> str:
    if src in ("dataforseo", "github", "tinyfish", "producthunt"):
        return "🟢"
    if src in ("homepage", "wayback", "social"):
        return "🟡"
    return "🔴"


def _apply_confidence_markers(prose: str, facts: dict) -> str:
    """Replace [fact:KEY] markers with a small confidence badge inline."""
    def repl(m):
        key = m.group(1)
        src = _resolve_source(facts, key)
        emoji = _confidence_emoji(src)
        # Render as `🟢` only (the prose already has the value text inline).
        return f"{emoji}<sup class=\"src-tag\" title=\"source: {src}\">{src[:4]}</sup>"
    out = _FACT_REF_RE.sub(repl, prose)

    # Add a legend footer if any badges appeared.
    if "🟢" in out or "🟡" in out or "🔴" in out:
        out += (
            "\n\n---\n\n**Source confidence**: "
            "🟢 high-trust API data (DataForSEO / GitHub / TinyFish / PH) · "
            "🟡 scraped from homepage / Wayback / social · "
            "🔴 inferred — verify before quoting."
        )
    return out


async def generate_ai_summary(product_name: str, url: str, website: dict, social: dict, traffic: dict, producthunt: dict, growth_strategy: dict = None, growth_analysis: dict = None, traffic_peaks: dict = None, pricing: dict = None, github_oss: dict = None) -> dict:
    """Two-pass synthesis: extract verified facts (Pass 1) → constrained
    prose synthesis (Pass 2) → confidence badges (Pass 3)."""

    def _safe(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return f"[数据解析错误: {str(e)[:80]}]"

    # ── Pass 1: deterministic fact extraction (no LLM, no hallucination)
    facts = _safe(_extract_facts, product_name, url, website, social, traffic,
                  producthunt, pricing, github_oss, growth_analysis, traffic_peaks)
    if isinstance(facts, str):  # _safe returned an error string
        log.warning("Fact extraction failed: %s", facts)
        facts = {}
    facts_json_str = json.dumps(facts, ensure_ascii=False, indent=2)
    log.info("Pass-1 facts extracted: %d top-level fields, JSON %d chars",
             len(facts), len(facts_json_str))

    context        = _safe(_build_context, product_name, url, website, social, traffic, producthunt, growth_analysis, traffic_peaks)
    wayback_insight = _safe(_build_wayback_insight, website)
    ph_insight     = _safe(_build_ph_insight, producthunt)
    playbook_insight = _safe(_build_playbook_insight, growth_strategy)
    social_insight = _safe(_build_social_insight, social)
    growth_insight = _safe(_build_growth_insight, growth_analysis, traffic_peaks)
    pricing_insight = _safe(_build_pricing_insight, pricing)
    github_insight  = _safe(_build_github_insight, github_oss)

    prompt = f"""你是一位顶级出海产品增长顾问，曾帮助多个开源产品从 0 到 60K+ GitHub stars，参与过多个 PLG 产品的 0→1 阶段策略制定。

以下是对竞品 **{product_name}** ({url}) 的系统化调研数据，来源包括 Wayback Machine 历史快照、Product Hunt 发布记录、DataForSEO 流量数据、社交媒体数据以及 Gingiris Playbook 智能匹配。

请基于这些真实数据，输出一份能够直接指导后来者的深度竞品分析报告。

---

## ✅ 已校验事实（FACTS JSON — 最高优先级，每条 finding 必须引用）

下面是从原始数据里**程序抽取**的结构化事实，每条带 `src` 字段表明出处。
**报告里的每个具体数字、URL、时间节点、价格、关注度数据**，**必须**引用这里的 fact key — 格式 `[fact:dotted.path]`，例如 `[fact:traffic.monthly_organic_visits]`。
**不在 FACTS JSON 里的数字 / 时间 / URL，禁止写入报告**。如果想说但 FACTS 里没有，写"FACTS 未覆盖"或省略。

```json
{facts_json_str}
```

引用示例：
> 月访问 12,000 [fact:traffic.monthly_organic_visits]，主要来自 8 个 Top-10 关键词 [fact:traffic.keywords_top10]。

---

## 原始调研数据（仅供参考，**不要**从这里直接取数字 — 取数字必须走 FACTS JSON）

{context}

## Wayback Machine 历史洞察（独家时序信号）

{wayback_insight}

## Product Hunt 发布分析

{ph_insight}

## 社交媒体渠道深度

{social_insight}

## 增长与峰值分析

{growth_insight}

## 定价结构分析

{pricing_insight}

## GitHub 开源数据

{github_insight}

## Gingiris Playbook 匹配

{playbook_insight}

---

## 请输出以下完整分析（中文，要求：每个结论必须有数据支撑，严禁空泛表述）：

### 一、产品定位与目标用户（ICP）

**核心用户画像**：基于数据（Slogan演变、关键词、PH评论主题、社区讨论内容），描述这个产品的理想客户是谁。具体到职业、痛点、使用场景。如果数据足够，区分 2-3 个用户层级（如：核心用户、次级用户、企业用户）。

**市场定位策略**：这个产品在市场上如何差异化？是抢了谁的市场？回避了哪些竞争？用数据说明。

### 二、商业模式拆解

**定价模型**：基于上方"定价结构分析"中的真实抓取数据，描述其定价层级（套餐名称、价格、功能边界、付费墙触发点）。如果没有定价数据，根据官网结构推断并标注"推断"。

**变现策略**：免费用户如何转化为付费用户？核心升级触发点是什么？

**收入规模估算**：基于流量数据和行业平均转化率，给出保守的月收入范围估算（需标注假设条件）。

### 三、增长密码（做对了什么）

提炼 4-6 个核心增长策略，每条必须：
- 有具体数据支撑（数字、时间节点、比较基准）
- 说明"为什么有效"而不只是"做了什么"
- 至少 1 条基于 Wayback 历史对比
- 至少 1 条基于 PH/社区数据
- 至少 1 条关于内容/传播策略

### 四、增长飞轮

用一个简洁的逻辑链描述这个产品的增长正循环（A → B → C → 回到 A）。必须是这个产品特有的飞轮，不能套用通用模板。

### 五、内容与传播策略

基于社交媒体数据、流量峰值、PH发布节奏，分析：
- 哪些渠道是核心获客渠道？
- 爆发期的内容是什么类型？（Demo视频？用户故事？技术帖？）
- 关键 Launch 节点的传播路径
- 创始人/团队的个人品牌是否发挥了作用？

### 六、给后来者的战术建议

如果你要做一个类似产品，基于这份数据给出 5 条最重要的建议。要求：
- 具体到可以今天就开始执行的行动
- 排序：按影响力从高到低
- 引用 Gingiris Playbook 作为行动框架
- 每条建议说明"不这样做的代价是什么"

### 七、风险与机会

**主要风险**（2-3 条，有数据支撑）：这个产品目前的增长隐患或结构性弱点是什么？

**市场机会**（1-2 条）：作为后来者，哪里有机会超越它？

---

## ⚠️ 必须遵守的约束：

1. **每个具体数字 / URL / 时间 / 价格必须紧跟 `[fact:KEY]` 引用**。例：
   - ✅ "月访问 12,000 [fact:traffic.monthly_organic_visits]"
   - ❌ "月访问约 12,000"（缺 fact 引用）
   - ❌ "月访问可能在 10K-20K 之间"（FACTS 没数据时不要瞎猜）
2. **FACTS JSON 没覆盖的维度**写"FACTS 未覆盖（需用户提供）"或省略，不要凭印象推断数字。
3. **严禁编造时间节点**。只有 FACTS 里出现的日期才能用，禁止"可能""推断""大约"修饰时间。
4. **社交账号可能误匹配**。如账号描述与产品不符，标注"⚠️ 此账号可能不属于目标产品"并跳过该数据。
5. **当前日期是 2026 年 6 月**。不要将未来事件当作已发生。
6. **战略观点和"推断"型结论**（飞轮、用户画像、市场机会等）不要求 `[fact:]` 引用，但要明确标"基于上述事实推断："。
7. 语言风格：像军师，直接，不废话，每段不超过 150 字。

---

## 最后，额外输出一个 JSON 块（用 ```json 包裹），格式如下：

```json
{{"killer_move": "一句话描述竞品的核心杀手锏（15字以内）", "growth_pattern": "从以下选一个：开源社区驱动|PLG 产品驱动|内容 SEO 驱动|社交病毒传播|模板飞轮驱动|企业销售驱动", "replicability": "高|中|低", "one_line_verdict": "一句话战略判定（20字以内）"}}
```

这个 JSON 会被程序自动提取，必须严格遵守格式。"""

    _log = logging.getLogger(__name__)
    _log.warning("generate_ai_summary: prompt built, len=%d chars, calling _call_llm", len(prompt))

    result = await _call_llm(prompt)

    _log.warning("generate_ai_summary: _call_llm returned success=%s source=%s", result.get("success"), result.get("source"))

    # Extract verdict JSON from AI response
    if result.get("success") and result.get("content"):
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', result["content"], re.DOTALL)
        if json_match:
            try:
                verdict = json.loads(json_match.group(1))
                result["verdict"] = verdict
                # Remove the JSON block from display content
                result["content"] = result["content"][:json_match.start()].rstrip()
            except Exception:
                pass

        # Pass 2.5 — numeric fact-check. Catches the LLM hallucinating
        # "around 200K" when DataForSEO said 12,000. Auto-rewrites with
        # the canonical value + ⚠️ marker. Runs BEFORE the confidence
        # badges so the markers Pass 3 sees are still raw [fact:KEY].
        try:
            corrected, fixes = _verify_numeric_claims(result["content"], facts)
            result["content"] = corrected
            result["numeric_fixes"] = fixes
            suspicious = _scan_uncited_numbers(result["content"])
            result["uncited_numbers"] = suspicious
            if fixes:
                log.warning(
                    "Pass-2.5 caught %d numeric drift(s): %s",
                    len(fixes),
                    [(f["key"], f["llm_wrote"], f["canonical"]) for f in fixes[:5]],
                )
            if suspicious:
                log.info(
                    "Pass-2.5: %d uncited large numbers — LLM bypassed citation",
                    len(suspicious),
                )
        except Exception as e:
            log.warning("Pass-2.5 numeric fact-check failed: %s", e)

        # Pass 3 — replace [fact:KEY] markers with confidence badges +
        # append the legend footer. Stays in `content` so the existing
        # report renderer doesn't need to change.
        try:
            result["content"] = _apply_confidence_markers(
                result["content"], facts
            )
            # Count how many distinct fact keys were actually cited — a
            # quick proxy for "did the LLM follow the citation rule?"
            cited = set(_FACT_REF_RE.findall(result["content"]))
            result["citations_count"] = len(cited)
            if cited and facts:
                log.info("Pass-3 confidence applied: %d distinct fact citations",
                         len(cited))
        except Exception as e:
            log.warning("Pass-3 confidence application failed: %s", e)

    # Always attach the facts JSON to the result — frontend / debugging
    # downstream may want to surface it as a "data dossier" tab.
    result["facts"] = facts

    return result


async def generate_ai_summary_from_text(product_name: str, text_description: str) -> dict:
    """从用户提供的文字描述或 PDF 提取内容生成竞品/产品分析（无需网站 URL）"""

    prompt = f"""你是一位顶级出海产品增长顾问，曾帮助多个开源产品从 0 到 60K+ GitHub stars。

用户提供了以下关于产品 **{product_name}** 的描述材料（可能来自 pitch deck、产品文档、竞品介绍等）：

---

{text_description[:8000]}

---

请基于以上信息，输出一份结构化的产品增长分析报告（中文，每个结论尽量有依据，无法判断的维度请标注"材料不足"）：

### 一、产品定位与目标用户（ICP）

**核心用户画像**：这个产品服务于哪类用户？职业、痛点、使用场景。

**市场定位**：在市场上如何差异化？占据哪个细分位置？

### 二、商业模式拆解

**定价与变现**：描述其收费逻辑（或推断可能的商业模式）。免费策略和付费钩子是什么？

**收入潜力**：根据目标市场和产品定位，估算收入范围（标注假设）。

### 三、增长路径分析

基于产品特性，推断：
- 最适合的用户获取渠道（PLG/SLG/社区/内容）
- 早期 0→100 用户的关键动作
- 可能的病毒传播机制

### 四、增长飞轮

描述这个产品类型的典型增长正循环（A → B → C → 回到 A）。

### 五、给创始人/竞争者的战术建议

5 条最重要的可执行建议：
- 今天就可以开始的行动
- 不这样做的代价

### 六、风险与机会

**主要风险**（2-3 条）：这类产品的典型陷阱和竞争威胁。

**市场机会**（1-2 条）：当前市场的空白点或进入时机。

---

语言风格：像军师，直接，不废话。每段不超过 150 字。"""

    result = await _call_llm(prompt)
    return result


def _build_wayback_insight(website: dict) -> str:
    ws = website or {}
    parts = []
    timeline = ws.get("deep_timeline", [])
    valid = [t for t in timeline if not t.get("error") and t.get("date")]
    changes = ws.get("key_changes", [])
    first_seen = ws.get("first_seen", "N/A")

    if not valid and not changes:
        return "Wayback Machine 无历史快照数据。"

    parts.append(f"- 首次收录：**{first_seen}**，分析快照：**{len(valid)}** 个")

    slogans = [(t.get("date", ""), t.get("slogan", "")) for t in valid if t.get("slogan")]
    if len(slogans) >= 2:
        parts.append("- Slogan 演变轨迹：")
        for date, slogan in slogans:
            parts.append(f"  · {date}: 「{slogan[:80]}」")

    if len(valid) >= 2:
        first_f = set(k for k, v in valid[0].get("features", {}).items() if v)
        last_f = set(k for k, v in valid[-1].get("features", {}).items() if v)
        added = last_f - first_f
        removed = first_f - last_f
        if added:
            parts.append(f"- 新增功能模块（{valid[0].get('date','?')}→{valid[-1].get('date','?')}）：{', '.join(added)}")
        if removed:
            parts.append(f"- 移除功能模块：{', '.join(removed)}")

    if len(valid) >= 2:
        first_struct = valid[0].get("structure_summary", [])
        last_struct = valid[-1].get("structure_summary", [])
        if first_struct and last_struct:
            parts.append(f"- 页面结构演变：{valid[0].get('date','?')} 共 {len(first_struct)} 个模块 → {valid[-1].get('date','?')} 共 {len(last_struct)} 个模块")

    if changes:
        parts.append(f"- 关键变化节点（{len(changes)} 次）：")
        for c in changes[:6]:
            parts.append(f"  · {c['from_date']}→{c['to_date']}: {'; '.join(c['changes'][:4])}")

    return "\n".join(parts)


def _build_ph_insight(producthunt: dict) -> str:
    ph = producthunt or {}
    if not ph.get("found"):
        return "该产品未在 Product Hunt 上发布，无 PH 数据。"

    parts = []
    launch_count = 1 + len(ph.get("other_launches", []))
    votes = ph.get("votes", 0)
    comments = ph.get("comments", 0)
    rating = ph.get("reviews_rating", 0)
    reviews_count = ph.get("reviews_count", 0)

    parts.append(f"- **{launch_count}** 次发布，最高 **{votes:,} votes**，**{comments:,} comments**")
    if rating:
        parts.append(f"- 用户评分 **{rating:.1f}**（{reviews_count} 条评价）")
    if ph.get("tagline"):
        parts.append(f"- 主 Launch Tagline：「{ph['tagline']}」")
    if ph.get("launch_date"):
        parts.append(f"- 首次发布时间：{ph['launch_date']}")

    other = ph.get("other_launches", [])
    if other:
        all_launches = [{"name": ph.get("name", ""), "votes": votes, "launch_date": ph.get("launch_date", ""), "tagline": ph.get("tagline", "")}]
        all_launches.extend(other)
        all_launches.sort(key=lambda x: x.get("launch_date", ""))
        parts.append(f"- 多波 Launch 详情：")
        for i, l in enumerate(all_launches, 1):
            tag = f"「{l.get('tagline', '')[:60]}」" if l.get("tagline") else ""
            parts.append(f"  · 第{i}次 ({l.get('launch_date', '?')}): ⬆{l.get('votes', 0):,} {tag}")

    if ph.get("top_comments"):
        parts.append("- 高赞用户评论（反映真实市场声音）：")
        for c in ph["top_comments"][:3]:
            parts.append(f"  · {c.get('body', '')[:100]}")

    return "\n".join(parts)


def _build_social_insight(social: dict) -> str:
    sm = social or {}
    channels = sm.get("channels", {})
    parts = []

    for platform, v in channels.items():
        if not v.get("detected"):
            continue
        line = f"- **{v.get('platform', platform)}** {v.get('handle', '')}"
        if v.get("followers"):
            line += f"：{v['followers']:,} 粉丝"
        if v.get("stars_total"):
            line += f"：{v['stars_total']:,} stars"
        if v.get("subreddit_members"):
            line += f"：{v['subreddit_members']:,} 成员"
        if v.get("subscribers"):
            line += f"：{v['subscribers']:,} 订阅"
        if v.get("note"):
            line += f"（{v['note'][:60]}）"
        parts.append(line)

        top = v.get("top_tweets") or v.get("top_posts", [])
        if top:
            top_sorted = sorted(top, key=lambda x: x.get("likes", 0) + x.get("retweets", 0), reverse=True)
            for tw in top_sorted[:2]:
                txt = (tw.get("text") or tw.get("title", ""))[:100]
                likes = tw.get("likes", 0)
                retweets = tw.get("retweets", 0)
                views = tw.get("views", 0)
                if txt:
                    parts.append(f"  · 热帖：「{txt}」❤{likes:,} 🔁{retweets:,}" + (f" 👁{views:,}" if views else ""))

    pm = sm.get("propagation_metrics", {})
    if pm.get("total_participants"):
        parts.append(f"- 传播规模：{pm['total_participants']:,} 参与者，{pm.get('total_engagement', 0):,} 总互动")

    return "\n".join(parts) if parts else "社交媒体数据不足。"


def _build_growth_insight(growth_analysis: dict, traffic_peaks: dict) -> str:
    parts = []
    ga = growth_analysis or {}
    tp = traffic_peaks or {}

    story = ga.get("zero_to_one_story", {})
    if story.get("milestones"):
        parts.append("**0→1 关键里程碑：**")
        for m in story["milestones"][:6]:
            date = m.get("date", "")
            event = m.get("event", "")
            impact = m.get("traffic_impact", "")
            parts.append(f"  · {date}: {event}" + (f"（{impact}）" if impact else ""))

    channels = ga.get("channel_breakdown", [])
    if channels:
        parts.append("**渠道拆解：**")
        for ch in channels[:5]:
            pct = ch.get("percentage", 0)
            name = ch.get("channel", "")
            followers = ch.get("followers", 0)
            parts.append(f"  · {name}: {pct}%" + (f"，{followers:,} 粉丝" if followers else ""))

    peaks = tp.get("peaks") if isinstance(tp, dict) else None
    if isinstance(peaks, list) and peaks:
        parts.append("**流量爆发节点：**")
        for p in peaks[:4]:
            if not isinstance(p, dict): continue
            date = p.get("date", "")
            cause = p.get("cause", "")
            multiplier = p.get("traffic_multiplier", 0)
            parts.append(f"  · {date}: {cause}" + (f"（流量 x{multiplier}）" if multiplier else ""))

    return "\n".join(parts) if parts else "增长分析数据不足。"


def _build_playbook_insight(growth_strategy: dict) -> str:
    gs = growth_strategy or {}
    primary = gs.get("primary")
    if not primary:
        return "Playbook 匹配数据不足。"

    parts = [f"- **主推 Playbook**: {primary.get('emoji','')} {primary.get('label','')}（匹配得分 {primary.get('score',0)}/4）"]
    parts.append(f"  描述: {primary.get('description','')}")
    if primary.get("url"):
        parts.append(f"  链接: {primary['url']}")
    if primary.get("reasons"):
        parts.append("  匹配原因: " + " / ".join(primary["reasons"][:3]))
    if primary.get("custom_tips"):
        parts.append("  定制建议:")
        for tip in primary["custom_tips"][:3]:
            parts.append(f"    · {tip}")
    for s in (gs.get("secondary") or [])[:2]:
        parts.append(f"- **辅助**: {s.get('emoji','')} {s.get('label','')}（得分 {s.get('score',0)}/4）")
    return "\n".join(parts)


def _build_context(product_name, url, website, social, traffic, producthunt, growth_analysis=None, traffic_peaks=None) -> str:
    parts = []
    ws = website or {}
    cur = ws.get("current_site", {}) or ws.get("current", {})

    parts.append(f"**产品**: {product_name} | **URL**: {url}")
    parts.append(f"**域名首次出现**: {ws.get('first_seen', 'N/A')} | **历史快照数**: {ws.get('total_snapshots', 0)}")
    if cur.get("slogan"):
        parts.append(f"**当前 Slogan**: {cur['slogan']}")
    if cur.get("meta_description"):
        parts.append(f"**Meta Description**: {cur['meta_description'][:200]}")

    features = cur.get("features", {})
    active = [k for k, v in features.items() if v]
    if active:
        parts.append(f"**官网已有功能**: {', '.join(active)}")

    struct = cur.get("structure_summary", [])
    if struct:
        parts.append(f"**页面结构**: {' → '.join(struct[:8])}")

    tr = traffic or {}
    rank = tr.get("domain_rank", {})
    if rank.get("organic_traffic"):
        parts.append(f"\n**月均有机流量**: {rank['organic_traffic']:,} | **关键词数**: {rank.get('total_keywords',0):,}")
        parts.append(f"**Top1 关键词**: {rank.get('keywords_top1',0)} | **Top10**: {rank.get('keywords_top10',0)}")
        parts.append(f"**等效付费广告成本**: ${rank.get('estimated_paid_cost',0):,}/月")
    bl = tr.get("backlinks", {})
    if bl.get("backlinks"):
        parts.append(f"**反链**: {bl['backlinks']:,} | **引用域名**: {bl.get('referring_domains',0):,} | **DR**: {bl.get('domain_rank',0)}")

    hist = tr.get("historical", {}).get("history", [])
    if hist:
        parts.append("**流量历史趋势**（近 6 个月）:")
        for h in hist[-6:]:
            parts.append(f"  {h['date']}: {h.get('organic_traffic',0):,} 有机 / {h.get('keywords',0):,} 关键词")

    kw = tr.get("top_keywords", {})
    kw_list = kw.get("keywords") if isinstance(kw, dict) else None
    if isinstance(kw_list, list) and kw_list:
        # Show non-branded keywords first (higher signal for competitor analysis)
        nb = kw.get("non_branded_keywords") or []
        display_kw = (nb[:5] + [k for k in kw_list if k not in nb])[:8] if nb else kw_list[:8]
        parts.append("**Top 非品牌关键词**:")
        for k in display_kw:
            if isinstance(k, dict):
                parts.append(f"  「{k.get('keyword','')}」位置#{k.get('position',0)} 月搜索量{k.get('search_volume',0):,}")

    sm = social or {}
    ch = sm.get("channels", {})
    social_lines = []
    for pf, v in ch.items():
        if v.get("detected") and (v.get("followers") or v.get("stars_total") or v.get("subreddit_members")):
            n = v.get("followers") or v.get("stars_total") or v.get("subreddit_members") or 0
            social_lines.append(f"{v.get('platform', pf)} {v.get('handle','')} {n:,}")
    if social_lines:
        parts.append(f"\n**社交媒体**: {' | '.join(social_lines)}")

    ph = producthunt or {}
    if ph.get("found"):
        parts.append(f"**Product Hunt**: {ph.get('launch_date','')} ⬆{ph.get('votes',0):,} votes ⭐{ph.get('reviews_rating',0):.1f}({ph.get('reviews_count',0)}条)")

    return "\n".join(parts)


def _build_pricing_insight(pricing: dict) -> str:
    """生成定价洞察文本，供 AI 提示词使用"""
    p = pricing or {}
    if not p.get("found"):
        return "未能抓取到定价页数据（可能无公开定价或为纯企业询价模式）。"

    lines = []
    lines.append(f"**来源**: {p.get('source_url', '—')}")
    lines.append(f"**定价模式**: {p.get('model', '—')} | **有免费套餐**: {'是' if p.get('free_plan') else '否'} | **免费试用**: {'是' if p.get('free_trial') else '否'}")
    if p.get("annual_discount"):
        lines.append(f"**年付折扣**: {p['annual_discount']}")

    tiers = p.get("tiers", [])
    if tiers:
        lines.append(f"\n**定价层级**（共 {len(tiers)} 档）:")
        for t in tiers:
            price_str = "免费" if t.get("price_monthly") == 0 else f"${t.get('price_monthly', '?')}/月"
            if t.get("price_annual_monthly"):
                price_str += f"（年付 ${t['price_annual_monthly']}/月）"
            features_str = " / ".join(t.get("features", [])[:3])
            lines.append(f"  - **{t.get('name', '—')}**: {price_str} — {features_str}")

    insights = p.get("insights", [])
    if insights:
        lines.append("\n**定价洞察**:")
        for ins in insights:
            lines.append(f"  • {ins}")

    return "\n".join(lines)


def _build_github_insight(github_oss: dict) -> str:
    """生成 GitHub 开源数据洞察文本，供 AI 提示词使用"""
    g = github_oss or {}
    if not g.get("found"):
        return "该产品无 GitHub 开源数据，或非开源项目。"

    parts = []
    stars = g.get("stars", 0)
    forks = g.get("forks", 0)
    contributors = g.get("contributors", 0)
    created = g.get("created_at", "")
    license_ = g.get("license", "")
    language = g.get("language", "")
    repo_url = g.get("repo_url", "")

    parts.append(f"- 仓库：{repo_url}（创建于 {created}，主语言 {language}，协议 {license_ or '未知'}）")
    parts.append(f"- **{stars:,} Stars** | {forks:,} Forks | {contributors:,} 贡献者")

    # Star milestones
    milestones = g.get("milestones", [])
    if milestones:
        parts.append("- Star 里程碑时间轴：")
        for m in milestones:
            parts.append(f"  · {m['label']} stars：{m['month']}")

    # Peak growth
    star_history = g.get("star_history", [])
    if star_history:
        peaks = sorted(
            [(h["month"], h["gain"]) for h in star_history if h.get("gain", 0) > 200],
            key=lambda x: x[1], reverse=True
        )
        if peaks:
            top = peaks[:3]
            parts.append("- 增长峰值月份（对应重大发布节点）：")
            for month, gain in top:
                parts.append(f"  · {month} 单月新增 {gain:,} stars")

    # Latest release
    rel = g.get("latest_release")
    if rel:
        parts.append(f"- 最新发布：{rel.get('tag', '')} ({rel.get('date', '')})  {rel.get('name', '')}")

    # Auto insights
    insights = g.get("insights", [])
    if insights:
        parts.append("- 自动洞察：")
        for ins in insights[:5]:
            parts.append(f"  · {ins}")

    return "\n".join(parts)


async def _call_llm(prompt: str) -> dict:
    """LLM call: DeepSeek primary, OpenRouter fallback (opt-in).

    Old TeamoRouter path was removed 2026-06-11 after the provider's
    URL changed, model catalog changed, AND the account ran out of
    balance simultaneously — three failure modes that all routed
    through 'fallback to DeepSeek anyway' while burning 6+ min of
    retry latency per LLM call. See growth_audit._call_llm_long for
    the same pattern used by the audit pipeline.
    """
    # ─── Primary: DeepSeek ───────────────────────────────────────────────
    ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not ds_key:
        try:
            ds_key = open(os.path.expanduser("~/.cola/secrets/deepseek_api_key")).read().strip()
        except FileNotFoundError:
            pass

    last_ds_err = None
    if ds_key:
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                    resp = await client.post(
                        "https://api.deepseek.com/chat/completions",
                        headers={"Authorization": f"Bearer {ds_key}",
                                 "Content-Type": "application/json"},
                        json={
                            "model": "deepseek-chat",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.6,
                            "max_tokens": 4000,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        return {"success": True, "content": content, "source": "DeepSeek"}
                    last_ds_err = "empty response"
            except Exception as e:
                last_ds_err = str(e)
            if attempt < 1:
                await asyncio.sleep(3)

    # ─── Fallback: OpenRouter (opt-in via OPENROUTER_API_KEY) ────────────
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    last_or_err = None
    if or_key:
        model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                    resp = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {or_key}",
                            "Content-Type":  "application/json",
                            "HTTP-Referer":  "https://www.analook.com",
                            "X-Title":       "Analook AI Summary",
                        },
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.6,
                            "max_tokens": 4000,
                        },
                    )
                    if resp.status_code in (401, 402, 403):
                        last_or_err = f"HTTP {resp.status_code}"
                        break
                    resp.raise_for_status()
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        return {"success": True, "content": content,
                                "source": f"OpenRouter ({data.get('model', model)})"}
                    last_or_err = "empty response"
            except Exception as e:
                last_or_err = str(e)
            if attempt < 1:
                await asyncio.sleep(2)

    note = (
        f"LLM 调用失败 (DeepSeek[key={bool(ds_key)}]: {last_ds_err or 'skipped'} / "
        f"OpenRouter[key={bool(or_key)}]: {last_or_err or 'skipped'})"
    )
    return {"success": False, "content": "", "note": note[:250], "source": "error"}


def _fallback_summary() -> dict:
    return {
        "success": False,
        "content": "",
        "note": "⚙️ AI 分析需配置 DEEPSEEK_API_KEY 或 OPENROUTER_API_KEY 环境变量。",
        "source": "fallback",
    }

