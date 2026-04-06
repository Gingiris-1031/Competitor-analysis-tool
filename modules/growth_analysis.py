"""增长深度分析模块 — 渠道拆解 + 0→1 故事线 + 多波 Launch 时间线"""
import re
from datetime import datetime

try:
    from .propagation import summarize_propagation_for_growth
except ImportError:
    try:
        from propagation import summarize_propagation_for_growth
    except ImportError:
        summarize_propagation_for_growth = None


def analyze_growth_deep(
    product_name: str,
    url: str,
    website: dict,
    social: dict,
    traffic: dict,
    producthunt: dict,
    propagation: dict = None,
    github_oss: dict = None,
) -> dict:
    """
    基于已采集数据，生成增长深度分析。
    """
    result = {
        "channel_breakdown": _analyze_channels(social, traffic, github_oss=github_oss),
        "zero_to_one_story": _build_zero_to_one(product_name, website, traffic, producthunt),
        "launch_waves": _detect_launch_waves(product_name, website, social, traffic, producthunt),
    }

    # 注入传播深度分析摘要（如果提供了 propagation 数据）
    if propagation and summarize_propagation_for_growth is not None:
        result["launch_propagation_summary"] = summarize_propagation_for_growth(propagation)
    elif propagation:
        # fallback: summarize_propagation_for_growth 导入失败，直接透传关键字段
        result["launch_propagation_summary"] = {
            "available": True,
            "data_mode": propagation.get("data_mode", "unknown"),
            "root_post": propagation.get("root_post", {}),
            "kol_count": propagation.get("influencer_analysis", {}).get("total_kols", 0),
            "four_stage_overview": {
                k: v.get("count", 0)
                for k, v in propagation.get("four_stage_timeline", {}).items()
            },
        }

    return result


# ============================================================
# 1. 关键增长渠道/内容拆解
# ============================================================

