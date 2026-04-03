"""社交媒体深度分析模块 — 渠道检测 + Apify/Caravo Twitter API + 传播指标"""
import httpx
import subprocess
import json
import os
import re
import logging
from urllib.parse import quote

log = logging.getLogger(__name__)

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
    """深度分析社交媒体存在与传播。优先使用 Brave Search 找到官方账号，其次用官网链接。"""
    brand = _extract_brand(domain)

    results = {
        "brand": brand,
        "channels": {},
        "propagation_metrics": {},
        "key_posts": [],
        "propagation_path": {"layer1": {}, "layer2": {}},
    }

    # Step 0: Use Brave Search as primary source for official social handles
    try:
        from .web_search import brave_find_social
    except ImportError:
        try:
            from web_search import brave_find_social
        except ImportError:
            brave_find_social = None

    brave_hints = {}
    if brave_find_social:
        try:
            brave_hints = await brave_find_social(brand, product_name, domain=domain)
        except Exception:
            brave_hints = {}

    # Merge: Brave Search takes priority over website hints
    website_hints = website_social_links or {}
    hints = {}
    for platform in set(list(brave_hints.keys()) + list(website_hints.keys())):
        hints[platform] = brave_hints.get(platform) or website_hints.get(platform) or {}

    # Extract hint handles
    twitter_hint   = hints.get("twitter", {}).get("handle")
    youtube_hint   = hints.get("youtube", {}).get("handle")
    github_hint    = hints.get("github", {}).get("handle")
    instagram_hint = hints.get("instagram", {}).get("handle")
    tiktok_hint    = hints.get("tiktok", {}).get("handle")
    facebook_hint  = hints.get("facebook", {}).get("handle")

    # Store hints for Phase 1.5 slow-channel callers (TikTok/Facebook run separately)
    results["_tiktok_hint"] = tiktok_hint
    results["_facebook_hint"] = facebook_hint
    # Placeholders — will be filled by app.py Phase 1.5
    results["channels"]["tiktok"]   = {"platform": "TikTok",    "detected": False, "note": "🔄 采集中…"}
    results["channels"]["facebook"] = {"platform": "Facebook",  "detected": False, "note": "🔄 采集中…"}

    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    }) as client:
        # Fast channels only (≤20s each) — TikTok/Facebook use Apify and need 45-55s, run separately
        import asyncio as _aio
        twitter_task   = _deep_twitter_caravo(brand, product_name, handle_hint=twitter_hint)
        youtube_task   = _deep_youtube(client, brand, product_name, handle_hint=youtube_hint)
        reddit_task    = _deep_reddit(client, brand, product_name, domain=domain)
        github_task    = _deep_github(client, brand, product_name, handle_hint=github_hint)
        instagram_task = _deep_instagram_caravo(brand, product_name, handle_hint=instagram_hint)

        channel_results = await _aio.gather(
            twitter_task, youtube_task, reddit_task, github_task, instagram_task,
            return_exceptions=True,
        )

        channel_names = ["twitter", "youtube", "reddit", "github", "instagram"]
        for ch_name, res in zip(channel_names, channel_results):
            if isinstance(res, Exception):
                log.warning("Channel %s failed: %s", ch_name, res)
                results["channels"][ch_name] = {"platform": ch_name, "detected": False, "error": str(res)[:100]}
            else:
                results["channels"][ch_name] = res

        # Sync check (no I/O, instant)
        results["channels"]["linkedin"] = _check_linkedin(brand)

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


# ---------------------------------------------------------------------------
# Apify REST API helpers — Twitter data via apidojo/twitter-profile-scraper
# ---------------------------------------------------------------------------

# Actor IDs on Apify
_APIFY_PROFILE_ACTOR = "apidojo/twitter-profile-scraper"
_APIFY_TWEET_ACTOR = "apidojo/tweet-scraper"


def _get_apify_token() -> str:
    """Return Apify API token from env var or secrets file, or empty string."""
    token = os.environ.get("APIFY_API_TOKEN", "").strip()
    if token:
        return token
    try:
        token = open(os.path.expanduser("~/.cola/secrets/apify_api_token")).read().strip()
    except (FileNotFoundError, OSError):
        pass
    return token


