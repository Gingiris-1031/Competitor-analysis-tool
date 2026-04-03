"""流量峰值分析模块 — Google Trends 周级别数据检测品牌搜索热度峰值"""
import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional


# ---------------------------------------------------------------------------
# pytrends helpers（替代 Caravo Google Trends）
# ---------------------------------------------------------------------------

def _fetch_trends_sync(query: str, date_range: str = "today 12-m") -> Optional[list]:
    """
    用 pytrends 获取 Google Trends 数据，返回与原 Caravo 格式兼容的 timeline 列表：
    [{"timestamp": int, "date": str, "values": [{"query": str, "extracted_value": int}]}]
    """
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)
        pt.build_payload([query], cat=0, timeframe=date_range, geo="", gprop="")
        df = pt.interest_over_time()
        if df is None or df.empty:
            return None
        if "isPartial" in df.columns:
            df = df.drop(columns=["isPartial"])

        timeline = []
        for date, row in df.iterrows():
            val = int(row[query]) if query in row else 0
            timeline.append({
                "timestamp": int(date.timestamp()),
                "date":      date.strftime("%Y-%m-%d"),
                "values":    [{"query": query, "extracted_value": val}],
            })
        return timeline if timeline else None
    except Exception:
        return None


async def _fetch_trends(query: str, date_range: str = "today 12-m") -> Optional[list]:
    """异步包装：在线程池中运行，不阻塞事件循环，最长等待 35 秒。"""
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_trends_sync, query, date_range),
            timeout=35,
        )
    except Exception:
        return None


def _parse_timeline(timeline: list, query: str) -> list:
    """
    将 timeline_data 转换为统一结构：
    [{"date_label": str, "timestamp": int, "value": int}, ...]
    """
    parsed = []
    for point in timeline:
        ts_raw = point.get("timestamp")
        ts = int(ts_raw) if ts_raw else None
        values = point.get("values", [])
        val = None
        for v in values:
            if v.get("query", "").lower() == query.lower():
                val = int(v.get("extracted_value", 0))
                break
        if val is None and values:
            val = int(values[0].get("extracted_value", 0))
        if ts is not None and val is not None:
            parsed.append({
                "date_label": point.get("date", ""),
                "timestamp": ts,
                "value": val,
            })
    return sorted(parsed, key=lambda x: x["timestamp"])


# ---------------------------------------------------------------------------
# Peak detection
# ---------------------------------------------------------------------------

def _moving_average(values: list[int], window: int = 4) -> list[float]:
    """4周移动平均，前缀不足时用已有数据的均值。"""
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        result.append(sum(values[start : i + 1]) / (i - start + 1))
    return result


def _detect_peaks(data: list) -> list:
    """
    算法：
    1. 移动平均 > 0 时，超过 MA 50% 的周为"峰值周"
    2. 周环比增长 > 30% 的为"急涨周"
    3. 合并相邻（±1 周）峰值周为同一"峰值事件"
    返回峰值事件列表。
    """
    if not data:
        return []

    values = [d["value"] for d in data]
    ma = _moving_average(values)

    # Also detect: global/local maxima that are significant
    max_value = max(values) if values else 0
    # Find the 75th percentile as a baseline for "high" values
    sorted_vals = sorted(values)
    p75 = sorted_vals[int(len(sorted_vals) * 0.75)] if sorted_vals else 0

    peak_weeks = []  # indices
    for i, (v, m) in enumerate(zip(values, ma)):
        is_above_ma = m > 0 and v > m * 1.5
        is_surge = i > 0 and values[i - 1] > 0 and (v - values[i - 1]) / values[i - 1] > 0.30
        # Also mark if it's the global max or a local max significantly above p75
        is_global_max = v == max_value and v > p75 * 1.2
        is_local_max = (v > p75 * 1.3 and
                        (i == 0 or v >= values[i - 1]) and
                        (i == len(values) - 1 or v >= values[min(i + 1, len(values) - 1)]))
        if is_above_ma or is_surge or is_global_max or is_local_max:
            peak_weeks.append(i)

    # Merge adjacent peaks into events
    if not peak_weeks:
        return []

    events = []
    group = [peak_weeks[0]]
    for idx in peak_weeks[1:]:
        if idx - group[-1] <= 1:
            group.append(idx)
        else:
            events.append(group)
            group = [idx]
    events.append(group)

    peak_events = []
    for group in events:
        peak_vals = [values[i] for i in group]
        peak_idx = group[int((len(group) - 1) / 2)]  # median week index
        peak_ts = data[group[peak_vals.index(max(peak_vals))]]["timestamp"]
        peak_events.append({
            "peak_week_index": group[peak_vals.index(max(peak_vals))],
            "peak_timestamp": peak_ts,
            "peak_date_label": data[group[peak_vals.index(max(peak_vals))]]["date_label"],
            "peak_value": max(peak_vals),
            "peak_ma": round(ma[group[peak_vals.index(max(peak_vals))]], 1),
            "weeks_in_event": len(group),
            "week_indices": group,
        })
    return peak_events