def _analyze_channels(social: dict, traffic: dict, github_oss: dict = None) -> dict:
    """分析各渠道的增长贡献和内容模式"""
    channels = social.get("channels", {})
    breakdown = {
        "active_channels": [],
        "channel_metrics": {},
        "content_patterns": [],
        "top_content": [],
    }

    # Twitter analysis
    tw = channels.get("twitter", {})
    if tw.get("detected"):
        tw_metrics = {
            "platform": "Twitter/X",
            "handle": tw.get("handle", ""),
            "followers": tw.get("followers", 0),
            "total_tweets": tw.get("profile", {}).get("statuses_count", 0),
        }
        # Analyze top tweets for content patterns
        top_tweets = tw.get("top_tweets", [])
        if top_tweets:
            tw_metrics["top_tweet_likes"] = max(t.get("likes", 0) for t in top_tweets)
            tw_metrics["avg_engagement"] = sum(t.get("likes", 0) + t.get("retweets", 0) for t in top_tweets) // max(len(top_tweets), 1)

            # Content classification
            categories = {"launch": 0, "product_update": 0, "community": 0, "tutorial": 0, "kol_collab": 0, "other": 0}
            for t in top_tweets:
                text = (t.get("text", "") or "").lower()
                if any(w in text for w in ["launch", "live", "introducing", "announcing", "shipped", "just launched"]):
                    categories["launch"] += 1
                elif any(w in text for w in ["update", "new feature", "v2", "v1", "release", "changelog"]):
                    categories["product_update"] += 1
                elif any(w in text for w in ["community", "discord", "join", "thank", "milestone", "star"]):
                    categories["community"] += 1
                elif any(w in text for w in ["how to", "tutorial", "guide", "tip", "learn"]):
                    categories["tutorial"] += 1
                elif any(w in text for w in ["collab", "partner", "feat", "thread by", "interview"]):
                    categories["kol_collab"] += 1
                else:
                    categories["other"] += 1
            tw_metrics["content_categories"] = {k: v for k, v in categories.items() if v > 0}

            # Top performing content
            for t in sorted(top_tweets, key=lambda x: x.get("likes", 0), reverse=True)[:3]:
                breakdown["top_content"].append({
                    "platform": "Twitter",
                    "text": (t.get("text", "") or "")[:120],
                    "likes": t.get("likes", 0),
                    "retweets": t.get("retweets", 0),
                    "type": _classify_tweet(t.get("text", "")),
                })

        breakdown["channel_metrics"]["twitter"] = tw_metrics
        breakdown["active_channels"].append("Twitter/X")

    # YouTube analysis
    yt = channels.get("youtube", {})
    if yt.get("detected"):
        breakdown["channel_metrics"]["youtube"] = {
            "platform": "YouTube",
            "handle": yt.get("handle", ""),
            "subscribers": yt.get("subscribers"),
            "video_count": yt.get("video_count"),
        }
        breakdown["active_channels"].append("YouTube")

    # Reddit analysis
    rd = channels.get("reddit", {})
    if rd.get("detected"):
        rd_metrics = {
            "platform": "Reddit",
            "total_mentions": rd.get("total_mentions", 0),
            "has_subreddit": rd.get("has_subreddit", False),
            "subreddit_members": rd.get("subreddit_members"),
            "top_subreddits": [s["name"] for s in rd.get("mentioned_subreddits", [])[:5]],
        }
        # Top Reddit posts
        for p in rd.get("top_posts", [])[:3]:
            breakdown["top_content"].append({
                "platform": "Reddit",
                "text": p.get("title", "")[:120],
                "likes": p.get("upvotes", 0),
                "comments": p.get("comments", 0),
                "subreddit": p.get("subreddit", ""),
            })
        breakdown["channel_metrics"]["reddit"] = rd_metrics
        breakdown["active_channels"].append("Reddit")

    # GitHub analysis — prefer github_oss module data (has stars, contributors)
    gh_social = channels.get("github", {})
    gh_oss = github_oss or {}
    if gh_oss.get("found") or gh_social.get("detected"):
        breakdown["channel_metrics"]["github"] = {
            "platform": "GitHub",
            "stars_total": gh_oss.get("stars", 0) or gh_social.get("stars_total", 0),
            "followers": gh_oss.get("subscribers", 0) or gh_social.get("followers", 0),
            "public_repos": gh_social.get("public_repos", 0),
            "top_repo_stars": gh_oss.get("stars", 0) or 0,
            "contributors": gh_oss.get("contributors_count", 0),
            "repo": gh_oss.get("repo", ""),
            "owner": gh_oss.get("owner", ""),
        }
        breakdown["active_channels"].append("GitHub")

    # SEO channel from traffic data
    rank = traffic.get("domain_rank", {})
    if rank.get("organic_traffic"):
        breakdown["channel_metrics"]["seo"] = {
            "platform": "SEO/Organic Search",
            "monthly_traffic": rank.get("organic_traffic", 0),
            "total_keywords": rank.get("total_keywords", 0),
            "equivalent_ad_cost": rank.get("estimated_paid_cost", 0),
        }
        breakdown["active_channels"].append("SEO/Organic")

    # Identify dominant channel
    if breakdown["channel_metrics"]:
        # Score channels roughly
        scores = {}
        for ch, m in breakdown["channel_metrics"].items():
            if ch == "twitter":
                scores[ch] = (m.get("followers", 0) or 0) * 2 + (m.get("top_tweet_likes", 0) or 0) * 10
            elif ch == "github":
                scores[ch] = (m.get("stars_total", 0) or 0) * 5
            elif ch == "seo":
                scores[ch] = (m.get("monthly_traffic", 0) or 0)
            elif ch == "reddit":
                scores[ch] = (m.get("total_mentions", 0) or 0) * 50 + (m.get("subreddit_members", 0) or 0)
            elif ch == "youtube":
                subs = m.get("subscribers") or "0"
                if isinstance(subs, str):
                    subs = subs.replace("K", "000").replace("M", "000000").replace(",", "")
                    try: subs = int(float(subs))
                    except: subs = 0
                elif not isinstance(subs, (int, float)):
                    subs = 0
                scores[ch] = (subs or 0) * 3
        if scores:
            dominant = max(scores, key=scores.get)
            breakdown["dominant_channel"] = dominant

    return breakdown


def _classify_tweet(text: str) -> str:
    text = (text or "").lower()
    if any(w in text for w in ["launch", "live", "introducing", "shipped"]):
        return "launch"
    elif any(w in text for w in ["update", "feature", "release", "changelog"]):
        return "product_update"
    elif any(w in text for w in ["community", "discord", "thank", "milestone"]):
        return "community"
    elif any(w in text for w in ["how to", "tutorial", "guide"]):
        return "tutorial"
    return "other"


# ============================================================
# 2. 流量 0→1 故事线还原
# ============================================================