async def _call_apify_twitter_user(handle: str) -> dict:
    """Fetch a Twitter user profile + recent tweets via Apify twitter-profile-scraper.

    Returns ``{"success": True, "profile": {...}, "tweets": [...]}`` on success,
    or ``{"success": False, "error": "..."}`` on failure.

    The profile dict contains: userName, name, followers, following, description,
    isBlueVerified.  Tweets list contains dicts with text, likeCount, retweetCount,
    replyCount, viewCount, bookmarkCount, createdAt.
    """
    token = _get_apify_token()
    if not token:
        return {"success": False, "error": "No APIFY_API_TOKEN configured"}

    actor_id = _APIFY_PROFILE_ACTOR
    api_base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {token}"}
    run_input = {
        "twitterHandles": [handle],
        "maxItems": 40,  # 40 included free per profile ($0.016)
    }

    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            # Start actor run and wait synchronously (up to 60s)
            resp = await client.post(
                f"{api_base}/acts/{actor_id}/runs",
                headers=headers,
                json=run_input,
                params={"waitForFinish": 60},
            )
            if resp.status_code not in (200, 201):
                return {"success": False, "error": f"Apify run start HTTP {resp.status_code}"}

            run_data = resp.json().get("data", {})
            run_id = run_data.get("id")
            run_status = run_data.get("status")

            if not run_id:
                return {"success": False, "error": "Apify run missing id"}

            # If still running after waitForFinish, poll a couple more times
            if run_status not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                for _ in range(3):
                    import asyncio
                    await asyncio.sleep(10)
                    status_resp = await client.get(
                        f"{api_base}/actor-runs/{run_id}",
                        headers=headers,
                    )
                    if status_resp.status_code == 200:
                        run_status = status_resp.json().get("data", {}).get("status")
                        if run_status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                            break

            if run_status != "SUCCEEDED":
                return {"success": False, "error": f"Apify run status: {run_status}"}

            # Fetch dataset items
            ds_resp = await client.get(
                f"{api_base}/actor-runs/{run_id}/dataset/items",
                headers=headers,
                params={"format": "json"},
            )
            if ds_resp.status_code != 200:
                return {"success": False, "error": f"Apify dataset HTTP {ds_resp.status_code}"}

            items = ds_resp.json()
            if not isinstance(items, list) or not items:
                return {"success": False, "error": "Apify returned empty dataset"}

            # Extract profile from the first item's author field
            first = items[0] if items else {}
            author = first.get("author", {})
            profile = {
                "userName": author.get("userName", handle),
                "name": author.get("name", ""),
                "followers": author.get("followers"),
                "following": author.get("following"),
                "description": (author.get("description") or "")[:200],
                "isBlueVerified": author.get("isBlueVerified", False),
                "isVerified": author.get("isVerified", False),
                "id": author.get("id", ""),
            }

            # Extract tweets
            tweets = []
            for item in items:
                if item.get("type") not in (None, "tweet"):
                    continue  # skip replies if any leaked in
                tweets.append({
                    "text": (item.get("fullText") or item.get("text") or "")[:200],
                    "likeCount": item.get("likeCount", 0),
                    "retweetCount": item.get("retweetCount", 0),
                    "replyCount": item.get("replyCount", 0),
                    "viewCount": item.get("viewCount", 0),
                    "bookmarkCount": item.get("bookmarkCount", 0),
                    "quoteCount": item.get("quoteCount", 0),
                    "createdAt": item.get("createdAt", ""),
                    "url": item.get("url", ""),
                })

            return {"success": True, "profile": profile, "tweets": tweets}

    except httpx.TimeoutException:
        log.warning("Apify twitter-profile-scraper timed out for @%s", handle)
        return {"success": False, "error": "Apify request timed out"}
    except Exception as e:
        log.warning("Apify twitter-profile-scraper error for @%s: %s", handle, e)
        return {"success": False, "error": f"Apify error: {str(e)[:120]}"}