# ---------------------------------------------------------------------------
# Growth phase classification
# ---------------------------------------------------------------------------

def _classify_growth_phases(data: list) -> list:
    """
    根据趋势数据划分增长阶段。使用 3 周滑动窗口平滑判断，避免周级别噪声导致阶段碎片化。
    短于 3 周的阶段自动合并到相邻阶段。
    """
    if not data:
        return []

    values = [d["value"] for d in data]

    # Use 3-week smoothed values for phase classification to avoid noise
    smoothed = []
    for i in range(len(values)):
        window = values[max(0, i - 1):i + 2]
        smoothed.append(sum(window) / len(window))

    def _get_phase(value: float, trend: str) -> str:
        if value < 10:
            return "冷启动期"
        elif value < 30:
            return "爬坡期" if trend != "down" else "回落期"
        elif trend == "up":
            return "爆发期"
        elif trend == "down":
            return "回落期"
        else:
            return "高位运行期"

    # Classify each week using smoothed values and 3-week trend
    raw_phases = []
    for i in range(len(data)):
        if i < 3:
            trend = "up" if i > 0 and smoothed[i] > smoothed[0] * 1.05 else "flat"
        else:
            recent_avg = sum(smoothed[i - 2:i + 1]) / 3
            earlier_avg = sum(smoothed[max(0, i - 5):i - 2]) / max(len(smoothed[max(0, i - 5):i - 2]), 1)
            if earlier_avg > 0:
                change = (recent_avg - earlier_avg) / earlier_avg
                if change > 0.15:
                    trend = "up"
                elif change < -0.15:
                    trend = "down"
                else:
                    trend = "flat"
            else:
                trend = "flat"
        raw_phases.append(_get_phase(smoothed[i], trend))

    # Group consecutive same-phase weeks
    groups = []
    current_phase = raw_phases[0]
    phase_start = 0
    for i in range(1, len(raw_phases)):
        if raw_phases[i] != current_phase:
            groups.append((current_phase, phase_start, i - 1))
            current_phase = raw_phases[i]
            phase_start = i
    groups.append((current_phase, phase_start, len(raw_phases) - 1))

    # Merge short phases (<3 weeks) into neighbors
    merged = []
    for phase, start, end in groups:
        week_count = end - start + 1
        if week_count < 3 and merged:
            # Merge into previous phase
            prev = merged[-1]
            merged[-1] = (prev[0], prev[1], end)
        else:
            merged.append((phase, start, end))

    # Build final phase objects
    phases = []
    for phase, start, end in merged:
        week_count = end - start + 1
        phase_values = values[start:end + 1]
        phases.append({
            "phase": phase,
            "start_date": data[start]["date_label"],
            "end_date": data[end]["date_label"],
            "start_timestamp": data[start]["timestamp"],
            "end_timestamp": data[end]["timestamp"],
            "week_count": week_count,
            "avg_value": round(sum(phase_values) / week_count, 1),
            "peak_value": max(phase_values),
            "min_value": min(phase_values),
        })

    return phases


# ---------------------------------------------------------------------------
# Phase insight enrichment
# ---------------------------------------------------------------------------

