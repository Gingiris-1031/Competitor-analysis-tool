"""社交媒体深度分析模块 — 渠道检测 + Caravo Twitter API + 传播指标"""
import httpx
import subprocess
import json
import os
import re
from urllib.parse import quote

# 可选：传播深度分析（propagation.py）
try:
    from .propagation import analyze_launch_propagation
except ImportError:
    try:
        from propagation import analyze_launch_propagation
    except ImportError:
        analyze_launch_propagation = None


def _extract_brand(domain: str) -> str:
    """Extract brand name from domain, stripping www. and all common TLDs."""
    brand = domain.lower().strip()
    brand = re.sub(r'^www\.', '', brand)
    brand = re.sub(r'\.[a-z]{2,6}$', '', brand)
    return brand


async def analyze_social(domain: str, product_name: str, website_social_links: dict = None) -> dict:
    """深度分析社交媒体存在与传播。website_social_links 来自官网提取的社媒链接，优先使用。"""
    brand = _extract_brand(domain)
    hints = website_social_links or {}  # e.g. {"twitter": {"handle": "AffineOfficial", "url": "..."}, ...}

    results = {
        "brand": brand,
        "channels": {},
        "propagation_metrics": {},
        "key_posts": [],
        "propagation_path": {"layer1": {}, "layer2": {}},
    }

    # Extract hint handles from website social links
    twitter_hint = hints.get("twitter", {}).get("handle")
    youtube_hint = hints.get("youtube", {}).get("handle")
    github_hint = hints.get("github", {}).get("handle")

    instagram_hint = hints.get("instagram", {}).get("handle")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    }) as client:
        results["channels"]["twitter"] = await _deep_twitter_caravo(brand, product_name, handle_hint=twitter_hint)
        results["channels"]["youtube"] = await _deep_youtube(client, brand, product_name, handle_hint=youtube_hint)
        results["channels"]["reddit"] = await _deep_reddit(client, brand, product_name, domain=domain)
        results["channels"]["linkedin"] = _check_linkedin(brand)
        results["channels"]["github"] = await _deep_github(client, brand, product_name, handle_hint=github_hint)
        results["channels"]["tiktok"] = _check_tiktok(brand)
        results["channels"]["instagram"] = await _deep_instagram_caravo(brand, product_name, handle_hint=instagram_hint)

    # Aggregate propagation metrics
    results["propagation_metrics"] = _calc_propagation_metrics(results)

    # Launch 传播深度分析（自动触发，如果 propagation.py 可用）
    # 使用 top_tweets 作为输入；调用方也可以在获取结果后单独调用
    # analyze_launch_propagation(brand, launch_tweets=[], all_tweets=top_tweets)
    results["launch_propagation"] = None  # 占位，需异步调用 run_launch_propagation() 填充
    results["_propagation_available"] = analyze_launch_propagation is not None

    return results


async def run_launch_propagation(social_result: dict) -> dict:
    """
    在 analyze_social() 完成后，单独触发传播深度分析。
    返回 analyze_launch_propagation() 的完整结果。

    用法示例（在 orchestrator/main 脚本中）：
        social = await analyze_social(domain, product_name)
        if social.get("_propagation_available"):
            social["launch_propagation"] = await run_launch_propagation(social)
        growth = analyze_growth_deep(..., propagation=social["launch_propagation"])

    设计为独立步骤的原因：
      - 需要额外 Caravo API 调用（retweets + quotes），每次约 $0.01
      - 不阻塞主流程；调用方可按需决定是否执行
    """
    if analyze_launch_propagation is None:
        return {"error": "propagation.py 未找到或导入失败"}

    brand = social_result.get("brand", "")
    twitter = social_result.get("channels", {}).get("twitter", {})
    top_tweets = twitter.get("top_tweets", [])

    if not top_tweets:
        return {
            "data_mode": "empty",
            "error": "Twitter top_tweets 为空，无法进行传播分析",
        }

    return await analyze_launch_propagation(
        brand=brand,
        launch_tweets=[],   # 让函数自动从 all_tweets 识别
        all_tweets=top_tweets,
    )


def _find_npx() -> str:
    """Locate npx binary — handles Docker/Railway containers where PATH may differ."""
    import shutil
    npx = shutil.which("npx")
    if npx:
        return npx
    # Common container / nvm / nodesource paths
    for candidate in [
        "/usr/bin/npx", "/usr/local/bin/npx",
        "/root/.nvm/versions/node/*/bin/npx",
        "/usr/lib/node_modules/.bin/npx",
    ]:
        import glob
        matches = glob.glob(candidate)
        if matches and os.path.isfile(matches[0]):
            return matches[0]
    return "npx"  # Last resort — hope it's on PATH