async def _call_apify_twitter_search(handle: str, count: int = 10) -> dict:
    """Search top tweets from a user via Apify tweet-scraper.

    Uses ``searchTerms: ["from:{handle}"]`` with ``sort: "Top"``.
    Returns ``{"success": True, "tweets": [...]}`` or ``{"success": False, ...}``.

    Note: apidojo/tweet-scraper requires minimum 50 results per query.
    We request 50 and trim to *count* on our side.
    """
    token = _get_apify_token()
    if not token:
        return {"success": False, "error": "No APIFY_API_TOKEN configured"}

    actor_id = _APIFY_TWEET_ACTOR
    api_base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {token}"}
    run_input = {
        "searchTerms": [f"from:{handle}"],
        "sort": "Top",
        "maxItems": max(50, count),  # minimum 50 required by actor
    }

    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            resp = await client.post(
                f"{api_base}/acts/{actor_id}/runs",
                headers=headers,
                json=run_input,
                params={"waitForFinish": 60},
            )
            if resp.status_code not in (200, 201):
                return {"success": False, "error": f"Apify tweet-scraper HTTP {resp.status_code}"}

            run_data = resp.json().get("data", {})
            run_id = run_data.get("id")
            run_status = run_data.get("status")

            if not run_id:
                return {"success": False, "error": "Apify run missing id"}

            if run_status not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                for _ in range(3):
                    import asyncio
                    await asyncio.sleep(10)
                    status_resp = await client.get(
                        f"{api_base}/actor-runs/{run_id}",
                        headers=headers,
                    )
                    if status_resp.status_code == 200:
                        run_status = status_resp.json().get("data", {}).get("status")
                        if run_status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                            break

            if run_status != "SUCCEEDED":
                return {"success": False, "error": f"Apify run status: {run_status}"}

            ds_resp = await client.get(
                f"{api_base}/actor-runs/{run_id}/dataset/items",
                headers=headers,
                params={"format": "json"},
            )
            if ds_resp.status_code != 200:
                return {"success": False, "error": f"Apify dataset HTTP {ds_resp.status_code}"}

            items = ds_resp.json()
            if not isinstance(items, list):
                return {"success": False, "error": "Apify tweet-scraper returned unexpected format"}

            tweets = []
            for item in items[:count]:
                tweets.append({
                    "text": (item.get("fullText") or item.get("text") or "")[:200],
                    "likeCount": item.get("likeCount", 0),
                    "retweetCount": item.get("retweetCount", 0),
                    "replyCount": item.get("replyCount", 0),
                    "viewCount": item.get("viewCount", 0),
                    "bookmarkCount": item.get("bookmarkCount", 0),
                    "quoteCount": item.get("quoteCount", 0),
                    "createdAt": item.get("createdAt", ""),
                    "url": item.get("url", ""),
                })

            return {"success": True, "tweets": tweets}

    except httpx.TimeoutException:
        log.warning("Apify tweet-scraper timed out for @%s", handle)
        return {"success": False, "error": "Apify tweet-scraper timed out"}
    except Exception as e:
        log.warning("Apify tweet-scraper error for @%s: %s", handle, e)
        return {"success": False, "error": f"Apify tweet-scraper: {str(e)[:120]}"}


async def _call_apify_actor(actor_id: str, input_data: dict, wait_secs: int = 50) -> dict:
    """通用 Apify actor 调用器 — 启动 run → 等待 → 拉取 dataset items"""
    import asyncio as _aio
    token = _get_apify_token()
    if not token:
        return {"success": False, "error": "No APIFY_API_TOKEN configured"}

    api_base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=90, headers=headers) as client:
            resp = await client.post(
                f"{api_base}/acts/{actor_id}/runs",
                json=input_data,
                params={"waitForFinish": wait_secs},
            )
            if resp.status_code not in (200, 201):
                return {"success": False, "error": f"Apify run HTTP {resp.status_code}"}

            run_data = resp.json().get("data", {})
            run_id = run_data.get("id")
            run_status = run_data.get("status", "")

            if not run_id:
                return {"success": False, "error": "Apify run missing id"}

            # Poll if still running after waitForFinish
            if run_status not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                for _ in range(4):
                    await _aio.sleep(5)
                    poll = await client.get(f"{api_base}/actor-runs/{run_id}")
                    run_status = poll.json().get("data", {}).get("status", "")
                    if run_status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                        break

            if run_status != "SUCCEEDED":
                return {"success": False, "error": f"Apify run ended: {run_status}"}

            ds_resp = await client.get(
                f"{api_base}/actor-runs/{run_id}/dataset/items",
                params={"format": "json"},
            )
            if ds_resp.status_code != 200:
                return {"success": False, "error": f"Apify dataset HTTP {ds_resp.status_code}"}

            items = ds_resp.json()
            if not isinstance(items, list):
                return {"success": False, "error": "Unexpected Apify dataset format"}
            return {"success": True, "items": items}

    except httpx.TimeoutException:
        return {"success": False, "error": f"Apify actor {actor_id} timed out"}
    except Exception as e:
        return {"success": False, "error": f"Apify actor error: {str(e)[:120]}"}