def _enrich_phases_with_insights(phases: list, peaks: list, producthunt: dict, social: dict):
    """为每个增长阶段注入渠道/内容关键洞察"""
    for phase in phases:
        p_start = phase.get("start_timestamp", 0)
        p_end = phase.get("end_timestamp", 0)
        insights = []
        channels = []

        # 1. Find attributed peaks within this phase
        phase_peaks = [
            pk for pk in peaks
            if pk.get("peak_timestamp", 0) >= p_start - 7 * 86400
            and pk.get("peak_timestamp", 0) <= p_end + 7 * 86400
        ]
        for pk in phase_peaks:
            attr = pk.get("attribution", {})
            if attr.get("attributed"):
                ch = attr.get("primary_channel", "")
                evt = attr.get("primary_event", "")
                if ch:
                    channels.append(ch)
                if evt:
                    insights.append(f"🔥 {ch} 热议：{evt[:60]}")
                # Secondary sources
                for src in attr.get("all_sources", [])[1:]:
                    if src.get("impact_score", 0) > 10:
                        channels.append(src["channel"])

        # 2. Find PH launches within this phase
        ph_launches_in_phase = []
        if producthunt.get("found"):
            main_date = producthunt.get("launch_date", "")
            main_ts = _date_to_ts(main_date)
            if main_ts and p_start <= main_ts <= p_end:
                ph_launches_in_phase.append(producthunt.get("name", ""))
                channels.append("Product Hunt")
            for other in producthunt.get("other_launches", []):
                o_ts = _date_to_ts(other.get("launch_date", ""))
                if o_ts and p_start <= o_ts <= p_end:
                    name = other.get("name", "")
                    votes = other.get("votes", 0)
                    ph_launches_in_phase.append(name)
                    channels.append("Product Hunt")
                    insights.append(f"🚀 PH Launch: {name} ({votes} votes)")

        # 3. Check social signals in this phase
        tw = social.get("channels", {}).get("twitter", {})
        for tweet in tw.get("top_tweets", []):
            t_ts = _tweet_date_to_ts(tweet.get("created_at", ""))
            if t_ts and p_start <= t_ts <= p_end:
                likes = tweet.get("likes", 0)
                if likes > 50:
                    text_preview = (tweet.get("text", "") or "")[:50]
                    insights.append(f"🐦 Twitter 爆帖 ({likes} likes): {text_preview}")
                    channels.append("Twitter/X")

        rd = social.get("channels", {}).get("reddit", {})
        for post in rd.get("top_posts", []):
            # Reddit posts usually have created_utc
            r_date = post.get("created_at", post.get("date", ""))
            r_ts = _date_to_ts(r_date) if r_date else 0
            if r_ts and p_start <= r_ts <= p_end:
                upvotes = post.get("upvotes", 0)
                if upvotes > 20:
                    insights.append(f"📢 Reddit: {post.get('title', '')[:50]} ({upvotes} upvotes)")
                    channels.append("Reddit")

        # 4. Phase-specific generic insight based on phase type
        phase_name = phase.get("phase", "")
        if not insights:
            if phase_name == "冷启动期":
                insights.append("📊 品牌搜索热度极低，市场认知尚未建立")
            elif phase_name == "爬坡期":
                insights.append("📈 品牌热度开始上升，可能有早期用户口碑或内容营销见效")
            elif phase_name == "爆发期":
                insights.append("💥 品牌热度急剧上升，通常伴随重大事件（launch/融资/媒体报道）")
            elif phase_name == "高位运行期":
                insights.append("🏔️ 品牌热度维持高位，产品已进入主流认知")
            elif phase_name == "回落期":
                insights.append("📉 品牌热度下降，可能需要新的增长引擎")

        # Deduplicate channels
        unique_channels = list(dict.fromkeys(channels))

        phase["insights"] = insights[:5]  # Max 5 insights per phase
        phase["active_channels"] = unique_channels
        phase["peak_count"] = len(phase_peaks)


def _date_to_ts(date_str: str) -> int:
    """Convert YYYY-MM-DD to unix timestamp, return 0 on failure"""
    if not date_str:
        return 0
    try:
        from datetime import datetime
        dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return 0


def _tweet_date_to_ts(date_str: str) -> int:
    """Convert Twitter date format to unix timestamp"""
    if not date_str:
        return 0
    try:
        from datetime import datetime
        # Twitter format: "Wed Oct 10 20:19:24 +0000 2018"
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return _date_to_ts(date_str)


# ---------------------------------------------------------------------------
# Launch correlation
# ---------------------------------------------------------------------------

