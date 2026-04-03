"""
传播深度分析模块 — Launch 帖四阶段传播模型

基于 Lovable 案例文档的分析框架：
  Stage 1: 内部点燃（团队/创始人集体发声）  0-2h
  Stage 2: 生态催化（合作伙伴/集成方背书）  2-12h
  Stage 3: KOL 引爆（科技大V/行业领袖转发）  12h-3d
  Stage 4: 广泛渗透（普通用户自发传播）     3d+

Caravo API 端点（twitter241 provider，$0.005/call）：
  - twitter241/retweets   → 原帖 retweet 列表（输入: pid, count）
  - twitter241/quotes     → 原帖 quote 列表（输入: pid, count）
  - twitter241/tweet-v2   → 单条推文详情（输入: pid）
  - twitter241/search-v3  → 关键词搜索（输入: query, type, count）
  - twitter241/user       → 用户画像（输入: username）

降级策略：
  - 如获取不到 retweet/quote 数据，基于现有 top_tweets 做近似分析
  - 每次 API 调用做 try/except，单点失败不影响整体流程
"""

import re
import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional


# ============================================================
# Caravo 工具函数
# ============================================================

def _call_caravo(tool_id: str, params: dict) -> dict:
    """调用 Caravo CLI，复用 social.py 的同款逻辑"""
    api_key = os.environ.get("CARAVO_API_KEY", "").strip()
    if not api_key:
        try:
            api_key = open(os.path.expanduser("~/.cola/secrets/caravo_api_key")).read().strip()
        except FileNotFoundError:
            pass
    if not api_key:
        return {"success": False, "error": "No Caravo API key"}
    env = os.environ.copy()
    env["CARAVO_API_KEY"] = api_key
    try:
        result = subprocess.run(
            ["npx", "-y", "@caravo/cli@latest", "exec", tool_id, "-d", json.dumps(params)],
            capture_output=True, text=True, timeout=30, env=env
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get("success"):
                return {"success": True, "data": data.get("output", {})}
        stderr = result.stderr[:200]
        if "balance" in stderr.lower() or "$0" in stderr:
            return {"success": False, "error": "Caravo 余额不足", "need_topup": True}
        return {"success": False, "error": stderr[:100]}
    except Exception as e:
        return {"success": False, "error": str(e)[:100]}


# ============================================================
# Tweet ID 提取
# ============================================================

def _extract_tweet_id(tweet: dict) -> Optional[str]:
    """从推文数据中提取 tweet ID，兼容多种嵌套结构"""
    # 常见字段路径
    for key in ["id_str", "id", "tweet_id", "rest_id"]:
        val = tweet.get(key)
        if val and str(val).isdigit():
            return str(val)
    # 深层嵌套：legacy.id_str
    legacy = tweet.get("legacy", {})
    if isinstance(legacy, dict):
        for key in ["id_str", "id"]:
            val = legacy.get(key)
            if val and str(val).isdigit():
                return str(val)
    return None


def _extract_tweet_timestamp(tweet: dict) -> Optional[datetime]:
    """从推文中提取发布时间，返回 UTC datetime"""
    created_at = (
        tweet.get("created_at")
        or tweet.get("legacy", {}).get("created_at")
        or ""
    )
    if not created_at:
        return None
    try:
        # Twitter 格式: "Wed Jan 01 00:00:00 +0000 2025"
        dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S +0000 %Y")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        # ISO 格式
        return datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception:
        return None


def _hours_since(ts: Optional[datetime], reference: Optional[datetime]) -> Optional[float]:
    """计算 ts 相对于 reference 的小时差"""
    if ts is None or reference is None:
        return None
    delta = ts - reference
    return delta.total_seconds() / 3600


# ============================================================
# KOL 画像分类
# ============================================================

# bio 关键词 → 用户类型映射（顺序决定优先级）
_KOL_TYPE_RULES = [
    ("founder_ceo",   ["founder", "co-founder", "ceo", "chief executive", "cofounder"]),
    ("developer",     ["developer", "engineer", "dev ", "coder", "programmer", "software", "frontend", "backend", "fullstack", "swe", "vp eng", "cto"]),
    ("vc_investor",   ["investor", "vc", " fund", "capital", "partner at", "general partner", "angel", "venture"]),
    ("kol_creator",   ["creator", "blogger", "youtuber", "podcaster", "newsletter", "influencer", "content"]),
    ("designer",      ["designer", "design", "ux", "ui ", "product design"]),
    ("product",       ["product manager", "product lead", "pm ", "head of product"]),
    ("journalist",    ["journalist", "reporter", "editor", "writer", "press", "media"]),
]

def _classify_user(bio: str, followers: int) -> str:
    """根据 bio 关键词和粉丝数判断用户类型"""
    if not bio:
        bio = ""
    bio_lower = bio.lower()
    for user_type, keywords in _KOL_TYPE_RULES:
        if any(kw in bio_lower for kw in keywords):
            # KOL/creator 需要额外粉丝门槛
            if user_type == "kol_creator" and followers < 5000:
                continue
            return user_type
    return "regular_user"


def _kol_tier(followers: int) -> str:
    """KOL 分级"""
    if followers >= 100_000:
        return "mega_kol"    # 100K+
    elif followers >= 10_000:
        return "big_kol"     # 10K-100K
    elif followers >= 1_000:
        return "mid_kol"     # 1K-10K
    else:
        return "small"       # <1K


# ============================================================
# Launch Post 识别
# ============================================================

LAUNCH_KEYWORDS = [
    "launch", "launching", "launched",
    "introducing", "introduce",
    "shipped", "ship",
    "announcing", "announce", "announcement",
    "just built", "just released", "just dropped",
    "live now", "now live",
    "excited to share", "thrilled to",
    "product hunt",
]

def _is_launch_tweet(text: str) -> bool:
    """判断是否为 launch 帖"""
    text_lower = (text or "").lower()
    return any(kw in text_lower for kw in LAUNCH_KEYWORDS)


def _find_launch_post(tweets: list) -> Optional[dict]:
    """
    从推文列表中识别最佳 launch post：
    1. 含 launch 关键词
    2. 按互动量（likes + retweets + views/100）排序取最高
    """
    launch_candidates = [t for t in tweets if _is_launch_tweet(t.get("text", "") or t.get("full_text", ""))]
    if not launch_candidates:
        # fallback: 互动量最高的帖子
        launch_candidates = tweets

    def _score(t: dict) -> float:
        likes = t.get("likes", 0) or 0
        rts = t.get("retweets", 0) or 0
        views = t.get("views", 0) or 0
        replies = t.get("replies", 0) or 0
        bookmarks = t.get("bookmarks", 0) or 0
        return likes + rts * 2 + views / 100 + replies * 1.5 + bookmarks

    return max(launch_candidates, key=_score, default=None)


# ============================================================
# 传播层级数据获取
# ============================================================

def _fetch_retweets(tweet_id: str, count: int = 100) -> list:
    """获取推文的 retweet 列表"""
    result = _call_caravo("twitter241/retweets", {"pid": tweet_id, "count": str(count)})
    if not result.get("success"):
        return []
    raw = result.get("data", {})
    # 尝试提取 retweets 列表
    if isinstance(raw, list):
        return raw
    # 常见嵌套路径
    for path in [
        ["retweets"],
        ["data", "retweets"],
        ["json", "retweets"],
        ["users"],
        ["data", "users"],
    ]:
        obj = raw
        for key in path:
            if isinstance(obj, dict):
                obj = obj.get(key, {})
        if isinstance(obj, list) and obj:
            return obj
    return []


def _fetch_quotes(tweet_id: str, count: int = 100) -> list:
    """获取推文的 quote 列表"""
    result = _call_caravo("twitter241/quotes", {"pid": tweet_id, "count": str(count)})
    if not result.get("success"):
        return []
    raw = result.get("data", {})
    if isinstance(raw, list):
        return raw
    for path in [
        ["quotes"],
        ["data", "tweets"],
        ["json", "data", "search_by_raw_query", "search_timeline", "timeline", "instructions"],
        ["tweets"],
        ["data"],
    ]:
        obj = raw
        for key in path:
            if isinstance(obj, dict):
                obj = obj.get(key, {})
        if isinstance(obj, list) and obj:
            return obj
    return []


def _fetch_tweet_detail(tweet_id: str) -> Optional[dict]:
    """获取推文详情"""
    result = _call_caravo("twitter241/tweet-v2", {"pid": tweet_id})
    if not result.get("success"):
        return None
    raw = result.get("data", {})
    # 深挖
    def _dig(obj, *keys):
        for k in keys:
            if isinstance(obj, dict):
                obj = obj.get(k, {})
            else:
                return {}
        return obj

    tweet = (
        _dig(raw, "data", "tweetResult", "result")
        or _dig(raw, "json", "data", "tweetResult", "result")
        or raw
    )
    legacy = tweet.get("legacy", tweet)
    return legacy if isinstance(legacy, dict) else raw


# ============================================================
# 用户画像提取
# ============================================================

def _extract_user_profile(user_obj: dict) -> dict:
    """从各种嵌套结构中提取用户画像"""
    # twitter241/retweets 的用户结构通常在 user.legacy 或直接在 user
    def _dig(obj, *keys):
        for k in keys:
            if isinstance(obj, dict):
                obj = obj.get(k, {})
            else:
                return {}
        return obj if isinstance(obj, dict) else {}

    legacy = (
        _dig(user_obj, "legacy")
        or _dig(user_obj, "user", "legacy")
        or _dig(user_obj, "author", "legacy")
        or user_obj
    )
    core = (
        _dig(user_obj, "core")
        or _dig(user_obj, "user", "core")
        or {}
    )

    screen_name = (
        core.get("screen_name")
        or legacy.get("screen_name")
        or user_obj.get("screen_name")
        or user_obj.get("username")
        or ""
    )
    followers = (
        legacy.get("followers_count")
        or legacy.get("normal_followers_count")
        or user_obj.get("followers_count")
        or 0
    )
    bio = (
        legacy.get("description")
        or user_obj.get("description")
        or ""
    )
    name = (
        core.get("name")
        or legacy.get("name")
        or user_obj.get("name")
        or screen_name
    )

    return {
        "screen_name": screen_name,
        "name": name,
        "followers": int(followers) if followers else 0,
        "bio": (bio or "")[:200],
        "verified": (
            user_obj.get("is_blue_verified")
            or legacy.get("verified")
            or False
        ),
    }


# ============================================================
# 传播节奏计算
# ============================================================

def _bucket_by_time(items: list, launch_time: Optional[datetime]) -> dict:
    """
    将带时间戳的条目按发帖后时间分桶：
    0-4h / 4-24h / 1-3d / 3-7d / 7d+
    每个桶返回: count, items(前5条)
    """
    buckets = {
        "0_4h":   {"label": "0-4小时", "count": 0, "items": []},
        "4_24h":  {"label": "4-24小时", "count": 0, "items": []},
        "1_3d":   {"label": "1-3天", "count": 0, "items": []},
        "3_7d":   {"label": "3-7天", "count": 0, "items": []},
        "7d_plus":{"label": "7天以上", "count": 0, "items": []},
        "unknown":{"label": "时间未知", "count": 0, "items": []},
    }
    for item in items:
        ts = item.get("_ts")
        hours = _hours_since(ts, launch_time) if ts and launch_time else None
        if hours is None:
            key = "unknown"
        elif hours <= 4:
            key = "0_4h"
        elif hours <= 24:
            key = "4_24h"
        elif hours <= 72:
            key = "1_3d"
        elif hours <= 168:
            key = "3_7d"
        else:
            key = "7d_plus"
        buckets[key]["count"] += 1
        if len(buckets[key]["items"]) < 5:
            buckets[key]["items"].append(item)
    # 清理 unknown 为空的桶
    if buckets["unknown"]["count"] == 0:
        del buckets["unknown"]
    return buckets


def _assign_four_stage(user_type: str, followers: int, hours_delta: Optional[float]) -> str:
    """
    四阶段划分逻辑：
      Stage 1 (0-2h):   founder_ceo / 团队（检测为内部人员）
      Stage 2 (2-12h):  partner/ecosystem 类
      Stage 3 (12h-3d): 高粉 KOL（>10K）
      Stage 4 (3d+):    普通用户广泛渗透
    时间未知时仅按身份判断
    """
    h = hours_delta if hours_delta is not None else 999

    if h <= 2 and user_type in ("founder_ceo", "developer"):
        return "stage_1_internal"
    if h <= 12 and user_type in ("vc_investor", "product", "designer"):
        return "stage_2_ecosystem"
    if followers >= 10_000 and (h <= 72 or user_type in ("kol_creator", "journalist")):
        return "stage_3_kol"
    if h <= 2:
        # 2h 内但不是创始人，也归内部点燃
        return "stage_1_internal"
    if h <= 12:
        return "stage_2_ecosystem"
    return "stage_4_mass"


# ============================================================
# 近似分析降级（无 retweet API 数据时）
# ============================================================

def _approximate_from_top_tweets(top_tweets: list) -> dict:
    """
    当无法获取 retweet/quote 详细数据时，
    基于 top_tweets 的聚合指标做近似推断。
    """
    total_rts = sum(t.get("retweets", 0) or 0 for t in top_tweets)
    total_likes = sum(t.get("likes", 0) or 0 for t in top_tweets)
    total_views = sum(t.get("views", 0) or 0 for t in top_tweets)
    total_replies = sum(t.get("replies", 0) or 0 for t in top_tweets)
    total_bookmarks = sum(t.get("bookmarks", 0) or 0 for t in top_tweets)

    launch_tweets = [t for t in top_tweets if _is_launch_tweet(t.get("text", ""))]
    best_launch = max(launch_tweets or top_tweets,
                      key=lambda t: (t.get("likes", 0) or 0) + (t.get("retweets", 0) or 0),
                      default=None)

    return {
        "mode": "approximate",
        "note": "⚠️ 未能获取 retweet/quote 详情，以下为基于 top_tweets 聚合的近似推断",
        "top_tweets_analyzed": len(top_tweets),
        "aggregate_metrics": {
            "total_retweets": total_rts,
            "total_likes": total_likes,
            "total_views": total_views,
            "total_replies": total_replies,
            "total_bookmarks": total_bookmarks,
            "avg_engagement_per_tweet": round(
                (total_likes + total_rts + total_replies) / max(len(top_tweets), 1), 1
            ),
        },
        "best_launch_tweet": {
            "text": (best_launch.get("text", "") or "")[:200] if best_launch else "",
            "likes": best_launch.get("likes", 0) if best_launch else 0,
            "retweets": best_launch.get("retweets", 0) if best_launch else 0,
            "views": best_launch.get("views", 0) if best_launch else 0,
            "created_at": best_launch.get("created_at", "") if best_launch else "",
        },
        "propagation_estimate": {
            "estimated_reach": total_views or (total_rts * 50),  # 若无 views，按每次 RT 传播 50 人估算
            "viral_coefficient": round(total_rts / max(len(top_tweets), 1), 2),
            "engagement_rate": round(
                (total_likes + total_rts + total_replies) / max(total_views, 1) * 100, 3
            ) if total_views else None,
        },
    }


# ============================================================
# 主函数：analyze_launch_propagation
# ============================================================

async def analyze_launch_propagation(
    brand: str,
    launch_tweets: list,
    all_tweets: list,
) -> dict:
    """
    分析 Launch 帖的传播层级、KOL 影响力和传播节奏。

    参数
    ----
    brand         : 品牌名（用于日志/标注）
    launch_tweets : 已知的 launch 相关推文列表（可为空，将从 all_tweets 自动识别）
    all_tweets    : 账号全部 top tweets（来自 social.py 的 _deep_twitter_caravo 结果）

    返回
    ----
    完整的传播分析 dict，可直接被 growth_analysis.py 消费。
    结构见函数体内的 result 定义。
    """
    result = {
        "brand": brand,
        "data_mode": "full",         # "full" | "approximate" | "empty"
        "root_post": {},
        "propagation_layers": {
            "layer_1_retweets": {"count": 0, "users": []},
            "layer_2_quotes":   {"count": 0, "items": []},
        },
        "influencer_analysis": {
            "total_kols": 0,
            "kol_categories": {
                "founder_ceo":   0,
                "developer":     0,
                "vc_investor":   0,
                "kol_creator":   0,
                "designer":      0,
                "product":       0,
                "journalist":    0,
                "regular_user":  0,
            },
            "kol_tiers": {
                "mega_kol": 0,
                "big_kol": 0,
                "mid_kol": 0,
                "small": 0,
            },
            "top_influencers": [],
        },
        "four_stage_timeline": {
            "stage_1_internal":  {"label": "内部点燃 (0-2h)", "count": 0, "users": []},
            "stage_2_ecosystem": {"label": "生态催化 (2-12h)", "count": 0, "users": []},
            "stage_3_kol":       {"label": "KOL 引爆 (12h-3d)", "count": 0, "users": []},
            "stage_4_mass":      {"label": "广泛渗透 (3d+)", "count": 0, "users": []},
        },
        "propagation_rhythm": {},
        "follow_up_activities": [],
        "approximate_analysis": None,  # 降级时填充
        "api_calls_made": [],
        "errors": [],
    }

    # ----------------------------------------------------------
    # Step 1: 识别 launch post
    # ----------------------------------------------------------
    combined = launch_tweets + [t for t in all_tweets if t not in launch_tweets]
    launch_post = _find_launch_post(combined)

    if not launch_post:
        result["data_mode"] = "empty"
        result["errors"].append("未找到任何推文数据")
        return result

    tweet_id = _extract_tweet_id(launch_post)
    launch_time = _extract_tweet_timestamp(launch_post)

    # 尝试补全 launch post 详情（如果 ID 存在）
    if tweet_id:
        detail = _fetch_tweet_detail(tweet_id)
        result["api_calls_made"].append("twitter241/tweet-v2")
        if detail:
            launch_post = {**launch_post, **detail}

    result["root_post"] = {
        "tweet_id": tweet_id,
        "text": (launch_post.get("full_text") or launch_post.get("text", ""))[:280],
        "created_at": launch_post.get("created_at", ""),
        "likes": launch_post.get("favorite_count") or launch_post.get("likes", 0) or 0,
        "retweets": launch_post.get("retweet_count") or launch_post.get("retweets", 0) or 0,
        "replies": launch_post.get("reply_count") or launch_post.get("replies", 0) or 0,
        "quotes": launch_post.get("quote_count") or launch_post.get("quotes", 0) or 0,
        "views": (
            launch_post.get("views_count")
            or (launch_post.get("views", {}).get("count") if isinstance(launch_post.get("views"), dict) else launch_post.get("views", 0))
            or 0
        ),
        "bookmarks": launch_post.get("bookmark_count") or launch_post.get("bookmarks", 0) or 0,
        "is_launch_detected": _is_launch_tweet(
            launch_post.get("full_text") or launch_post.get("text", "")
        ),
    }

    # ----------------------------------------------------------
    # Step 2: 获取 retweets（Layer 1）
    # ----------------------------------------------------------
    rt_users = []
    if tweet_id:
        raw_rts = _fetch_retweets(tweet_id, count=100)
        result["api_calls_made"].append("twitter241/retweets")
        for item in raw_rts:
            profile = _extract_user_profile(item)
            if not profile.get("screen_name"):
                continue
            ts = _extract_tweet_timestamp(item)
            user_type = _classify_user(profile["bio"], profile["followers"])
            tier = _kol_tier(profile["followers"])
            hours = _hours_since(ts, launch_time)
            rt_users.append({
                **profile,
                "_ts": ts,
                "_hours_after_launch": round(hours, 2) if hours is not None else None,
                "user_type": user_type,
                "kol_tier": tier,
                "stage": _assign_four_stage(user_type, profile["followers"], hours),
            })

        result["propagation_layers"]["layer_1_retweets"] = {
            "count": len(rt_users),
            "users": [
                {k: v for k, v in u.items() if not k.startswith("_")}
                for u in rt_users[:20]  # 只保留前 20 条避免响应体过大
            ],
        }

    # ----------------------------------------------------------
    # Step 3: 获取 quotes（Layer 2）
    # ----------------------------------------------------------
    quote_items = []
    if tweet_id:
        raw_quotes = _fetch_quotes(tweet_id, count=100)
        result["api_calls_made"].append("twitter241/quotes")
        for item in raw_quotes:
            # quotes 返回的是 tweet 对象，需提取 author
            author_obj = (
                item.get("core", {}).get("user_results", {}).get("result", {})
                or item.get("author", {})
                or item.get("user", {})
            )
            profile = _extract_user_profile(author_obj) if author_obj else {}
            ts = _extract_tweet_timestamp(item.get("legacy", item))
            user_type = _classify_user(profile.get("bio", ""), profile.get("followers", 0))
            tier = _kol_tier(profile.get("followers", 0))
            hours = _hours_since(ts, launch_time)
            quote_items.append({
                "tweet_text": (
                    item.get("legacy", {}).get("full_text")
                    or item.get("full_text")
                    or item.get("text", "")
                )[:200],
                "author": profile,
                "user_type": user_type,
                "kol_tier": tier,
                "created_at": item.get("legacy", {}).get("created_at") or item.get("created_at", ""),
                "likes": item.get("legacy", {}).get("favorite_count") or 0,
                "retweets": item.get("legacy", {}).get("retweet_count") or 0,
                "_ts": ts,
                "_hours_after_launch": round(hours, 2) if hours is not None else None,
                "stage": _assign_four_stage(user_type, profile.get("followers", 0), hours),
            })

        result["propagation_layers"]["layer_2_quotes"] = {
            "count": len(quote_items),
            "items": [
                {k: v for k, v in q.items() if not k.startswith("_")}
                for q in sorted(quote_items, key=lambda x: x.get("likes", 0), reverse=True)[:20]
            ],
        }

    # ----------------------------------------------------------
    # Step 4: 合并所有传播者，计算 KOL 分析
    # ----------------------------------------------------------
    all_participants = rt_users + [
        {
            **(q.get("author", {}) if isinstance(q.get("author"), dict) else {}),
            "_ts": q.get("_ts"),
            "_hours_after_launch": q.get("_hours_after_launch"),
            "user_type": q.get("user_type", "regular_user"),
            "kol_tier": q.get("kol_tier", "small"),
            "stage": q.get("stage", "stage_4_mass"),
        }
        for q in quote_items
        if isinstance(q, dict)
    ]

    if all_participants:
        # KOL 分类统计
        for p in all_participants:
            cat = p.get("user_type", "regular_user")
            tier = p.get("kol_tier", "small")
            if cat in result["influencer_analysis"]["kol_categories"]:
                result["influencer_analysis"]["kol_categories"][cat] += 1
            if tier in result["influencer_analysis"]["kol_tiers"]:
                result["influencer_analysis"]["kol_tiers"][tier] += 1

        # 大V总数（粉丝 > 10K）
        result["influencer_analysis"]["total_kols"] = sum(
            1 for p in all_participants if (p.get("followers") or 0) >= 10_000
        )

        # Top 影响者（按粉丝数排序，取前 10）
        top_inf = sorted(
            [p for p in all_participants if (p.get("followers") or 0) >= 1000],
            key=lambda x: x.get("followers", 0),
            reverse=True,
        )[:10]
        result["influencer_analysis"]["top_influencers"] = [
            {
                "screen_name": p.get("screen_name", ""),
                "name": p.get("name", ""),
                "followers": p.get("followers", 0),
                "bio_snippet": (p.get("bio") or "")[:100],
                "user_type": p.get("user_type", "regular_user"),
                "kol_tier": p.get("kol_tier", "small"),
                "stage": p.get("stage", ""),
                "verified": p.get("verified", False),
                "hours_after_launch": p.get("_hours_after_launch"),
            }
            for p in top_inf
        ]

        # 四阶段统计
        for p in all_participants:
            stage = p.get("stage", "stage_4_mass")
            if stage in result["four_stage_timeline"]:
                result["four_stage_timeline"][stage]["count"] += 1
                if len(result["four_stage_timeline"][stage]["users"]) < 5:
                    result["four_stage_timeline"][stage]["users"].append({
                        "screen_name": p.get("screen_name", ""),
                        "followers": p.get("followers", 0),
                        "user_type": p.get("user_type", ""),
                        "hours_after_launch": p.get("_hours_after_launch"),
                    })

        # 传播节奏：按时间分桶
        timed_items = [p for p in all_participants]
        result["propagation_rhythm"] = _bucket_by_time(timed_items, launch_time)
        # 补充每桶的 engagement 加权（用粉丝数近似）
        for bucket_key, bucket in result["propagation_rhythm"].items():
            bucket_items = [
                p for p in all_participants
                if _get_bucket_key(p, launch_time) == bucket_key
            ]
            bucket["total_followers_reached"] = sum(
                p.get("followers", 0) or 0 for p in bucket_items
            )

        result["data_mode"] = "full"

    else:
        # --------------------------------------------------
        # 降级：无法获取传播详情，基于 top_tweets 近似分析
        # --------------------------------------------------
        result["data_mode"] = "approximate"
        result["approximate_analysis"] = _approximate_from_top_tweets(all_tweets or combined)

    # ----------------------------------------------------------
    # Step 5: 识别后续活动（AMA、Office Hours 等）
    # ----------------------------------------------------------
    FOLLOW_UP_KEYWORDS = {
        "ama": ["ama", "ask me anything", "q&a", "q & a"],
        "office_hours": ["office hours", "officehours"],
        "demo": ["demo", "walkthrough", "live demo", "watch me"],
        "thread": ["🧵", "thread", "1/", "1)"],
        "milestone": ["milestone", "users", "customers", "sign up", "waitlist", "★", "reached", "hit"],
        "media": ["featured", "techcrunch", "producthunt", "hackernews", "hn"],
    }
    for tweet in (all_tweets or []):
        text = (tweet.get("text", "") or "").lower()
        ts = _extract_tweet_timestamp(tweet)
        hours = _hours_since(ts, launch_time)
        for activity_type, keywords in FOLLOW_UP_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                result["follow_up_activities"].append({
                    "type": activity_type,
                    "tweet_text": (tweet.get("text", "") or "")[:150],
                    "created_at": tweet.get("created_at", ""),
                    "hours_after_launch": round(hours, 1) if hours is not None else None,
                    "likes": tweet.get("likes", 0) or 0,
                    "retweets": tweet.get("retweets", 0) or 0,
                })
                break  # 每条推文只分类一次

    # 去重：同类型活动只保留最高互动的
    seen_types: dict = {}
    for act in result["follow_up_activities"]:
        t = act["type"]
        if t not in seen_types or act["likes"] > seen_types[t]["likes"]:
            seen_types[t] = act
    result["follow_up_activities"] = sorted(
        seen_types.values(),
        key=lambda x: x.get("hours_after_launch") or 9999,
    )

    return result


def _get_bucket_key(p: dict, launch_time: Optional[datetime]) -> str:
    """辅助：获取某参与者所属时间桶的 key"""
    ts = p.get("_ts")
    hours = _hours_since(ts, launch_time) if ts and launch_time else None
    if hours is None:
        return "unknown"
    if hours <= 4:
        return "0_4h"
    if hours <= 24:
        return "4_24h"
    if hours <= 72:
        return "1_3d"
    if hours <= 168:
        return "3_7d"
    return "7d_plus"


# ============================================================
# growth_analysis.py 消费接口
# ============================================================

def summarize_propagation_for_growth(propagation: dict) -> dict:
    """
    将 analyze_launch_propagation 的结果压缩为 growth_analysis.py 可直接消费的摘要。
    挂载到 growth_analysis._detect_launch_waves 的返回结构上。
    """
    if not propagation or propagation.get("data_mode") == "empty":
        return {"available": False, "reason": "无传播数据"}

    root = propagation.get("root_post", {})
    inf = propagation.get("influencer_analysis", {})
    stages = propagation.get("four_stage_timeline", {})
    rhythm = propagation.get("propagation_rhythm", {})
    approx = propagation.get("approximate_analysis")

    summary = {
        "available": True,
        "data_mode": propagation.get("data_mode", "unknown"),
        "launch_post": {
            "tweet_id": root.get("tweet_id"),
            "text_snippet": (root.get("text") or "")[:120],
            "metrics": {
                "likes": root.get("likes", 0),
                "retweets": root.get("retweets", 0),
                "quotes": root.get("quotes", 0),
                "views": root.get("views", 0),
                "replies": root.get("replies", 0),
                "bookmarks": root.get("bookmarks", 0),
            },
        },
        "kol_impact": {
            "total_kols": inf.get("total_kols", 0),
            "top_category": max(
                inf.get("kol_categories", {}).items(),
                key=lambda x: x[1],
                default=("unknown", 0)
            )[0],
            "top_influencers_preview": [
                f"@{u['screen_name']} ({u['followers']:,} followers)"
                for u in inf.get("top_influencers", [])[:3]
            ],
        },
        "four_stage_summary": {
            stage: {
                "label": data.get("label", ""),
                "count": data.get("count", 0),
            }
            for stage, data in stages.items()
        },
        "peak_window": _find_peak_window(rhythm),
        "follow_up_count": len(propagation.get("follow_up_activities", [])),
        "follow_up_types": [a["type"] for a in propagation.get("follow_up_activities", [])],
    }

    if approx:
        summary["approximate_metrics"] = approx.get("aggregate_metrics", {})
        summary["estimated_reach"] = approx.get("propagation_estimate", {}).get("estimated_reach", 0)

    return summary


def _find_peak_window(rhythm: dict) -> str:
    """找出传播量最高的时间窗口"""
    if not rhythm:
        return "unknown"
    peak = max(rhythm.items(), key=lambda x: x[1].get("count", 0), default=(None, {}))
    if peak[0] and peak[1].get("count", 0) > 0:
        return rhythm[peak[0]].get("label", peak[0])
    return "unknown"