async def _deep_twitter_caravo(brand: str, name: str, handle_hint: str = None) -> dict:
    """深度分析 Twitter — 优先 Apify REST API，fallback Caravo CLI/HTTP"""
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

    name_lower = name.lower().replace(" ", "")
    handles_to_try = []
    if handle_hint:
        handles_to_try.append(handle_hint)
    handles_to_try.extend([
        f"{brand}hq", f"{name_lower}hq", brand, name_lower,
        f"{brand}_dev", f"{brand}ai", f"get{brand}", f"{brand}app", f"use{brand}",
    ])
    handles_to_try = list(dict.fromkeys(handles_to_try))  # Deduplicate

    # ------------------------------------------------------------------
    # Strategy 1: Apify REST API (apidojo/twitter-profile-scraper)
    # ------------------------------------------------------------------
    apify_token = _get_apify_token()
    if apify_token:
        for handle in handles_to_try:
            apify_resp = await _call_apify_twitter_user(handle)
            if not apify_resp.get("success"):
                log.debug("Apify miss for @%s: %s", handle, apify_resp.get("error", ""))
                # If token issue, stop trying Apify entirely
                if "token" in apify_resp.get("error", "").lower():
                    break
                continue

            prof = apify_resp.get("profile", {})
            apify_tweets = apify_resp.get("tweets", [])

            # Skip if profile looks empty
            if not prof.get("userName") and not prof.get("followers"):
                continue

            # ---- Bio relevance verification (same logic as Caravo path) ----
            account_bio = (prof.get("description") or "").lower()
            account_name_str = (prof.get("name") or "").lower()
            if handle_hint and handle == handle_hint:
                pass  # Trust website hint
            elif account_bio and len(account_bio) > 10:
                is_generic_name = len(brand) <= 5 or brand.lower() in {
                    "enter", "super", "start", "build", "magic", "spark", "power",
                    "light", "smart", "cloud", "agent", "click", "blast", "pulse",
                }
                if is_generic_name:
                    domain_in_bio = any(tld in account_bio for tld in [
                        f"{brand}.com", f"{brand}.io", f"{brand}.dev", f"{brand}.ai",
                        f"{brand}.pro", f"{brand}.co", f"{brand}.app",
                    ])
                    if not domain_in_bio:
                        continue
                else:
                    brand_lower_check = brand.lower()
                    name_lower_check = name.lower()
                    brand_in_bio = (
                        brand_lower_check in account_bio or brand_lower_check in account_name_str
                        or name_lower_check in account_bio or name_lower_check in account_name_str
                    )
                    if not brand_in_bio:
                        continue

            # ---- Populate result from Apify data ----
            screen_name = prof.get("userName", handle)
            result["detected"] = True
            result["handle"] = f"@{screen_name}"
            result["url"] = f"https://x.com/{screen_name}"
            result["followers"] = prof.get("followers")
            result["following"] = prof.get("following")
            result["profile"] = {
                "name": prof.get("name", ""),
                "description": (prof.get("description") or "")[:200],
                "verified": prof.get("isBlueVerified", False) or prof.get("isVerified", False),
                "created_at": "",  # profile-scraper doesn't return creation date in author
                "statuses_count": 0,
                "listed_count": 0,
            }
            result["note"] = "✅ 通过 Apify REST API 获取到完整数据"

            # Map Apify tweet format → internal format
            for tw in apify_tweets[:10]:
                result["top_tweets"].append({
                    "text": (tw.get("text") or "")[:200],
                    "likes": tw.get("likeCount", 0),
                    "retweets": tw.get("retweetCount", 0),
                    "replies": tw.get("replyCount", 0),
                    "views": tw.get("viewCount", 0),
                    "bookmarks": tw.get("bookmarkCount", 0),
                    "created_at": tw.get("createdAt", ""),
                })
            # Sort by likes descending
            result["top_tweets"].sort(key=lambda x: x.get("likes", 0), reverse=True)

            log.info("Twitter data for @%s fetched via Apify", screen_name)
            return result

        # If we reach here, Apify didn't find a matching account — fall through
        log.info("Apify did not resolve Twitter for brand=%s, falling back to Caravo", brand)

    # ------------------------------------------------------------------
    # Strategy 2: Caravo CLI / HTTP fallback (original logic)
    # ------------------------------------------------------------------
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
                is_generic_name = len(brand) <= 5 or brand.lower() in {
                    "enter", "super", "start", "build", "magic", "spark", "power",
                    "light", "smart", "cloud", "agent", "click", "blast", "pulse",
                }
                if is_generic_name:
                    domain_in_bio = any(tld in account_bio for tld in [
                        f"{brand}.com", f"{brand}.io", f"{brand}.dev", f"{brand}.ai",
                        f"{brand}.pro", f"{brand}.co", f"{brand}.app",
                    ])
                    if not domain_in_bio:
                        continue
                else:
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
            result["note"] = "✅ 通过 Caravo Twitter API 获取到完整数据（Apify fallback）"

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
        # Fallback: try Brave Search to extract follower count from snippets
        if handle_hint:
            followers = await _brave_twitter_followers(handle_hint)
            result["detected"] = True
            result["handle"] = f"@{handle_hint}" if not handle_hint.startswith("@") else handle_hint
            result["url"] = f"https://x.com/{handle_hint.lstrip('@')}"
            if followers:
                result["followers"] = followers
                result["note"] = "粉丝数来自 Brave Search 摘要（近似值）"
            else:
                result["note"] = "受 API 限制，仅显示账号信息（粉丝数/推文需 Apify/Caravo 支持）"
        else:
            tried_str = ", ".join(handles_to_try[:3])
            sources = "Apify + Caravo" if apify_token else "Caravo"
            result["note"] = f"未通过 {sources} 找到（尝试了 {tried_str}...）。可能需要充值或手动确认。"
        result["key_posts_framework"] = {
            "note": "🔍 需 API 充值或手动补充",
            "needed_data": [
                "Launch 帖子详情（Views/Likes/Retweets/Quotes/Replies/Bookmarks）",
                "最高互动帖子 Top 5",
                "内容分类统计",
                "发布频次和节奏分析",
                "KOL 合作帖子列表",
            ],
        }

    return result