def _extract_ph_launches(producthunt: dict) -> list:
    """从 producthunt 结果提取 launch 记录，统一为 {timestamp, label, source}"""
    launches = []
    if not producthunt:
        return launches

    # products list
    products = producthunt.get("products", [])
    for p in products:
        featured_at = p.get("featured_at") or p.get("createdAt") or p.get("created_at")
        if not featured_at:
            continue
        try:
            dt = datetime.fromisoformat(featured_at.replace("Z", "+00:00"))
            launches.append({
                "timestamp": int(dt.timestamp()),
                "label": p.get("name", "Unknown"),
                "source": "producthunt",
                "votes": p.get("votes_count", p.get("votesCount", 0)),
                "url": p.get("url", ""),
            })
        except Exception:
            continue

    # Also handle flat structure
    if not launches:
        for key in ("featured_at", "created_at", "launch_date"):
            val = producthunt.get(key)
            if val:
                try:
                    dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
                    launches.append({
                        "timestamp": int(dt.timestamp()),
                        "label": producthunt.get("name", "PH Launch"),
                        "source": "producthunt",
                        "votes": producthunt.get("votes_count", 0),
                        "url": producthunt.get("url", ""),
                    })
                    break
                except Exception:
                    continue

    return launches


def _extract_social_launches(social: dict) -> list:
    """从 social 结果提取 launch 相关帖子，统一为 {timestamp, label, source}"""
    launches = []
    if not social:
        return launches

    LAUNCH_KEYWORDS = re.compile(
        r"\b(launch(ed|ing)?|ship(ped|ping)?|release[d]?|introducing|announce[d]?|going live|产品发布|上线)\b",
        re.IGNORECASE,
    )

    # Twitter / X posts
    posts = social.get("twitter_posts", social.get("posts", []))
    for post in posts:
        text = post.get("text", post.get("content", ""))
        if LAUNCH_KEYWORDS.search(text):
            ts_raw = post.get("created_at", post.get("timestamp", ""))
            if not ts_raw:
                continue
            try:
                if isinstance(ts_raw, (int, float)):
                    ts = int(ts_raw)
                else:
                    dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    ts = int(dt.timestamp())
                launches.append({
                    "timestamp": ts,
                    "label": text[:80],
                    "source": "twitter",
                    "url": post.get("url", ""),
                })
            except Exception:
                continue

    return launches


WEEK_SECONDS = 7 * 24 * 3600
MATCH_WINDOW = 2 * WEEK_SECONDS  # ±2 weeks


def _correlate(peak_events: list, known_launches: list) -> tuple[list, list]:
    """
    对每个峰值事件，检查 ±2 周内是否有已知 launch。
    返回 (correlated_peaks, unmatched_peaks)
    """
    correlated = []
    unmatched = []

    for peak in peak_events:
        pt = peak["peak_timestamp"]
        matches = []
        for launch in known_launches:
            lt = launch["timestamp"]
            if abs(pt - lt) <= MATCH_WINDOW:
                delta_days = round((pt - lt) / 86400)
                matches.append({**launch, "delta_days": delta_days})

        entry = {**peak, "matched_launches": matches}
        if matches:
            entry["status"] = "matched"
            correlated.append(entry)
        else:
            entry["status"] = "unmatched"
            entry["hypothesis"] = (
                "疑似 launch 事件——可能来自 HN 首页/媒体报道/付费投放/病毒传播"
            )
            unmatched.append(entry)

    return correlated, unmatched


# ---------------------------------------------------------------------------
# Attribution — HN search
# ---------------------------------------------------------------------------

def _search_hn_sync(brand: str, start_ts: int, end_ts: int, domain: str = "", first_seen_ts: int = 0) -> list:
    """同步版本 — 在 run_in_executor 线程中运行。

    Filters:
    - Clamp start_ts to first_seen_ts (product launch date) to exclude pre-product noise
    - Search by both brand name and domain for better recall
    - Relevance check: title or story URL must mention brand/domain
    """
    # Clamp search window: never look before product existed
    if first_seen_ts and start_ts < first_seen_ts:
        start_ts = first_seen_ts

    # If the clamped window is invalid, skip
    if start_ts >= end_ts:
        return []

    # Search with brand name + domain for better recall
    all_hits = {}
    for query in [brand, domain] if domain and domain != brand else [brand]:
        url = (
            f"https://hn.algolia.com/api/v1/search"
            f"?query={query}"
            f"&tags=story"
            f"&numericFilters=created_at_i%3E{start_ts}%2Ccreated_at_i%3C{end_ts}"
            f"&hitsPerPage=10"
        )
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", "8", url],
                capture_output=True, text=True, timeout=12,
            )
            data = json.loads(result.stdout)
            for h in data.get("hits", []):
                oid = h.get("objectID", "")
                if oid and oid not in all_hits and h.get("points", 0) >= 2:
                    title = h.get("title", "")
                    story_url = h.get("url", "") or ""
                    # Relevance check: title or story URL should relate to the product
                    text_combined = (title + " " + story_url).lower()
                    brand_lower = brand.lower()
                    domain_lower = domain.lower().replace("www.", "")
                    is_relevant = (
                        brand_lower in text_combined
                        or domain_lower in text_combined
                    )
                    if not is_relevant:
                        continue
                    all_hits[oid] = {
                        "title": title,
                        "points": h.get("points", 0),
                        "comments": h.get("num_comments", 0),
                        "date": h.get("created_at", "")[:10],
                        "url": f"https://news.ycombinator.com/item?id={oid}",
                    }
        except Exception:
            continue

    hits = list(all_hits.values())
    return sorted(hits, key=lambda x: x["points"], reverse=True)[:5]