def _build_zero_to_one(product_name: str, website: dict, traffic: dict, producthunt: dict) -> dict:
    """还原从 0 到 1 的增长故事线"""
    story = {
        "timeline": [],
        "first_seen": website.get("first_seen", "N/A"),
        "current_traffic": 0,
        "growth_multiple": None,
        "key_inflection_points": [],
    }

    # Collect timeline events
    events = []

    # 1) Domain first seen (Wayback)
    first_seen = website.get("first_seen", "")
    if first_seen and first_seen != "N/A":
        events.append({
            "date": first_seen,
            "type": "milestone",
            "event": f"{product_name} 域名首次出现在 Wayback Machine",
            "source": "Wayback Machine",
        })

    # 2) Wayback key changes
    for change in website.get("key_changes", []):
        events.append({
            "date": change.get("to_date", ""),
            "type": "website_change",
            "event": "; ".join(change.get("changes", [])[:3]),
            "source": "Wayback Machine",
        })

    # 3) Product Hunt launch
    if producthunt and producthunt.get("found"):
        events.append({
            "date": producthunt.get("launch_date", ""),
            "type": "launch",
            "event": f"Product Hunt Launch — ⬆{producthunt.get('votes', 0)} votes, 💬{producthunt.get('comments', 0)} comments",
            "source": "Product Hunt",
            "metrics": {"votes": producthunt.get("votes", 0), "comments": producthunt.get("comments", 0)},
        })
        # Other launches
        for other in producthunt.get("other_launches", []):
            events.append({
                "date": other.get("launch_date", ""),
                "type": "launch",
                "event": f"Product Hunt 再次 Launch「{other.get('name', '')}」— ⬆{other.get('votes', 0)} votes",
                "source": "Product Hunt",
            })

    # 4) Traffic inflection points
    history = traffic.get("historical", {}).get("history", [])
    if len(history) >= 2:
        story["current_traffic"] = history[-1].get("organic_traffic", 0)
        first_traffic = next((h.get("organic_traffic", 0) for h in history if h.get("organic_traffic", 0) > 0), 0)
        if first_traffic > 0 and story["current_traffic"] > 0:
            story["growth_multiple"] = round(story["current_traffic"] / first_traffic, 1)

        # Detect significant growth spikes (>50% MoM)
        for i in range(1, len(history)):
            prev = history[i - 1].get("organic_traffic", 0)
            curr = history[i].get("organic_traffic", 0)
            if prev > 0 and curr > 0:
                growth_pct = (curr - prev) / prev * 100
                if growth_pct > 50:
                    events.append({
                        "date": history[i].get("date", ""),
                        "type": "traffic_spike",
                        "event": f"有机流量激增 +{growth_pct:.0f}%（{prev:,} → {curr:,}/月）",
                        "source": "DataForSEO",
                        "metrics": {"from": prev, "to": curr, "growth_pct": round(growth_pct)},
                    })
                    story["key_inflection_points"].append({
                        "date": history[i].get("date", ""),
                        "traffic_before": prev,
                        "traffic_after": curr,
                        "growth_pct": round(growth_pct),
                    })

    # 5) Keyword milestones
    kw_history = [(h.get("date", ""), h.get("keywords", 0)) for h in history if h.get("keywords", 0) > 0]
    if len(kw_history) >= 2:
        first_kw = kw_history[0][1]
        for date, kw_count in kw_history:
            if kw_count >= first_kw * 2 and first_kw > 100:
                events.append({
                    "date": date,
                    "type": "seo_milestone",
                    "event": f"排名关键词突破 {kw_count:,}（从 {first_kw:,} 翻倍）",
                    "source": "DataForSEO",
                })
                break

    # Sort events chronologically
    events.sort(key=lambda e: e.get("date", ""))
    story["timeline"] = events

    return story


# ============================================================
# 3. 多波 Launch 时间线
# ============================================================