async def _brave_twitter_followers(handle: str) -> int | None:
    """Brave Search 摘要提取 Twitter 粉丝数（免费兜底，数据粗糙）"""
    try:
        from .web_search import brave_search
    except ImportError:
        try:
            from web_search import brave_search
        except ImportError:
            return None
    try:
        results = await brave_search(f"x.com/{handle.lstrip('@')} followers", count=3)
        for r in results:
            text = (r.get("description") or "") + " " + (r.get("title") or "")
            m = re.search(r'([\d,]+\.?\d*)\s*([KMk])?\s*Followers', text, re.I)
            if m:
                raw = m.group(1).replace(",", "")
                suffix = (m.group(2) or "").upper()
                mult = {"K": 1_000, "M": 1_000_000}.get(suffix, 1)
                try:
                    return int(float(raw) * mult)
                except ValueError:
                    pass
    except Exception:
        pass
    return None


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
    """深度 YouTube 分析 — 优先 Apify apidojo/youtube-channel-scraper，fallback HTML"""
    result = {
        "platform": "YouTube",
        "detected": False,
        "handle": None,
        "url": None,
        "subscribers": None,
        "video_count": None,
        "total_views": None,
        "note": "",
    }

    handles = []
    if handle_hint:
        handles.append(handle_hint.lstrip("@"))
    handles.extend([brand, f"{brand}hq", name.lower().replace(" ", ""), f"{brand}dev"])
    handles = list(dict.fromkeys(handles))

    # Strategy 1: Apify youtube-channel-scraper
    if _get_apify_token():
        for handle in handles:
            channel_url = f"https://www.youtube.com/@{handle}"
            resp = await _call_apify_actor(
                "apidojo/youtube-channel-scraper",
                {"channelUrls": [channel_url]},
                wait_secs=45,
            )
            if not resp.get("success"):
                log.debug("Apify YouTube miss for @%s: %s", handle, resp.get("error", ""))
                continue
            items = resp.get("items", [])
            if not items:
                continue
            ch = items[0]

            # Relevance check (skip if handle came from hint — already trusted)
            ch_name = (ch.get("channelName") or ch.get("title") or "").lower()
            if not (handle_hint and handle == handle_hint.lstrip("@")):
                if brand.lower() not in ch_name and name.lower() not in ch_name:
                    continue

            result["detected"] = True
            result["handle"] = f"@{handle}"
            result["url"] = ch.get("channelUrl") or channel_url
            result["subscribers"] = ch.get("numberOfSubscribers") or ch.get("subscriberCount")
            result["video_count"] = ch.get("numberOfVideos") or ch.get("videoCount")
            result["total_views"] = ch.get("channelTotalViews") or ch.get("viewCount")
            result["note"] = "✅ 通过 Apify 获取 YouTube 频道数据"
            log.info("YouTube data for @%s fetched via Apify", handle)
            return result

    # Strategy 2: HTML fallback (no subscriber count due to YouTube JS rendering)
    for handle in handles:
        try:
            r = await client.get(f"https://www.youtube.com/@{handle}")
            if r.status_code == 200 and "This page isn" not in r.text[:1000]:
                result["detected"] = True
                result["handle"] = f"@{handle}"
                result["url"] = f"https://www.youtube.com/@{handle}"
                sub_m = re.search(r'"subscriberCountText".*?"([\d,.]+[KMB]?)\s*subscriber', r.text, re.I)
                if sub_m:
                    result["subscribers"] = sub_m.group(1)
                result["note"] = "检测到频道（HTML 解析，数据有限）"
                return result
        except Exception:
            continue

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