async def _search_hn(brand: str, start_ts: int, end_ts: int, domain: str = "", first_seen_ts: int = 0) -> list:
    """异步包装：在线程池中运行，不阻塞事件循环。"""
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                None, _search_hn_sync, brand, start_ts, end_ts, domain, first_seen_ts
            ),
            timeout=15,
        )
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Attribution — PH / Twitter / Reddit matching from existing data
# ---------------------------------------------------------------------------

def _match_ph_launches(producthunt: dict, window_start: int, window_end: int) -> list:
    """从 producthunt 数据中匹配时间窗口内的 launch。"""
    if not producthunt:
        return []
    launches = _extract_ph_launches(producthunt)
    results = []
    for launch in launches:
        if window_start <= launch["timestamp"] <= window_end:
            results.append({
                "title": launch["label"],
                "votes": launch.get("votes", 0),
                "date": datetime.fromtimestamp(launch["timestamp"]).strftime("%Y-%m-%d"),
                "url": launch.get("url", ""),
            })
    return sorted(results, key=lambda x: x["votes"], reverse=True)


def _match_twitter_posts(social: dict, window_start: int, window_end: int) -> list:
    """从 social.channels.twitter.top_tweets 中匹配时间窗口内的推文。"""
    if not social:
        return []
    twitter = social.get("channels", {}).get("twitter", {})
    top_tweets = twitter.get("top_tweets", [])
    results = []
    for tw in top_tweets:
        ts_raw = tw.get("created_at", "")
        if not ts_raw:
            continue
        try:
            if isinstance(ts_raw, (int, float)):
                ts = int(ts_raw)
            else:
                # Handle Twitter date format: "Tue Mar 01 12:00:00 +0000 2025"
                try:
                    dt = datetime.strptime(str(ts_raw), "%a %b %d %H:%M:%S %z %Y")
                except ValueError:
                    dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                ts = int(dt.timestamp())
            if window_start <= ts <= window_end:
                results.append({
                    "title": tw.get("text", "")[:120],
                    "likes": tw.get("likes", 0) or 0,
                    "retweets": tw.get("retweets", 0) or 0,
                    "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                    "url": "",
                })
        except Exception:
            continue
    return sorted(results, key=lambda x: x["likes"] + x["retweets"] * 3, reverse=True)[:5]


def _match_reddit_posts(social: dict, window_start: int, window_end: int) -> list:
    """从 social.channels.reddit.top_posts 中匹配时间窗口内的帖子。"""
    if not social:
        return []
    reddit = social.get("channels", {}).get("reddit", {})
    top_posts = reddit.get("top_posts", [])
    results = []
    for post in top_posts:
        ts_raw = post.get("date", 0)  # Reddit returns created_utc as float
        if not ts_raw:
            continue
        try:
            ts = int(float(ts_raw))
            if window_start <= ts <= window_end:
                results.append({
                    "title": post.get("title", "")[:120],
                    "upvotes": post.get("upvotes", 0) or 0,
                    "comments": post.get("comments", 0) or 0,
                    "subreddit": post.get("subreddit", ""),
                    "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                    "url": post.get("url", ""),
                })
        except Exception:
            continue
    return sorted(results, key=lambda x: x["upvotes"], reverse=True)[:5]


# ---------------------------------------------------------------------------
# Attribution — summary text generator
# ---------------------------------------------------------------------------