def _detect_launch_waves(product_name: str, website: dict, social: dict, traffic: dict, producthunt: dict) -> dict:
    """检测并分析多波 Launch"""
    waves = {
        "total_waves": 0,
        "launches": [],
        "launch_cadence": None,
    }

    # Collect all launch events
    launches = []

    # Product Hunt launches (primary + others)
    if producthunt and producthunt.get("found"):
        launches.append({
            "date": producthunt.get("launch_date", ""),
            "channel": "Product Hunt",
            "name": producthunt.get("name", product_name),
            "tagline": producthunt.get("tagline", ""),
            "metrics": {
                "votes": producthunt.get("votes", 0),
                "comments": producthunt.get("comments", 0),
                "rating": producthunt.get("reviews_rating", 0),
            },
        })
        for other in producthunt.get("other_launches", []):
            launches.append({
                "date": other.get("launch_date", ""),
                "channel": "Product Hunt",
                "name": other.get("name", ""),
                "tagline": "",
                "metrics": {"votes": other.get("votes", 0)},
            })

    # Twitter launch posts
    tw = social.get("channels", {}).get("twitter", {})
    for tweet in tw.get("top_tweets", []):
        text = (tweet.get("text", "") or "").lower()
        if any(w in text for w in ["launch", "just launched", "introducing", "shipped", "live on", "announcing"]):
            launches.append({
                "date": _parse_twitter_date(tweet.get("created_at", "")),
                "channel": "Twitter",
                "name": tweet.get("text", "")[:80],
                "tagline": "",
                "metrics": {
                    "likes": tweet.get("likes", 0),
                    "retweets": tweet.get("retweets", 0),
                    "views": tweet.get("views", 0),
                },
            })

    # Traffic spikes as potential launch indicators
    history = traffic.get("historical", {}).get("history", [])
    for i in range(1, len(history)):
        prev = history[i - 1].get("organic_traffic", 0)
        curr = history[i].get("organic_traffic", 0)
        if prev > 0 and curr > 0:
            growth_pct = (curr - prev) / prev * 100
            if growth_pct > 80:  # Major spike = likely a launch event
                launches.append({
                    "date": history[i].get("date", ""),
                    "channel": "Organic Traffic Spike",
                    "name": f"流量激增 +{growth_pct:.0f}%",
                    "tagline": f"{prev:,} → {curr:,}/月",
                    "metrics": {"traffic_before": prev, "traffic_after": curr, "growth_pct": round(growth_pct)},
                })

    # Sort by date and deduplicate nearby events (within same month = same wave)
    launches.sort(key=lambda l: l.get("date", ""))

    # Group into waves (events within 45 days = same wave)
    wave_groups = []
    current_wave = []
    for launch in launches:
        if not current_wave:
            current_wave.append(launch)
        else:
            last_date = current_wave[-1].get("date", "")
            this_date = launch.get("date", "")
            if _days_between(last_date, this_date) <= 45:
                current_wave.append(launch)
            else:
                wave_groups.append(current_wave)
                current_wave = [launch]
    if current_wave:
        wave_groups.append(current_wave)

    # Format waves
    for i, group in enumerate(wave_groups):
        wave = {
            "wave_number": i + 1,
            "date_range": f"{group[0].get('date', '?')} ~ {group[-1].get('date', '?')}" if len(group) > 1 else group[0].get("date", "?"),
            "channels": list(set(l["channel"] for l in group)),
            "events": group,
            "total_impact": {},
        }
        # Aggregate impact
        total_votes = sum(l.get("metrics", {}).get("votes", 0) for l in group)
        total_likes = sum(l.get("metrics", {}).get("likes", 0) for l in group)
        if total_votes:
            wave["total_impact"]["ph_votes"] = total_votes
        if total_likes:
            wave["total_impact"]["twitter_likes"] = total_likes
        # Traffic impact
        traffic_events = [l for l in group if "traffic_after" in l.get("metrics", {})]
        if traffic_events:
            wave["total_impact"]["traffic_peak"] = max(l["metrics"]["traffic_after"] for l in traffic_events)

        waves["launches"].append(wave)

    waves["total_waves"] = len(wave_groups)

    # Launch cadence
    if len(wave_groups) >= 2:
        dates = [g[0].get("date", "") for g in wave_groups if g[0].get("date")]
        if len(dates) >= 2:
            days = _days_between(dates[0], dates[-1])
            if days > 0:
                avg_interval = days // (len(dates) - 1)
                if avg_interval < 60:
                    waves["launch_cadence"] = f"高频（约每 {avg_interval} 天一波）"
                elif avg_interval < 180:
                    waves["launch_cadence"] = f"中频（约每 {avg_interval // 30} 个月一波）"
                else:
                    waves["launch_cadence"] = f"低频（约每 {avg_interval // 30} 个月一波）"

    return waves


def _parse_twitter_date(date_str: str) -> str:
    """Parse Twitter date format to YYYY-MM-DD"""
    if not date_str:
        return ""
    # Twitter format: "Wed Oct 10 20:19:24 +0000 2018"
    try:
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        # Maybe already in YYYY-MM-DD format
        if re.match(r'\d{4}-\d{2}-\d{2}', str(date_str)):
            return str(date_str)[:10]
        return str(date_str)[:10] if date_str else ""


def _days_between(date1: str, date2: str) -> int:
    """Calculate days between two date strings"""
    try:
        d1 = datetime.strptime(str(date1)[:10], "%Y-%m-%d")
        d2 = datetime.strptime(str(date2)[:10], "%Y-%m-%d")
        return abs((d2 - d1).days)
    except (ValueError, TypeError):
        return 999  # Unknown = treat as far apart