async def _deep_tiktok_apify(brand: str, name: str, handle_hint: str = None) -> dict:
    """深度 TikTok 分析 — Apify apidojo/tiktok-profile-scraper"""
    result = {
        "platform": "TikTok",
        "detected": False,
        "handle": None,
        "url": None,
        "followers": None,
        "following": None,
        "likes": None,
        "video_count": None,
        "verified": False,
        "note": "",
    }

    handles = []
    if handle_hint:
        handles.append(handle_hint.lstrip("@"))
    handles.extend([brand, name.lower().replace(" ", ""), f"{brand}hq", f"{brand}app", f"{brand}official"])
    handles = list(dict.fromkeys(handles))

    if not _get_apify_token():
        result["url"] = f"https://www.tiktok.com/@{brand}"
        result["note"] = "⚠️ 未配置 APIFY_API_TOKEN"
        return result

    for handle in handles:
        resp = await _call_apify_actor(
            "apidojo/tiktok-profile-scraper",
            {"profiles": [f"@{handle}"]},
            wait_secs=45,
        )
        if not resp.get("success"):
            log.debug("Apify TikTok miss for @%s: %s", handle, resp.get("error", ""))
            continue
        items = resp.get("items", [])
        if not items:
            continue
        prof = items[0]

        # Relevance check
        prof_name = (prof.get("nickname") or prof.get("uniqueId") or "").lower()
        bio = (prof.get("signature") or "").lower()
        if not (handle_hint and handle == handle_hint.lstrip("@")):
            if brand.lower() not in prof_name and brand.lower() not in bio and name.lower() not in bio:
                continue

        result["detected"] = True
        uid = prof.get("uniqueId") or handle
        result["handle"] = f"@{uid}"
        result["url"] = f"https://www.tiktok.com/@{uid}"
        result["followers"] = prof.get("fans") or prof.get("followerCount")
        result["following"] = prof.get("following") or prof.get("followingCount")
        result["likes"] = prof.get("heart") or prof.get("heartCount") or prof.get("diggCount")
        result["video_count"] = prof.get("video") or prof.get("videoCount")
        result["verified"] = bool(prof.get("verified"))
        result["note"] = "✅ 通过 Apify 获取 TikTok 账号数据"
        log.info("TikTok data for @%s fetched via Apify", uid)
        return result

    result["url"] = f"https://www.tiktok.com/@{brand}"
    result["note"] = f"未找到匹配 TikTok 账号（尝试了 {', '.join(handles[:3])}）"
    return result