def _generate_attribution_summary(sources: list, peak: dict) -> str:
    """根据归因来源生成自然语言摘要。"""
    if not sources:
        return "未找到明确的流量来源。"

    primary = sources[0]
    channel = primary["channel"]
    top_event = primary["events"][0] if primary["events"] else {}
    title = top_event.get("title", "")

    date_label = peak.get("peak_date_label", "")
    val = peak.get("peak_value", 0)

    # Build primary attribution sentence
    if channel == "Hacker News":
        points = top_event.get("points", 0)
        event_type = top_event.get("event_type", "品牌提及")
        # Find the actual direct driver if top event is derivative
        direct_events = [e for e in primary.get("events", []) if e.get("event_type_en") == "direct"]
        derivative_events = [e for e in primary.get("events", []) if e.get("event_type_en") == "derivative"]
        if direct_events:
            de = direct_events[0]
            summary = f"主要由行业事件驱动（{de.get('title', '')[:50]}，{de.get('points', 0)} points）"
            if derivative_events:
                summary += f"，引发 {len(derivative_events)} 个衍生讨论（替代品/clone）"
        elif derivative_events and len(derivative_events) > 1:
            summary = f"品牌热度溢出期——{len(derivative_events)} 个'替代品/clone'讨论集中出现"
            best = derivative_events[0]
            summary += f"，最热：「{best.get('title', '')[:50]}」({best.get('points', 0)} pts)"
        else:
            summary = f"主要由 Hacker News 讨论驱动（最高 {points} points）"
            if title:
                summary += f"：「{title[:60]}」"
    elif channel == "Product Hunt":
        votes = top_event.get("votes", 0)
        summary = f"主要由 Product Hunt 发布驱动（{votes} votes）"
        if title:
            summary += f"：「{title[:60]}」"
    elif channel == "Twitter/X":
        likes = top_event.get("likes", 0)
        summary = f"主要由 Twitter/X 病毒传播驱动（最高 {likes} likes）"
        if title:
            summary += f"：「{title[:60]}」"
    elif channel == "Reddit":
        upvotes = top_event.get("upvotes", 0)
        subreddit = top_event.get("subreddit", "")
        summary = f"主要由 Reddit 讨论驱动（{upvotes} upvotes，r/{subreddit}）"
        if title:
            summary += f"：「{title[:60]}」"
    else:
        summary = f"主要由 {channel} 驱动"

    # Add secondary channels
    if len(sources) > 1:
        secondary = [s["channel"] for s in sources[1:]]
        summary += f"，次要渠道：{' / '.join(secondary)}"

    return summary


# ---------------------------------------------------------------------------
# Attribution — main orchestrator
# ---------------------------------------------------------------------------