def _call_caravo_http(tool_id: str, params: dict, api_key: str) -> dict:
    """Direct HTTP fallback for Caravo API (no CLI needed)."""
    import httpx as _httpx
    try:
        resp = _httpx.post(
            "https://api.caravo.ai/v1/exec",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"tool_id": tool_id, "params": params},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return {"success": True, "data": data.get("output", data.get("data", {}))}
            err_msg = data.get("error", data.get("message", ""))
            if "balance" in str(err_msg).lower():
                return {"success": False, "error": "Caravo 余额不足", "need_topup": True}
            return {"success": False, "error": str(err_msg)[:100]}
        if resp.status_code == 402:
            return {"success": False, "error": "Caravo 余额不足", "need_topup": True}
        return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": f"HTTP fallback: {str(e)[:80]}"}


def _call_caravo(tool_id: str, params: dict) -> dict:
    """调用 Caravo — 先尝试 CLI，失败则用 HTTP API 直连"""
    api_key = os.environ.get("CARAVO_API_KEY", "").strip()
    if not api_key:
        try:
            api_key = open(os.path.expanduser("~/.cola/secrets/caravo_api_key")).read().strip()
        except FileNotFoundError:
            pass
    if not api_key:
        return {"success": False, "error": "No Caravo API key"}

    # Attempt 1: CLI
    env = os.environ.copy()
    env["CARAVO_API_KEY"] = api_key
    npx_bin = _find_npx()
    try:
        result = subprocess.run(
            [npx_bin, "-y", "@caravo/cli@latest", "exec", tool_id, "-d", json.dumps(params)],
            capture_output=True, text=True, timeout=30, env=env
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get("success"):
                return {"success": True, "data": data.get("output", {})}
        stderr = result.stderr[:200]
        if "balance" in stderr.lower() or "$0" in stderr:
            return {"success": False, "error": "Caravo 余额不足", "need_topup": True}
        # CLI failed — fall through to HTTP
    except Exception:
        pass  # CLI not available — fall through to HTTP

    # Attempt 2: Direct HTTP API
    return _call_caravo_http(tool_id, params, api_key)


async def _deep_twitter_caravo(brand: str, name: str, handle_hint: str = None) -> dict:
    """通过 Caravo Twitter API 深度分析 Twitter"""
    result = {
        "platform": "Twitter/X",
        "detected": False,
        "handle": None,
        "url": None,
        "followers": None,
        "following": None,
        "profile": {},
        "top_tweets": [],
        "note": "",
    }

    # Try to get user profile via Caravo
    # If we have a hint from the website, try it FIRST
    name_lower = name.lower().replace(" ","")
    handles_to_try = []
    if handle_hint:
        handles_to_try.append(handle_hint)
    handles_to_try.extend([f"{brand}hq", f"{name_lower}hq", brand, name_lower, f"{brand}_dev", f"{brand}ai", f"get{brand}", f"{brand}app", f"use{brand}"])
    handles_to_try = list(dict.fromkeys(handles_to_try))  # Deduplicate
    for handle in handles_to_try:
        user_data = _call_caravo("twitter241/user", {"username": handle})
        if user_data.get("success") and user_data.get("data"):
            d = user_data["data"]
            # Navigate deeply nested twitter241 response:
            # {json: {result: {data: {user: {result: {legacy: {...}, core: {...}}}}}}}
            def _dig(obj, *keys):
                for k in keys:
                    if isinstance(obj, dict):
                        obj = obj.get(k, {})
                    else:
                        return {}
                return obj if isinstance(obj, dict) else {}

            user_root = _dig(d, "json", "result", "data", "user", "result")
            legacy = user_root.get("legacy", {})
            core = user_root.get("core", {})
            
            # Fallback: try shorter paths
            if not legacy.get("followers_count"):
                user_root = _dig(d, "json", "result")
                legacy = user_root.get("legacy", user_root)
            if not legacy.get("followers_count"):
                legacy = d.get("json", d)
            
            # Skip if truly empty
            if not legacy.get("screen_name") and not legacy.get("followers_count") and not core.get("screen_name"):
                continue

            # Verify bio relevance — skip accounts whose description is clearly unrelated
            # (Unless this was from a website hint, which we trust)
            account_bio = (legacy.get("description") or "").lower()
            account_name_str = (core.get("name") or legacy.get("name") or "").lower()
            if handle_hint and handle == handle_hint:
                pass  # Trust website hint
            elif account_bio and len(account_bio) > 10:
                # For generic brand names, account name matching is useless
                # (e.g. "ENTER" as account name will always match brand "enter")
                # Instead, check if bio content has meaningful keyword overlap with the brand's domain
                is_generic_name = len(brand) <= 5 or brand.lower() in {
                    "enter", "super", "start", "build", "magic", "spark", "power",
                    "light", "smart", "cloud", "agent", "click", "blast", "pulse",
                }
                if is_generic_name:
                    # For generic brands: bio must contain domain-specific keywords
                    # or the handle must exactly match a website-linked pattern
                    # Check a few signals of relevance:
                    domain_in_bio = any(tld in account_bio for tld in [
                        f"{brand}.com", f"{brand}.io", f"{brand}.dev", f"{brand}.ai",
                        f"{brand}.pro", f"{brand}.co", f"{brand}.app",
                    ])
                    # Also accept if bio mentions typical product keywords matching the product
                    if not domain_in_bio:
                        # This handle is probably not the right one — skip
                        continue
                else:
                    # Non-generic: brand or name in bio or account name is enough
                    brand_lower_check = brand.lower()
                    name_lower_check = name.lower()
                    brand_in_bio = (brand_lower_check in account_bio or brand_lower_check in account_name_str
                                    or name_lower_check in account_bio or name_lower_check in account_name_str)
                    if not brand_in_bio:
                        continue

            result["detected"] = True
            result["handle"] = f"@{core.get('screen_name', handle)}"
            result["url"] = f"https://x.com/{core.get('screen_name', handle)}"
            result["followers"] = legacy.get("followers_count") or legacy.get("normal_followers_count")
            result["following"] = legacy.get("friends_count") or legacy.get("following_count")
            result["profile"] = {
                "name": core.get("name") or legacy.get("name", ""),
                "description": (legacy.get("description") or "")[:200],
                "verified": legacy.get("verified", False) or user_root.get("is_blue_verified", False),
                "created_at": legacy.get("created_at", ""),
                "statuses_count": legacy.get("statuses_count", 0),
                "listed_count": legacy.get("listed_count", 0),
            }
            result["note"] = "✅ 通过 Twitter API 获取到完整数据"

            # Search for top tweets
            search_data = _call_caravo("twitter241/search-v3", {"query": f"from:{handle}", "type": "Top", "count": "10"})
            if search_data.get("success") and search_data.get("data"):
                tweets_raw = search_data["data"]
                tweets = tweets_raw if isinstance(tweets_raw, list) else tweets_raw.get("tweets", tweets_raw.get("results", []))
                for tw in (tweets[:10] if isinstance(tweets, list) else []):
                    tweet = tw.get("legacy", tw) if isinstance(tw, dict) else {}
                    result["top_tweets"].append({
                        "text": (tweet.get("full_text") or tweet.get("text", ""))[:200],
                        "likes": tweet.get("favorite_count", 0),
                        "retweets": tweet.get("retweet_count", 0),
                        "replies": tweet.get("reply_count", 0),
                        "views": tweet.get("views_count") or tweet.get("views", {}).get("count", 0) if isinstance(tweet.get("views"), dict) else tweet.get("views", 0),
                        "bookmarks": tweet.get("bookmark_count", 0),
                        "created_at": tweet.get("created_at", ""),
                    })
                # Sort by likes
                result["top_tweets"].sort(key=lambda x: x.get("likes", 0), reverse=True)
            break

    if not result["detected"]:
        # Fallback: note that Caravo API may need balance
        result["note"] = f"未通过 API 找到（尝试了 {', '.join(handles_to_try[:3])}...）。可能需要 Caravo 充值或手动确认。"
        result["key_posts_framework"] = {
            "note": "🔍 需 Caravo 充值或手动补充",
            "needed_data": [
                "Launch 帖子详情（Views/Likes/Retweets/Quotes/Replies/Bookmarks）",
                "最高互动帖子 Top 5",
                "内容分类统计",
                "发布频次和节奏分析",
                "KOL 合作帖子列表",
            ],
        }

    return result


async def _deep_twitter(client: httpx.AsyncClient, brand: str, name: str) -> dict:
    """深度 Twitter/X 分析"""
    result = {
        "platform": "Twitter/X",
        "detected": False,
        "handle": None,
        "url": None,
        "followers": None,
        "following": None,
        "key_posts": [],
        "content_analysis": None,
        "note": "",
    }
    
    # Try common handle variations
    handles_to_try = [brand, f"{brand}_dev", f"{brand}hq", f"{brand}_ai", f"get{brand}"]
    
    for handle in handles_to_try:
        try:
            resp = await client.get(f"https://x.com/{handle}")
            if resp.status_code == 200 and "This account doesn" not in resp.text and "doesn't exist" not in resp.text:
                result["detected"] = True
                result["handle"] = f"@{handle}"
                result["url"] = f"https://x.com/{handle}"
                
                # Try to extract followers from page HTML
                follower_match = re.search(r'(\d[\d,.]*[KMB]?)\s*Followers', resp.text, re.I)
                if follower_match:
                    result["followers"] = follower_match.group(1)
                
                following_match = re.search(r'(\d[\d,.]*[KMB]?)\s*Following', resp.text, re.I)
                if following_match:
                    result["following"] = following_match.group(1)
                
                result["note"] = "检测到官方账号"
                
                # Framework for key post analysis (needs Twitter API for full data)
                result["key_posts_framework"] = {
                    "note": "🔍 需 Twitter API 或手动补充以下数据",
                    "needed_data": [
                        "Launch 帖子详情（Views/Likes/Retweets/Quotes/Replies/Bookmarks）",
                        "最高互动帖子 Top 5",
                        "内容分类统计（产品更新/用户案例/教程/招聘/生态合作）",
                        "发布频次和节奏分析",
                        "KOL 合作帖子列表",
                    ],
                }
                break
        except Exception:
            continue
    
    if not result["detected"]:
        result["note"] = f"未找到精确匹配（尝试了 {', '.join(handles_to_try[:3])}...），建议手动确认"
    
    return result


async def _deep_youtube(client: httpx.AsyncClient, brand: str, name: str, handle_hint: str = None) -> dict:
    """深度 YouTube 分析"""
    result = {
        "platform": "YouTube",
        "detected": False,
        "handle": None,
        "url": None,
        "subscribers": None,
        "video_count": None,
        "note": "",
    }
    
    handles = []
    if handle_hint:
        handles.append(handle_hint)
    handles.extend([brand, f"{brand}hq", name.lower().replace(" ",""), f"{brand}dev"])
    for handle in list(dict.fromkeys(handles)):
        try:
            resp = await client.get(f"https://www.youtube.com/@{handle}")
            if resp.status_code == 200 and "This page isn" not in resp.text[:1000]:
                result["detected"] = True
                result["handle"] = f"@{handle}"
                result["url"] = f"https://www.youtube.com/@{handle}"
                
                sub_match = re.search(r'"subscriberCountText".*?"(\d[\d,.]*[KMB]?)\s*subscriber', resp.text, re.I)
                if sub_match:
                    result["subscribers"] = sub_match.group(1)
                
                vid_match = re.search(r'"videoCountText".*?"(\d[\d,.]*)"', resp.text)
                if vid_match:
                    result["video_count"] = vid_match.group(1)
                
                result["note"] = "检测到官方频道"
                result["analysis_framework"] = {
                    "note": "🔍 建议手动补充",
                    "needed_data": [
                        "视频分类统计（产品demo/教程/用户访谈/活动）",
                        "Top 10 视频播放量排名",
                        "发布频率和节奏",
                        "KOL 合作视频列表",
                    ],
                }
                break
        except Exception:
            continue
    
    if not result["detected"]:
        result["note"] = "未找到精确匹配"
    
    return result


async def _deep_reddit(client: httpx.AsyncClient, brand: str, name: str, domain: str = "") -> dict:
    """深度 Reddit 分析"""
    result = {
        "platform": "Reddit",
        "detected": False,
        "has_subreddit": False,
        "subreddit_url": None,
        "subreddit_members": None,
        "mentioned_subreddits": [],
        "top_posts": [],
        "total_mentions": 0,
        "sentiment_summary": None,
        "note": "",
    }
    
    try:
        # Search Reddit — use domain + quoted product name for precision
        # For short/generic brand names, domain is the primary search term
        is_generic_brand = len(brand) <= 5 or brand.lower() in {
            "enter", "super", "start", "build", "magic", "spark", "power",
            "light", "smart", "cloud", "agent", "click", "blast", "pulse",
        }

        # Build search queries: domain-based (most precise) + name-based (broader)
        domain_for_search = f"{brand}.{name.split('.')[-1]}" if '.' not in brand else brand
        # Use the actual domain from the function args if available
        if is_generic_brand:
            # Generic brand: only search by domain or full product name
            search_terms = f'"{name}" OR url:{brand}'
        else:
            search_terms = f'"{name}" OR "{brand}"'

        resp = await client.get(
            f"https://www.reddit.com/search.json?q={quote(search_terms)}&sort=relevance&limit=25&type=link",
            headers={"User-Agent": "CompetitiveAnalysisTool/1.0"},
        )
        if resp.status_code == 200:
            data = resp.json()
            raw_posts = data.get("data", {}).get("children", [])

            # Relevance filter: stricter for generic brand names
            brand_lower = brand.lower()
            name_lower = name.lower()
            import re

            # Build the actual domain string for precise matching
            # Use the full domain (e.g. "enter.pro") passed from analyze_social()
            _domain_str = domain.lower().replace("www.", "") if domain else brand_lower

            def _is_relevant(post_data):
                title = post_data.get("title", "").lower()
                selftext = post_data.get("selftext", "").lower()
                post_url = post_data.get("url", "").lower()
                combined = f"{title} {selftext} {post_url}"

                # Full domain in the post URL or text → definitely relevant
                if _domain_str and "." in _domain_str and _domain_str in combined:
                    return True

                if is_generic_brand:
                    # For generic brands: require full domain or product-context patterns
                    # Do NOT match bare brand word (e.g. "enter" matches everything)
                    product_patterns = [
                        rf'\b{re.escape(brand_lower)}\.(?:com|io|dev|ai|pro|co|app)\b',
                        rf'\b{re.escape(brand_lower)}\s+(?:app|ai|tool|platform|product|website|builder)\b',
                    ]
                    for pat in product_patterns:
                        if re.search(pat, combined):
                            return True
                    return False
                else:
                    # Non-generic brand: check in title/selftext
                    # Full domain always matches
                    if _domain_str and "." in _domain_str and _domain_str in combined:
                        return True
                    # Brand/name in title or selftext — but filter common-word false positives
                    # by requiring it appears near tech/product context or as a proper noun
                    text_to_check = f"{title} {selftext}"
                    if brand_lower in text_to_check or name_lower in text_to_check:
                        # Extra check: is the subreddit tech-related?
                        sub = post_data.get("subreddit", "").lower()
                        tech_subs = {"programming", "webdev", "saas", "startups", "sideproject",
                                     "entrepreneur", "opensource", "selfhosted", "devops",
                                     "artificial", "machinelearning", "chatgpt", "openai",
                                     "technology", "tech", "software", "coding", "nocode",
                                     "indiehackers", "buildinpublic", "producthunt"}
                        # If posted in a tech subreddit, likely relevant
                        if any(ts in sub for ts in tech_subs):
                            return True
                        # Or if the brand appears with product-like context
                        product_ctx = re.search(
                            rf'\b{re.escape(brand_lower)}\b.*?\b(?:app|tool|dev|ai|code|build|launch|product|startup|saas|api|platform)\b',
                            text_to_check
                        ) or re.search(
                            rf'\b(?:app|tool|dev|ai|code|build|launch|product|startup|saas|api|platform)\b.*?\b{re.escape(brand_lower)}\b',
                            text_to_check
                        )
                        if product_ctx:
                            return True
                        # Domain in post URL (external link to the product)
                        if _domain_str and _domain_str in post_url:
                            return True
                    return False

            posts = [p for p in raw_posts if _is_relevant(p.get("data", {}))]
            result["total_mentions"] = len(posts)
            result["detected"] = len(posts) > 0
            if len(posts) < len(raw_posts):
                result["filtered_out"] = len(raw_posts) - len(posts)

            subreddits = {}
            for p in posts:
                d = p.get("data", {})
                sub = d.get("subreddit", "")
                subreddits[sub] = subreddits.get(sub, 0) + 1
                
                result["top_posts"].append({
                    "title": d.get("title", "")[:100],
                    "subreddit": sub,
                    "upvotes": d.get("ups", 0),
                    "comments": d.get("num_comments", 0),
                    "date": d.get("created_utc", 0),
                    "url": f"https://reddit.com{d.get('permalink', '')}",
                    "author": d.get("author", ""),
                    "is_self": d.get("is_self", False),
                })
            
            # Sort by upvotes
            result["top_posts"].sort(key=lambda x: x["upvotes"], reverse=True)
            result["top_posts"] = result["top_posts"][:10]
            
            # Subreddits sorted by mention count
            result["mentioned_subreddits"] = [
                {"name": k, "count": v}
                for k, v in sorted(subreddits.items(), key=lambda x: x[1], reverse=True)
            ][:10]
        
        # Check for dedicated subreddit (skip for generic brand names)
        if not is_generic_brand:
            sub_resp = await client.get(
                f"https://www.reddit.com/r/{brand}/about.json",
                headers={"User-Agent": "CompetitiveAnalysisTool/1.0"},
            )
            if sub_resp.status_code == 200:
                try:
                    sub_data = sub_resp.json()
                    sub_info = sub_data.get("data", {})
                    if sub_info.get("subscribers"):
                        # Extra check: subreddit description should relate to the product
                        sub_desc = (sub_info.get("public_description", "") + " " + sub_info.get("title", "")).lower()
                        brand_in_desc = brand.lower() in sub_desc or name.lower() in sub_desc
                        if brand_in_desc or sub_info.get("subscribers", 0) < 10000:
                            # Small subreddits likely belong to the product; large generic ones probably don't
                            result["has_subreddit"] = True
                            result["subreddit_url"] = f"https://reddit.com/r/{brand}"
                            result["subreddit_members"] = sub_info.get("subscribers", 0)
                except Exception:
                    pass
        
    except Exception as e:
        result["note"] = f"Error: {str(e)[:100]}"
    
    return result


async def _deep_github(client: httpx.AsyncClient, brand: str, name: str, handle_hint: str = None) -> dict:
    """深度 GitHub 分析"""
    result = {
        "platform": "GitHub",
        "detected": False,
        "type": None,
        "url": None,
        "public_repos": 0,
        "followers": 0,
        "stars_total": 0,
        "top_repos": [],
        "note": "",
    }
    
    name_lower = name.lower().replace(" ","")
    names_to_try = []
    if handle_hint:
        names_to_try.append(handle_hint)
    names_to_try.extend([f"{brand}hq", f"{name_lower}hq", brand, name_lower, f"{brand}-org"])
    names_to_try = list(dict.fromkeys(names_to_try))
    try:
        # Try HQ variant first, then brand
        resp = await client.get(f"https://api.github.com/orgs/{names_to_try[0]}")
        if resp.status_code != 200:
            resp = await client.get(f"https://api.github.com/orgs/{brand}")
        if resp.status_code == 200:
            data = resp.json()
            result["detected"] = True
            result["type"] = "organization"
            result["url"] = data.get("html_url", "")
            result["public_repos"] = data.get("public_repos", 0)
            result["followers"] = data.get("followers", 0)
        else:
            # Try all name variants as org or user
            found = False
            for alt in names_to_try:
                for endpoint in ["orgs", "users"]:
                    try:
                        r2 = await client.get(f"https://api.github.com/{endpoint}/{alt}")
                        if r2.status_code == 200:
                            data = r2.json()
                            result["detected"] = True
                            result["type"] = "organization" if endpoint == "orgs" else "user"
                            result["url"] = data.get("html_url", "")
                            result["public_repos"] = data.get("public_repos", 0)
                            result["followers"] = data.get("followers", 0)
                            brand = alt  # Use the found name for repo fetching
                            found = True
                            break
                    except:
                        pass
                if found:
                    break
        
        # Get top repos if found
        if result["detected"]:
            repos_resp = await client.get(
                f"https://api.github.com/{'orgs' if result['type'] == 'organization' else 'users'}/{brand}/repos?sort=stars&per_page=5"
            )
            if repos_resp.status_code == 200:
                repos = repos_resp.json()
                total_stars = 0
                for r in repos:
                    stars = r.get("stargazers_count", 0)
                    total_stars += stars
                    result["top_repos"].append({
                        "name": r.get("name", ""),
                        "stars": stars,
                        "language": r.get("language", ""),
                        "description": (r.get("description") or "")[:80],
                    })
                result["stars_total"] = total_stars
    except Exception as e:
        result["note"] = f"Error: {str(e)[:100]}"
    
    return result


def _check_linkedin(brand: str) -> dict:
    return {
        "platform": "LinkedIn",
        "detected": None,
        "url": f"https://www.linkedin.com/company/{brand}",
        "note": "🔍 LinkedIn 需登录验证，建议手动检查",
    }


def _check_tiktok(brand: str) -> dict:
    return {
        "platform": "TikTok",
        "detected": None,
        "url": f"https://www.tiktok.com/@{brand}",
        "note": "🔍 建议手动检查",
    }


async def _deep_instagram_caravo(brand: str, name: str, handle_hint: str = None) -> dict:
    """通过 Caravo instagram-data API 获取 Instagram 数据（account-data + user-posts）"""
    result = {
        "platform": "Instagram",
        "detected": False,
        "handle": None,
        "url": None,
        "followers": None,
        "following": None,
        "posts_count": None,
        "bio": None,
        "verified": False,
        "top_posts": [],
        "note": "",
    }

    name_lower = name.lower().replace(" ", "")
    handles_to_try = []
    if handle_hint:
        handles_to_try.append(handle_hint)
    handles_to_try.extend([brand, name_lower, f"{brand}hq", f"{brand}official", f"{brand}ai", f"{brand}app", f"get{brand}"])
    handles_to_try = list(dict.fromkeys(handles_to_try))  # Deduplicate

    found_handle = None
    account_data = None

    for handle in handles_to_try:
        try:
            resp = _call_caravo("instagram-data/account-data", {"username": handle})
            if not resp.get("success"):
                # Stop trying if it's a balance issue — no point burning more API calls
                if resp.get("need_topup"):
                    result["note"] = "⚠️ Caravo 余额不足，Instagram 数据未采集"
                    return result
                continue
            data = resp.get("data", {})
            if not data:
                continue

            # Verify relevance: bio should mention brand/product (unless handle_hint from website)
            bio = (data.get("biography") or data.get("bio") or "").lower()
            acct_name = (data.get("full_name") or data.get("name") or "").lower()
            is_hint = handle_hint and handle == handle_hint

            if not is_hint and bio and len(bio) > 5:
                brand_lower = brand.lower()
                name_lower_chk = name.lower()
                is_generic = len(brand) <= 5 or brand.lower() in {
                    "enter", "super", "start", "build", "magic", "spark", "power",
                    "light", "smart", "cloud", "agent", "click", "blast", "pulse",
                }
                if is_generic:
                    domain_in_bio = any(
                        f"{brand_lower}.{tld}" in bio
                        for tld in ["com", "io", "dev", "ai", "pro", "co", "app"]
                    )
                    if not domain_in_bio:
                        continue
                else:
                    brand_in_bio = (brand_lower in bio or brand_lower in acct_name
                                    or name_lower_chk in bio or name_lower_chk in acct_name)
                    if not brand_in_bio:
                        continue

            found_handle = handle
            account_data = data
            break
        except Exception:
            continue

    if not found_handle or not account_data:
        result["note"] = f"未通过 Caravo API 找到 Instagram（尝试了 {', '.join(handles_to_try[:3])}...）"
        return result

    # Populate account fields (Caravo returns varied key names; try multiple)
    result["detected"] = True
    result["handle"] = f"@{found_handle}"
    result["url"] = f"https://www.instagram.com/{found_handle}"
    result["followers"] = (account_data.get("follower_count")
                           or account_data.get("followers")
                           or account_data.get("edge_followed_by", {}).get("count"))
    result["following"] = (account_data.get("following_count")
                           or account_data.get("following")
                           or account_data.get("edge_follow", {}).get("count"))
    result["posts_count"] = (account_data.get("media_count")
                             or account_data.get("post_count")
                             or account_data.get("edge_owner_to_timeline_media", {}).get("count"))
    result["bio"] = (account_data.get("biography") or account_data.get("bio") or "")[:200]
    result["verified"] = bool(account_data.get("is_verified") or account_data.get("verified"))
    result["note"] = "✅ 通过 Caravo Instagram API 获取到账号数据"

    # Fetch recent posts only for accounts with meaningful follower counts (control cost)
    follower_count = result["followers"] or 0
    if isinstance(follower_count, int) and follower_count >= 500:
        try:
            posts_resp = _call_caravo("instagram-data/user-posts", {"username": found_handle})
            if posts_resp.get("success") and posts_resp.get("data"):
                raw_posts = posts_resp["data"]
                posts_list = raw_posts if isinstance(raw_posts, list) else raw_posts.get("posts", raw_posts.get("data", []))
                for p in (posts_list[:10] if isinstance(posts_list, list) else []):
                    if not isinstance(p, dict):
                        continue
                    result["top_posts"].append({
                        "caption": (p.get("caption") or p.get("text") or "")[:150],
                        "likes": p.get("like_count") or p.get("likes") or 0,
                        "comments": p.get("comment_count") or p.get("comments") or 0,
                        "timestamp": p.get("taken_at") or p.get("timestamp") or p.get("created_at") or "",
                        "type": p.get("media_type") or p.get("type") or "post",
                    })
                # Sort by likes descending
                result["top_posts"].sort(key=lambda x: x.get("likes", 0) or 0, reverse=True)
        except Exception:
            pass  # Post fetch failure is non-fatal

    return result


def _calc_propagation_metrics(data: dict) -> dict:
    """计算传播指标总览"""
    metrics = {
        "total_participants": 0,
        "estimated_impressions": 0,
        "total_engagement": 0,
        "data_sources": [],
        "breakdown": [],
    }
    
    # Twitter data (from Caravo API)
    twitter = data["channels"].get("twitter", {})
    if twitter.get("detected") and twitter.get("followers"):
        followers = twitter["followers"] if isinstance(twitter["followers"], int) else 0
        metrics["total_participants"] += followers
        metrics["estimated_impressions"] += followers  # Conservative: followers ≈ potential impressions
        # Top tweets engagement
        tweet_engagement = 0
        for tw in twitter.get("top_tweets", []):
            tweet_engagement += (tw.get("likes", 0) or 0) + (tw.get("retweets", 0) or 0) + (tw.get("replies", 0) or 0)
        metrics["total_engagement"] += tweet_engagement
        metrics["data_sources"].append("Twitter/X")
        metrics["breakdown"].append(f"Twitter: {followers:,} followers, {tweet_engagement:,} engagement (top tweets)")
    
    # Reddit data
    reddit = data["channels"].get("reddit", {})
    if reddit.get("top_posts"):
        reddit_engagement = 0
        for post in reddit["top_posts"]:
            reddit_engagement += (post.get("upvotes", 0) or 0) + (post.get("comments", 0) or 0)
        metrics["total_engagement"] += reddit_engagement
        metrics["total_participants"] += reddit.get("total_mentions", 0)
        if reddit.get("subreddit_members"):
            metrics["total_participants"] += reddit["subreddit_members"]
            metrics["estimated_impressions"] += reddit["subreddit_members"]
        metrics["data_sources"].append("Reddit")
        metrics["breakdown"].append(f"Reddit: {reddit.get('total_mentions', 0)} posts, {reddit_engagement:,} engagement")
    
    # GitHub data
    github = data["channels"].get("github", {})
    if github.get("detected"):
        gh_stars = github.get("stars_total", 0) or 0
        gh_followers = github.get("followers", 0) or 0
        metrics["total_engagement"] += gh_stars
        metrics["total_participants"] += gh_followers
        metrics["data_sources"].append("GitHub")
        metrics["breakdown"].append(f"GitHub: {gh_stars:,} stars, {gh_followers:,} followers")
    
    # YouTube
    youtube = data["channels"].get("youtube", {})
    if youtube.get("detected"):
        subs = youtube.get("subscribers")
        if subs:
            try:
                sub_num = int(str(subs).replace(",", "").replace("K", "000").replace("M", "000000"))
                metrics["total_participants"] += sub_num
                metrics["estimated_impressions"] += sub_num
            except:
                pass
        metrics["data_sources"].append("YouTube")

    # Instagram data (from Caravo API)
    instagram = data["channels"].get("instagram", {})
    if instagram.get("detected"):
        ig_followers = instagram.get("followers") or 0
        if isinstance(ig_followers, int) and ig_followers > 0:
            metrics["total_participants"] += ig_followers
            metrics["estimated_impressions"] += ig_followers
        ig_engagement = sum(
            (p.get("likes", 0) or 0) + (p.get("comments", 0) or 0)
            for p in instagram.get("top_posts", [])
        )
        metrics["total_engagement"] += ig_engagement
        metrics["data_sources"].append("Instagram")
        metrics["breakdown"].append(
            f"Instagram: {ig_followers:,} followers, {ig_engagement:,} engagement (top posts)"
            if isinstance(ig_followers, int) else f"Instagram: detected"
        )

    if not metrics["data_sources"]:
        metrics["note"] = "⚠️ 未能自动采集到社交媒体数据。建议手动补充。"
    else:
        missing = []
        if not twitter.get("detected"): missing.append("Twitter/X")
        if not youtube.get("detected"): missing.append("YouTube")
        missing.extend(["LinkedIn", "TikTok"])
        metrics["note"] = f"📊 已采集: {', '.join(metrics['data_sources'])}。" + (f" 未采集: {', '.join(missing)}。" if missing else "")
    
    return metrics