async def _deep_facebook_apify(brand: str, name: str, handle_hint: str = None) -> dict:
    """Facebook 页面分析 — Apify apify/facebook-pages-scraper"""
    result = {
        "platform": "Facebook",
        "detected": False,
        "handle": None,
        "url": None,
        "followers": None,
        "likes": None,
        "about": None,
        "note": "",
    }

    handles = []
    if handle_hint:
        handles.append(handle_hint.lstrip("@"))
    handles.extend([brand, name.lower().replace(" ", ""), f"{brand}hq", f"{brand}official"])
    handles = list(dict.fromkeys(handles))

    if not _get_apify_token():
        result["url"] = f"https://www.facebook.com/{brand}"
        result["note"] = "⚠️ 未配置 APIFY_API_TOKEN"
        return result

    # Try first 2 handles — Facebook scraping is slow, limit scope
    for handle in handles[:2]:
        fb_url = f"https://www.facebook.com/{handle}"
        resp = await _call_apify_actor(
            "apify/facebook-pages-scraper",
            {"startUrls": [{"url": fb_url}], "maxPosts": 0},
            wait_secs=55,
        )
        if not resp.get("success"):
            log.debug("Apify Facebook miss for %s: %s", fb_url, resp.get("error", ""))
            continue
        items = resp.get("items", [])
        if not items:
            continue
        page = items[0]

        # Relevance check
        page_name = (page.get("name") or page.get("title") or "").lower()
        if not (handle_hint and handle == handle_hint.lstrip("@")):
            if brand.lower() not in page_name and name.lower() not in page_name:
                continue

        result["detected"] = True
        result["handle"] = handle
        result["url"] = page.get("url") or fb_url
        result["followers"] = page.get("followers") or page.get("followersCount")
        result["likes"] = page.get("likes") or page.get("likesCount")
        result["about"] = (page.get("about") or page.get("description") or "")[:200]
        result["note"] = "✅ 通过 Apify 获取 Facebook 页面数据"
        log.info("Facebook data for %s fetched via Apify", handle)
        return result

    result["url"] = f"https://www.facebook.com/{brand}"
    result["note"] = f"未找到匹配 Facebook 页面（尝试了 {', '.join(handles[:2])}）"
    return result


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

    # TikTok data
    tiktok = data["channels"].get("tiktok", {})
    if tiktok.get("detected"):
        tk_followers = tiktok.get("followers") or 0
        if isinstance(tk_followers, int) and tk_followers > 0:
            metrics["total_participants"] += tk_followers
            metrics["estimated_impressions"] += tk_followers
        tk_likes = tiktok.get("likes") or 0
        if isinstance(tk_likes, int):
            metrics["total_engagement"] += tk_likes
        metrics["data_sources"].append("TikTok")
        metrics["breakdown"].append(
            f"TikTok: {tk_followers:,} followers" + (f", {tk_likes:,} total likes" if tk_likes else "")
            if isinstance(tk_followers, int) else "TikTok: detected"
        )

    # Facebook data
    facebook = data["channels"].get("facebook", {})
    if facebook.get("detected"):
        fb_followers = facebook.get("followers") or facebook.get("likes") or 0
        if isinstance(fb_followers, int) and fb_followers > 0:
            metrics["total_participants"] += fb_followers
            metrics["estimated_impressions"] += fb_followers
        metrics["data_sources"].append("Facebook")
        metrics["breakdown"].append(
            f"Facebook: {fb_followers:,} followers"
            if isinstance(fb_followers, int) else "Facebook: detected"
        )

    if not metrics["data_sources"]:
        metrics["note"] = "⚠️ 未能自动采集到社交媒体数据。建议手动补充。"
    else:
        missing = []
        if not twitter.get("detected"):  missing.append("Twitter/X")
        if not youtube.get("detected"):  missing.append("YouTube")
        if not tiktok.get("detected"):   missing.append("TikTok")
        if not facebook.get("detected"): missing.append("Facebook")
        missing.append("LinkedIn")
        metrics["note"] = f"📊 已采集: {', '.join(metrics['data_sources'])}。" + (f" 未采集: {', '.join(missing)}。" if missing else "")
    
    return metrics