async def _attribute_peak(
    peak: dict,
    brand: str,
    domain: str,
    producthunt: dict,
    social: dict,
    first_seen_ts: int = 0,
) -> dict:
    """对单个峰值进行归因分析。"""
    window_start = peak["peak_timestamp"] - 14 * 86400  # -2 weeks
    window_end = peak["peak_timestamp"] + 14 * 86400    # +2 weeks

    sources = []

    # 1. HN Search (live API call, ±3 weeks to catch upstream causes)
    hn_window_start = peak["peak_timestamp"] - 21 * 86400
    hn_window_end = peak["peak_timestamp"] + 14 * 86400
    hn_results = await _search_hn(brand, hn_window_start, hn_window_end, domain=domain, first_seen_ts=first_seen_ts)
    if hn_results:
        # Classify: direct driver vs derivative discussion
        for h in hn_results:
            title_lower = h.get("title", "").lower()
            is_derivative = any(kw in title_lower for kw in [
                "alternative", "clone", "open source", "open-source", "opensource",
                "better than", "vs ", " vs.", "competitor", "replacement",
                "like lovable", "like bolt", "similar to",
            ])
            is_direct = any(kw in title_lower for kw in [
                "raises", "funding", "valuation", "launch", "announce",
                "ipo", "acqui", "partner", "series ",
            ])
            if is_derivative and not is_direct:
                h["event_type"] = "衍生讨论"
                h["event_type_en"] = "derivative"
            elif is_direct:
                h["event_type"] = "直接驱动"
                h["event_type_en"] = "direct"
            else:
                h["event_type"] = "品牌提及"
                h["event_type_en"] = "mention"

        # Sort: direct drivers first, then by points
        type_priority = {"direct": 0, "mention": 1, "derivative": 2}
        hn_results.sort(key=lambda x: (type_priority.get(x.get("event_type_en", "mention"), 1), -x.get("points", 0)))

        sources.append({
            "channel": "Hacker News",
            "events": hn_results,
            "impact_score": sum(h["points"] for h in hn_results),
        })

    # 2. PH launches from existing data
    ph_matches = _match_ph_launches(producthunt, window_start, window_end)
    if ph_matches:
        sources.append({
            "channel": "Product Hunt",
            "events": ph_matches,
            "impact_score": sum(m["votes"] for m in ph_matches),
        })

    # 3. Twitter peak posts from existing data
    tw_matches = _match_twitter_posts(social, window_start, window_end)
    if tw_matches:
        sources.append({
            "channel": "Twitter/X",
            "events": tw_matches,
            "impact_score": sum(
                t.get("likes", 0) + t.get("retweets", 0) * 3 for t in tw_matches
            ),
        })

    # 4. Reddit peak posts from existing data
    rd_matches = _match_reddit_posts(social, window_start, window_end)
    if rd_matches:
        sources.append({
            "channel": "Reddit",
            "events": rd_matches,
            "impact_score": sum(r.get("upvotes", 0) for r in rd_matches),
        })

    # Rank sources by impact score
    sources.sort(key=lambda s: s["impact_score"], reverse=True)

    if sources:
        primary = sources[0]
        top_event = primary["events"][0] if primary["events"] else {}
        return {
            "attributed": True,
            "primary_channel": primary["channel"],
            "primary_event": top_event.get("title", ""),
            "confidence": "high" if primary["impact_score"] > 50 else "medium",
            "all_sources": sources,
            "summary": _generate_attribution_summary(sources, peak),
        }
    else:
        return {
            "attributed": False,
            "primary_channel": "Unknown",
            "confidence": "low",
            "all_sources": [],
            "summary": (
                "未找到明确的流量来源。"
                "可能来自：付费广告投放、线下活动、口碑传播、或数据源未覆盖的渠道。"
            ),
        }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _build_summary(data: list, peaks: list, unmatched: list, phases: list) -> dict:
    if not data:
        return {}

    values = [d["value"] for d in data]
    max_val = max(values)
    max_idx = values.index(max_val)

    # Trend direction: compare last 4 weeks vs 4 weeks before
    trend = "insufficient_data"
    if len(values) >= 8:
        recent = sum(values[-4:]) / 4
        prior = sum(values[-8:-4]) / 4
        if prior > 0:
            pct = (recent - prior) / prior * 100
            if pct > 10:
                trend = "上升"
            elif pct < -10:
                trend = "下降"
            else:
                trend = "平稳"

    # Current phase
    current_phase = phases[-1]["phase"] if phases else "未知"

    # Count by new status values
    attributed_count = sum(1 for p in peaks if p.get("status") == "attributed")
    ph_matched_count = sum(1 for p in peaks if p.get("status") == "ph_matched")
    matched_count = attributed_count + ph_matched_count
    unmatched_count = len(unmatched)

    return {
        "total_weeks": len(data),
        "max_interest": max_val,
        "max_interest_date": data[max_idx]["date_label"],
        "avg_interest": round(sum(values) / len(values), 1),
        "recent_trend": trend,
        "current_phase": current_phase,
        "total_peaks_detected": len(peaks),
        "matched_peaks": matched_count,
        "unmatched_peaks": unmatched_count,
        "attributed_peaks": attributed_count,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def analyze_traffic_peaks(
    brand: str,
    domain: str,
    producthunt: dict = None,
    social: dict = None,
    first_seen: str = "",
) -> dict:
    """
    通过 Google Trends 检测品牌搜索热度峰值，交叉关联已知 launch 事件，
    并对每个峰值执行自动归因（HN + PH + Twitter + Reddit）。

    Returns:
        {
            "trends_data": [...],
            "detected_peaks": [...],
            "peak_launch_correlation": [...],
            "unmatched_peaks": [...],
            "growth_phases": [...],
            "summary": {...},
        }
    """
    empty = {
        "trends_data": [],
        "detected_peaks": [],
        "peak_launch_correlation": [],
        "unmatched_peaks": [],
        "growth_phases": [],
        "summary": {},
        "error": None,
    }

    # --- Step 1 & 2: fetch Trends (domain + brand) IN PARALLEL ---
    domain_query = domain.lstrip("www.").strip()
    brand_name = re.sub(r"\.[a-z]{2,}$", "", domain_query.lower())
    if brand_name == domain_query.lower():
        brand_name = brand.lower()

    timeline_domain, timeline_brand = await asyncio.gather(
        _fetch_trends(domain_query),
        _fetch_trends(brand_name),
        return_exceptions=True,
    )
    if isinstance(timeline_domain, Exception):
        timeline_domain = None
    if isinstance(timeline_brand, Exception):
        timeline_brand = None

    # Prefer whichever has more non-zero values; fall back gracefully
    def _nonzero_count(tl):
        if not tl:
            return 0
        return sum(1 for p in tl if p.get("values") and
                   int(p["values"][0].get("extracted_value", 0)) > 0)

    if _nonzero_count(timeline_brand) >= _nonzero_count(timeline_domain):
        primary_query = brand_name
        primary_timeline = timeline_brand
        secondary_query = domain_query
        secondary_timeline = timeline_domain
    else:
        primary_query = domain_query
        primary_timeline = timeline_domain
        secondary_query = brand_name
        secondary_timeline = timeline_brand

    if not primary_timeline and not secondary_timeline:
        empty["error"] = "Google Trends API 调用失败（两次查询均无数据）"
        return empty

    # Use primary; if primary empty, fall back to secondary
    active_timeline = primary_timeline or secondary_timeline
    active_query = primary_query if primary_timeline else secondary_query

    # --- Step 3: parse ---
    data = _parse_timeline(active_timeline, active_query)
    if not data:
        empty["error"] = "无法解析 Trends 时间序列数据"
        return empty

    # --- Step 4: detect peaks ---
    peaks = _detect_peaks(data)

    # --- Step 5: collect known launches (for legacy correlation) ---
    known_launches = _extract_ph_launches(producthunt) + _extract_social_launches(social)

    # --- Step 6: legacy correlate (PH / social launch posts) ---
    correlated, unmatched = _correlate(peaks, known_launches)
    all_peaks_annotated = correlated + unmatched

    # --- Step 7: attribution (HN + PH + Twitter + Reddit per peak) ---
    # Convert first_seen date (e.g. "2022-08-01") to unix timestamp for HN filtering
    first_seen_ts = 0
    if first_seen:
        try:
            first_seen_ts = int(datetime.strptime(first_seen[:10], "%Y-%m-%d").timestamp())
        except Exception:
            pass

    for peak in all_peaks_annotated:
        attribution = await _attribute_peak(
            peak, brand_name, domain_query, producthunt or {}, social or {},
            first_seen_ts=first_seen_ts,
        )
        peak["attribution"] = attribution

        # Update status based on attribution result
        if attribution["attributed"]:
            # Keep "ph_matched" if it was already matched via PH legacy path,
            # otherwise mark as "attributed"
            if peak.get("status") == "matched":
                # Check if match was PH-only
                is_ph_only = all(
                    m.get("source") == "producthunt"
                    for m in peak.get("matched_launches", [])
                )
                peak["status"] = "ph_matched" if is_ph_only else "attributed"
            else:
                peak["status"] = "attributed"
        elif peak.get("status") != "matched":
            peak["status"] = "unmatched"

    # Rebuild correlated / unmatched lists based on updated statuses
    correlated_final = [p for p in all_peaks_annotated if p["status"] in ("matched", "ph_matched", "attributed")]
    unmatched_final = [p for p in all_peaks_annotated if p["status"] == "unmatched"]

    # --- Step 8: growth phases ---
    phases = _classify_growth_phases(data)

    # --- Step 8b: enrich phases with channel/content insights ---
    _enrich_phases_with_insights(phases, all_peaks_annotated, producthunt or {}, social or {})

    # --- Step 9: summary ---
    summary = _build_summary(data, all_peaks_annotated, unmatched_final, phases)
    summary["primary_query"] = active_query
    summary["secondary_query"] = secondary_query

    return {
        "trends_data": data,
        "detected_peaks": all_peaks_annotated,
        "peak_launch_correlation": correlated_final,
        "unmatched_peaks": unmatched_final,
        "growth_phases": phases,
        "summary": summary,
        "error": None,
    }
