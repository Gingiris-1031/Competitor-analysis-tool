"""社交媒体深度分析模块 — 渠道检测 + Apify/Caravo Twitter API + 传播指标"""
import httpx
import subprocess
import json
import os
import re
import logging
from urllib.parse import quote

from .i18n import _T

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


def _handle_matches_brand(handle: str, brand: str, product_name: str) -> bool:
    """Sanity-check a fuzzily-discovered social handle against the brand.

    Brave search returns the most-frequent handle for a loose query like
    `"gingiris" official twitter`, which can surface an unrelated account
    (e.g. @gingrnation for gingiris). When we can't validate via an API
    (bio/website/verified signals), require the handle to actually overlap
    the brand or product name — otherwise reject it as a false positive.
    """
    def _norm(s: str) -> str:
        return re.sub(r'[^a-z0-9]', '', (s or '').lower())

    h = _norm(handle)
    b = _norm(brand)
    n = _norm(product_name)
    if not h:
        return False
    # Accept when the brand/name is contained in the handle (brand, brandhq,
    # brandofficial, get-brand…) or vice-versa (handle is an abbreviation the
    # brand contains). Require ≥4 chars on the matched token to avoid spurious
    # short-substring hits.
    for token in (b, n):
        if token and len(token) >= 4 and (token in h or (h in token and len(h) >= 4)):
            return True
    return False


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

    # Merge hints: website links > Brave, but validate both against brand name.
    # website_hints can contain false positives: testimonial users' Twitter handles,
    # competitor links in blog posts, share-widget URLs etc.
    # We validate ALL hints with _handle_matches_brand() before accepting.
    # Exception: high-confidence sources (link[rel=me], JSON-LD sameAs weight=4)
    # from _extract_social_links are already authoritative — we keep them.
    # Brave results are always validated.
    website_hints = website_social_links or {}
    hints = {}
    for platform in set(list(brave_hints.keys()) + list(website_hints.keys())):
        w_hint = website_hints.get(platform) or {}
        b_hint = brave_hints.get(platform) or {}
        w_handle = w_hint.get("handle", "")
        b_handle = b_hint.get("handle", "")
        # Validate website hint — reject if it doesn't overlap brand/product name
        # (skip validation for weight-4 hints: link[rel=me] / JSON-LD sameAs)
        w_weight = w_hint.get("weight", 0)
        w_valid = bool(
            w_handle and (
                w_weight >= 4  # authoritative declaration — trust unconditionally
                or _handle_matches_brand(w_handle, brand, product_name)
            )
        )
        b_valid = bool(b_handle and _handle_matches_brand(b_handle, brand, product_name))
        if w_valid:
            hints[platform] = w_hint
        elif b_valid:
            hints[platform] = b_hint
        # Both invalid → omit (downstream will fall back to direct API lookup)
        if not w_valid and not b_valid and (w_handle or b_handle):
            log.info(
                "social hint rejected for %s: website=%s brave=%s (no brand overlap with '%s'/'%s')",
                platform, w_handle, b_handle, brand, product_name,
            )

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
    results["channels"]["tiktok"]   = {"platform": "TikTok",    "detected": False, "note": _T("🔄 Collecting…", "🔄 采集中…")}
    results["channels"]["facebook"] = {"platform": "Facebook",  "detected": False, "note": _T("🔄 Collecting…", "🔄 采集中…")}

    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    }) as client:
        # Fast channels only (≤20s each) — TikTok/Facebook use Apify and need 45-55s, run separately
        import asyncio as _aio

        # Twitter gets its own 50s timeout to prevent it from blocking other channels
        # (Apify Twitter takes 30-60s per handle, other channels complete in 5-15s)
        async def _twitter_with_timeout():
            try:
                return await _aio.wait_for(
                    _deep_twitter_caravo(brand, product_name, handle_hint=twitter_hint),
                    timeout=20,  # TwitterAPI.io is fast (<3s/handle), 20s is generous
                )
            except _aio.TimeoutError:
                return {"platform": "Twitter/X", "detected": False, "handle": None,
                        "note": _T("Twitter analysis timed out", "Twitter 分析超时")}

        twitter_task   = _twitter_with_timeout()
        youtube_task   = _deep_youtube(client, brand, product_name, handle_hint=youtube_hint, domain=domain)
        reddit_task    = _deep_reddit(client, brand, product_name, domain=domain)
        github_task    = _deep_github(client, brand, product_name, handle_hint=github_hint, domain=domain)
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

        # LinkedIn: resolve the real company slug via Google's index
        # (SerpAPI) instead of guessing linkedin.com/company/{brand}.
        try:
            results["channels"]["linkedin"] = await _aio.wait_for(
                _check_linkedin_search(brand, product_name, domain), timeout=15,
            )
        except Exception:
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
        return {"error": _T("propagation.py not found or failed to import", "propagation.py 未找到或导入失败")}

    brand = social_result.get("brand", "")
    twitter = social_result.get("channels", {}).get("twitter", {})
    top_tweets = twitter.get("top_tweets", [])

    if not top_tweets:
        return {
            "data_mode": "empty",
            "error": _T("Twitter top_tweets is empty — cannot run propagation analysis", "Twitter top_tweets 为空，无法进行传播分析"),
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
_APIFY_PROFILE_ACTOR = "happitap~twitter-profile-scraper"
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
        "handles": [handle],
    }

    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            # Start actor run with waitForFinish
            resp = await client.post(
                f"{api_base}/acts/{actor_id}/runs",
                json=run_input,
                params={"token": token, "waitForFinish": 60},
                timeout=75,
            )
            if resp.status_code not in (200, 201):
                body = resp.text[:200] if resp.text else ""
                return {"success": False, "error": f"Apify HTTP {resp.status_code}: {body}"}

            run_data = resp.json().get("data", {})
            run_id = run_data.get("id")
            run_status = run_data.get("status")

            if not run_id:
                return {"success": False, "error": "Apify run missing id"}

            # Poll if not finished yet
            if run_status not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                import asyncio as _aio_poll
                for _ in range(4):
                    await _aio_poll.sleep(8)
                    sr = await client.get(
                        f"{api_base}/actor-runs/{run_id}",
                        params={"token": token},
                    )
                    if sr.status_code == 200:
                        run_status = sr.json().get("data", {}).get("status")
                        if run_status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                            break

            if run_status != "SUCCEEDED":
                return {"success": False, "error": f"Apify run status: {run_status}"}

            # Fetch dataset items
            ds_resp = await client.get(
                f"{api_base}/actor-runs/{run_id}/dataset/items",
                params={"token": token, "format": "json"},
            )
            if ds_resp.status_code != 200:
                return {"success": False, "error": f"Apify dataset HTTP {ds_resp.status_code}"}

            try:
                items = ds_resp.json()
            except Exception:
                return {"success": False, "error": "Apify non-JSON dataset response"}

            if isinstance(items, dict):
                err = items.get("error", {})
                return {"success": False, "error": f"Apify error: {err.get('message', str(err)[:100])}"}
            if not isinstance(items, list) or not items:
                return {"success": False, "error": "Apify returned empty dataset"}

            # happitap/twitter-profile-scraper returns flat profile objects:
            # {"type": "user", "userName": ..., "name": ..., "bio": ..., "followers": ...}
            # Old apidojo actor returned tweets with nested author fields.
            # Support both formats for backward compatibility.
            first = items[0] if items else {}
            if first.get("type") == "user" or "bio" in first:
                # New happitap format: flat profile object
                profile = {
                    "userName": first.get("userName", handle),
                    "name": first.get("name", ""),
                    "followers": first.get("followers"),
                    "following": first.get("following"),
                    "description": (first.get("bio") or "")[:200],
                    "isBlueVerified": first.get("isBlueVerified", False),
                    "isVerified": first.get("isVerified", False),
                    "verifiedType": first.get("verifiedType", ""),
                    "id": first.get("id", ""),
                    "website": first.get("website", ""),
                }
                tweets = []  # Profile-only actor, no tweets
            else:
                # Old apidojo format: tweets with author field
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
                tweets = []
                for item in items:
                    if item.get("type") not in (None, "tweet"):
                        continue
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
    """深度分析 Twitter — TwitterAPI.io (primary, <3s) → Brave fallback (instant)"""
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
        f"{brand}hq", f"{name_lower}hq",
        f"{brand}official", f"{name_lower}official",  # AFFiNEOfficial pattern
        brand, name_lower,
        # Iris 2026-06-30 bug ga-a0fa2515: Hyperliquid matched @HyperliquidAi
        # instead of official @HyperliquidX because "x" wasn't in this list at
        # all. The "+x" suffix is a common crypto/web3 naming convention
        # (LayerZero → @LayerZero, Aevo → @AevoXYZ, Hyperliquid → @HyperliquidX).
        # Adding it ahead of the AI variant since AI suffix has lower precision
        # in crypto/finance space.
        f"{brand}x", f"{name_lower}x",
        f"{brand}_dev", f"{brand}ai", f"get{brand}", f"{brand}app", f"use{brand}",
    ])
    handles_to_try = list(dict.fromkeys(handles_to_try))

    # ------------------------------------------------------------------
    # Strategy 1: TwitterAPI.io — try handles, validate with bio + website field
    # Collect all valid candidates, pick best by followers count.
    # ------------------------------------------------------------------
    twitterapi_key = os.environ.get("TWITTERAPI_IO_KEY", "").strip()
    # Extract domain for website field cross-validation
    _domain_clean = ""
    try:
        from urllib.parse import urlparse as _urlparse
        # brand comes from domain, reconstruct it
        for _tld in ["com", "io", "dev", "ai", "pro", "co", "app", "so", "xyz"]:
            if f"{brand}.{_tld}" in name.lower() or brand:
                _domain_clean = f"{brand}.{_tld}"
                break
        if not _domain_clean:
            _domain_clean = brand
    except Exception:
        _domain_clean = brand

    # Track API-level errors across all handle probes so we can distinguish
    # "the API is misbehaving" (should surface as a warning) from
    # "the account genuinely doesn't match" (silent skip).
    # NOTE: This list is shared across both the primary enumeration loop AND
    # the brave_find_twitter fallback call (both reuse _check_handle). That
    # means a single transient 429 anywhere makes "api_error" the verdict —
    # intentional: we'd rather over-warn than silently claim Co-Star has no
    # presence when the API was just rate-limited.
    api_errors: list[str] = []

    async def _check_handle(client, handle):
        """Check a single handle via TwitterAPI.io.

        Returns:
            - profile dict: handle validated and matched
            - None:         handle fetched OK but didn't match relevance rules
                            (API status 200, just no signal match)
        Side effect:
            appends an error tag to `api_errors` if the call failed at the
            transport/API layer (429/401/5xx/timeout/etc). Callers should
            check `api_errors` to decide whether a "not found" conclusion
            is trustworthy.
        """
        try:
            resp = await client.get(
                "https://api.twitterapi.io/twitter/user/info",
                headers={"X-API-Key": twitterapi_key},
                params={"userName": handle},
            )
            if resp.status_code in (429, 401, 403):
                api_errors.append(f"http_{resp.status_code}")
                return None
            if resp.status_code >= 500:
                api_errors.append(f"http_{resp.status_code}")
                return None
            if resp.status_code != 200:
                # 404 on a user lookup = handle doesn't exist, that's fine
                return None
            data = resp.json()
            if data.get("status") != "success":
                # Distinguish "handle doesn't exist" (expected, silent skip)
                # from real API problems (log as error so caller can warn).
                msg = (data.get("message") or data.get("msg") or "").lower()
                if "not found" in msg or "not exist" in msg or "no user" in msg:
                    return None  # legitimate miss, not an API issue
                api_errors.append("bad_payload")
                return None
            prof = data.get("data", {})
            if not prof.get("userName"):
                return None

            # --- Multi-signal relevance check ---
            account_bio = (prof.get("description") or "").lower()
            account_name_str = (prof.get("name") or "").lower()
            account_website = (prof.get("url") or "").lower()  # User's website link
            account_handle = (prof.get("userName") or handle or "").lower()
            brand_lower = brand.lower()
            name_lower_check = name.lower()

            # Signal 1: website field contains product domain → strongest match
            website_match = any(d in account_website for d in [
                f"{brand_lower}.com", f"{brand_lower}.io", f"{brand_lower}.dev",
                f"{brand_lower}.ai", f"{brand_lower}.pro", f"{brand_lower}.co",
                f"{brand_lower}.app", f"{brand_lower}.so",
            ] if d)

            # Signal 2: bio mentions brand/product
            # IMPORTANT: Only count bio/name match if it's NOT just the handle
            # itself (tautological). e.g. @spara having display name "Spara"
            # doesn't prove it's the spara.com product account.
            bio_mentions_brand = (
                brand_lower in account_bio
                or name_lower_check in account_bio
            )
            # Display name match only counts if it's more specific than the handle
            # (e.g. display name "Spara AI" for brand "spara" is meaningful,
            #  but display name "Spara" for handle @spara is tautological)
            name_is_meaningful = (
                (brand_lower in account_name_str or name_lower_check in account_name_str)
                and account_name_str != account_handle  # not just the handle echoed
                and len(account_name_str) > len(account_handle) + 1  # has extra context
            )
            bio_match = bio_mentions_brand or name_is_meaningful

            # Signal 3: verified business account → a *booster*, never sole proof.
            # A popular unrelated verified business (e.g. @testingcatalog, an
            # AI-news account) must NOT match just for carrying a Business badge;
            # require the handle or display name to actually relate to the brand.
            is_verified_biz = prof.get("verifiedType") == "Business"
            verified_and_relevant = is_verified_biz and (
                _handle_matches_brand(account_handle, brand, name)
                or _handle_matches_brand(account_name_str, brand, name)
            )

            # Accept if ANY strong signal matches
            if not website_match and not bio_match and not verified_and_relevant:
                return None

            return prof
        except httpx.TimeoutException:
            api_errors.append("timeout")
            return None
        except httpx.HTTPError as e:
            api_errors.append(f"network:{type(e).__name__}")
            return None
        except Exception as e:
            api_errors.append(f"exc:{type(e).__name__}")
            return None

    if twitterapi_key:
        candidates = []
        async with httpx.AsyncClient(timeout=10) as client:
            # Round 1: try enumerated handles (up to 5, <3s each)
            for handle in handles_to_try[:5]:
                prof = await _check_handle(client, handle)
                if prof:
                    candidates.append(prof)

            # Round 2: if no candidates found, use Brave Search to find handle
            if not candidates:
                try:
                    from .web_search import brave_find_twitter
                    brave_handle = await brave_find_twitter(brand, name, domain="")
                    if brave_handle and brave_handle not in [h.lower() for h in handles_to_try[:5]]:
                        prof = await _check_handle(client, brave_handle)
                        if prof:
                            candidates.append(prof)
                except Exception:
                    pass

        # Pick best candidate. The site-declared handle (handle_hint) is ground
        # truth — if it validated, prefer it even when another brand variant has
        # more followers. Otherwise rank by (verified > followers).
        #
        # Iris 2026-06-30: previously the tiebreak was followers-only, so a
        # rogue @HyperliquidAi (1 follower) could win over real @HyperliquidX
        # (410K, Business-verified) if the handles list happened to include AI
        # but not X. Sorting verified-first kills that whole class of bug:
        # an unverified 1-follower account can't beat a verified 100K account
        # regardless of which handle pattern hit first.
        if candidates:
            best = None
            if handle_hint:
                _hint_norm = handle_hint.lstrip("@").lower().replace("_", "")
                best = next(
                    (c for c in candidates
                     if (c.get("userName") or "").lower().replace("_", "") == _hint_norm),
                    None,
                )
            if best is None:
                def _rank(p):
                    return (
                        1 if p.get("verifiedType") == "Business" else 0,
                        1 if p.get("isBlueVerified") else 0,
                        p.get("followers", 0) or 0,
                    )
                best = max(candidates, key=_rank)
            screen_name = best.get("userName", "")
            result["detected"] = True
            result["handle"] = f"@{screen_name}"
            result["url"] = f"https://x.com/{screen_name}"
            result["followers"] = best.get("followers")
            result["following"] = best.get("following")
            result["profile"] = {
                "name": best.get("name", ""),
                "description": (best.get("description") or "")[:200],
                "verified": best.get("isBlueVerified", False),
                "verified_type": best.get("verifiedType", ""),
                "created_at": best.get("createdAt", ""),
                "statuses_count": best.get("statusesCount", 0),
                "listed_count": 0,
            }
            result["note"] = "✅ via TwitterAPI.io"

            # Fetch top tweets for the winning account
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    tw_resp = await client.get(
                        "https://api.twitterapi.io/twitter/user/last_tweets",
                        headers={"X-API-Key": twitterapi_key},
                        params={"userName": screen_name},
                    )
                    if tw_resp.status_code == 200:
                        tw_data = tw_resp.json()
                        tweets = tw_data.get("data", {}).get("tweets", []) if isinstance(tw_data.get("data"), dict) else []
                        for tw in tweets[:10]:
                            result["top_tweets"].append({
                                "text": (tw.get("text") or "")[:200],
                                "likes": tw.get("likeCount", 0),
                                "retweets": tw.get("retweetCount", 0),
                                "replies": tw.get("replyCount", 0),
                                "views": tw.get("viewCount", 0),
                                "bookmarks": tw.get("bookmarkCount", 0),
                                "created_at": tw.get("createdAt", ""),
                            })
                        result["top_tweets"].sort(key=lambda x: x.get("likes", 0), reverse=True)
            except Exception:
                pass

            log.info("Twitter @%s via TwitterAPI.io: %s followers (from %d candidates)",
                     screen_name, best.get("followers"), len(candidates))
            return result

    # ------------------------------------------------------------------
    # Strategy 2: Brave Search fallback (instant, handle + estimated followers)
    # ------------------------------------------------------------------
    if not result["detected"]:
        handle = handle_hint  # site-declared handle is trusted as-is
        if not handle:
            try:
                from .web_search import brave_find_twitter
                brave_handle = await brave_find_twitter(brand, name, domain="")
                # Brave handles are fuzzy and API-unvalidated here — only trust
                # one that plausibly belongs to the brand. Rejects e.g.
                # @gingrnation surfacing for "gingiris".
                if brave_handle and _handle_matches_brand(brave_handle, brand, name):
                    handle = brave_handle
                elif brave_handle:
                    log.info(
                        "Twitter brave handle @%s rejected for brand=%s (no name overlap)",
                        brave_handle, brand,
                    )
            except Exception:
                pass
        if handle:
            followers = await _brave_twitter_followers(handle)
            result["detected"] = True
            result["handle"] = f"@{handle}" if not handle.startswith("@") else handle
            result["url"] = f"https://x.com/{handle.lstrip('@')}"
            result["followers"] = followers
            # If TwitterAPI.io had errors, say so — user should know follower
            # count couldn't be verified against the source of truth.
            if api_errors and not followers:
                result["note"] = _T(f"⚠️ TwitterAPI.io returned an error ({api_errors[0]}); account exists but follower count wasn't fetched. Retry or check api_status",
                                     f"⚠️ TwitterAPI.io 返回错误（{api_errors[0]}），账号存在但粉丝数未抓到。可重试或查看 api_status")
                result["api_status"] = "degraded"
            elif followers:
                result["note"] = _T("Follower count from Brave Search (TwitterAPI.io found no matching account)",
                                     "粉丝数来自 Brave Search（TwitterAPI.io 未找到匹配账号）")
                result["api_status"] = "brave_fallback"
            else:
                result["note"] = _T("Only Brave confirms the account exists", "仅 Brave 确认账号存在")
                result["api_status"] = "partial"
        else:
            tried_str = ", ".join(handles_to_try[:3])
            # Distinguish "API is broken" from "genuinely no account".
            # If every TwitterAPI.io probe errored at the transport/API layer,
            # we can't conclude the account doesn't exist — it might be
            # @costarastrology (1M+ followers) that we just couldn't reach.
            if api_errors and twitterapi_key:
                err_sample = api_errors[0]
                result["note"] = _T(
                    f"⚠️ Could not detect reliably — all TwitterAPI.io requests failed ({err_sample}, "
                    f"{len(api_errors)} times). Most likely API rate-limit/auth issues, "
                    f"not that the account doesn't exist. Retry later or check TWITTERAPI_IO_KEY.",
                    f"⚠️ 未能可靠检测 — TwitterAPI.io 全部请求失败（{err_sample}，"
                    f"共 {len(api_errors)} 次）。大概率是 API 限流/鉴权问题，"
                    f"而非账号不存在。请稍后重试或检查 TWITTERAPI_IO_KEY。"
                )
                result["api_status"] = "api_error"
            else:
                result["note"] = _T(f"No Twitter account found (tried {tried_str})", f"未找到 Twitter 账号（尝试了 {tried_str}）")
                result["api_status"] = "not_found"
        result["key_posts_framework"] = {
            "note": _T("🔍 Needs API top-up or manual input", "🔍 需 API 充值或手动补充"),
            "needed_data": [
                _T("Launch post details (Views/Likes/Retweets/Quotes/Replies/Bookmarks)", "Launch 帖子详情（Views/Likes/Retweets/Quotes/Replies/Bookmarks）"),
                _T("Top 5 most-engaged posts", "最高互动帖子 Top 5"),
                _T("Content-category breakdown", "内容分类统计"),
                _T("Posting frequency & cadence analysis", "发布频次和节奏分析"),
                _T("KOL collaboration post list", "KOL 合作帖子列表"),
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
                
                result["note"] = _T("Official account detected", "检测到官方账号")

                # Framework for key post analysis (needs Twitter API for full data)
                result["key_posts_framework"] = {
                    "note": _T("🔍 Needs Twitter API or manual input for the data below", "🔍 需 Twitter API 或手动补充以下数据"),
                    "needed_data": [
                        _T("Launch post details (Views/Likes/Retweets/Quotes/Replies/Bookmarks)", "Launch 帖子详情（Views/Likes/Retweets/Quotes/Replies/Bookmarks）"),
                        _T("Top 5 most-engaged posts", "最高互动帖子 Top 5"),
                        _T("Content-category breakdown (product updates / case studies / tutorials / hiring / ecosystem)", "内容分类统计（产品更新/用户案例/教程/招聘/生态合作）"),
                        _T("Posting frequency & cadence analysis", "发布频次和节奏分析"),
                        _T("KOL collaboration post list", "KOL 合作帖子列表"),
                    ],
                }
                break
        except Exception:
            continue
    
    if not result["detected"]:
        result["note"] = _T(f"No exact match found (tried {', '.join(handles_to_try[:3])}...) — manual check recommended",
                             f"未找到精确匹配（尝试了 {', '.join(handles_to_try[:3])}...），建议手动确认")
    
    return result


async def _deep_youtube(client: httpx.AsyncClient, brand: str, name: str, handle_hint: str = None, domain: str = "") -> dict:
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
            result["note"] = _T("✅ YouTube channel data fetched via Apify", "✅ 通过 Apify 获取 YouTube 频道数据")
            log.info("YouTube data for @%s fetched via Apify", handle)
            return result

    # Strategy 2: HTML fallback (no subscriber count due to YouTube JS rendering)
    #
    # 2026-06-18 — Iris ran an audit on her own analook.com and found a fake
    # @analook YouTube channel showed up as detected. Root cause: the only
    # validation was "brand string present anywhere in page", but the
    # channel HTML ALWAYS contains the handle text (which IS the brand
    # string when brand=handle), so any unrelated @analook channel passes.
    #
    # Stronger fix: require the channel description / about page to mention
    # the actual product DOMAIN (e.g. "analook.com"), not just the brand
    # word. Or be referenced via handle_hint (authoritative signal from
    # the product's own site). Otherwise the channel is treated as unrelated.
    domain_clean = re.sub(r"^www\.", "", (domain or "").lower())
    for handle in handles:
        try:
            r = await client.get(f"https://www.youtube.com/@{handle}")
            if not (r.status_code == 200 and "This page isn" not in r.text[:1000]):
                continue
            page_lower = r.text[:50000].lower()
            is_hint = handle_hint and handle == handle_hint.lstrip("@")
            # Tier 1 (strongest): handle_hint came from website — trust unconditionally.
            # Tier 2: the channel page mentions the actual product domain.
            # Tier 3: REJECT — brand-only match is too weak when brand==handle.
            domain_in_page = bool(domain_clean) and (domain_clean in page_lower)
            if not is_hint and not domain_in_page:
                log.info(
                    "YouTube HTML @%s rejected: domain %r not found in page (brand-only match insufficient)",
                    handle, domain_clean or "<none>",
                )
                continue
            result["detected"] = True
            result["handle"] = f"@{handle}"
            result["url"] = f"https://www.youtube.com/@{handle}"
            sub_m = re.search(r'"subscriberCountText".*?"([\d,.]+[KMB]?)\s*subscriber', r.text, re.I)
            if sub_m:
                result["subscribers"] = sub_m.group(1)
            result["note"] = (_T("✅ Channel page confirms link to ", "✅ 频道页确认链接到 ") + domain_clean) if domain_in_page else _T("Channel detected (from website claim)", "检测到频道（来自网站声明）")
            return result
        except Exception:
            continue

    result["note"] = _T("No exact match found", "未找到精确匹配")
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


async def _deep_github(client: httpx.AsyncClient, brand: str, name: str, handle_hint: str = None, domain: str = "") -> dict:
    """深度 GitHub 分析 — with relevance validation to prevent false positives.

    After finding a candidate org/user, validates it's actually related to the
    product by checking the blog/website field, bio/description, and org name
    against the target domain and brand.
    """
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

    # Clean domain for matching (strip www. and TLD)
    domain_clean = re.sub(r'^www\.', '', (domain or brand).lower())
    domain_base = re.sub(r'\.[a-z]{2,6}$', '', domain_clean)  # e.g. "spara"
    domain_variants = [domain_clean]  # e.g. ["spara.com"]
    for tld in ["com", "io", "dev", "ai", "pro", "co", "app", "so"]:
        domain_variants.append(f"{domain_base}.{tld}")

    def _is_relevant(data: dict) -> bool:
        """Check if a GitHub org/user is actually related to the target product."""
        blog = (data.get("blog") or "").lower().strip().rstrip("/")
        bio = (data.get("bio") or data.get("description") or "").lower()
        display_name = (data.get("name") or "").lower()
        company = (data.get("company") or "").lower()

        # Signal 1: blog/website field contains product domain (strongest)
        if blog:
            for dv in domain_variants:
                if dv in blog:
                    return True

        # Signal 2: bio/description mentions brand or product name
        brand_lower = brand.lower()
        name_lower_check = name.lower()
        if brand_lower in bio or name_lower_check in bio:
            return True
        if brand_lower in display_name or name_lower_check in display_name:
            return True

        # Signal 3: company field references the brand
        if brand_lower in company or name_lower_check in company:
            return True

        # Signal 4: it's an org (orgs are more likely to be the product itself)
        # and the login matches the brand exactly (strong implicit signal)
        login = (data.get("login") or "").lower()
        if data.get("type") == "Organization" and login == brand_lower:
            return True

        # Signal 5: handle was explicitly provided by website social_links or Brave
        # (handle_hint means external evidence pointed to this account)
        if handle_hint and login == handle_hint.lower().strip("/").split("/")[-1]:
            return True

        return False

    name_lower = name.lower().replace(" ", "")
    names_to_try = []
    if handle_hint:
        names_to_try.append(handle_hint)
    names_to_try.extend([f"{brand}hq", f"{name_lower}hq", brand, name_lower, f"{brand}-org"])
    names_to_try = list(dict.fromkeys(names_to_try))

    data = None
    matched_name = None

    def _candidate_rank(c: dict) -> tuple:
        """Rank GitHub candidates: domain-matching blog beats follower count.

        Iris 2026-07-06 accuracy audit: Notion matched org `notionhq`
        (7 followers, no blog) because the loop broke on FIRST relevant hit.
        The real org `makenotion` (2,925 followers, blog=notion.so) was never
        tried. Collect all candidates and rank: blog-matches-domain is the
        strongest ownership signal, then followers as tiebreak.
        """
        blog = (c.get("blog") or "").lower().strip().rstrip("/")
        blog_match = any(dv in blog for dv in domain_variants) if blog else False
        return (1 if blog_match else 0, c.get("followers", 0) or 0)

    try:
        # Try all name variants, collect ALL relevant candidates, rank at end
        candidates_gh = []
        for alt in names_to_try:
            for endpoint in ["orgs", "users"]:
                try:
                    r = await client.get(f"https://api.github.com/{endpoint}/{alt}")
                    if r.status_code == 200:
                        candidate = r.json()
                        if _is_relevant(candidate):
                            candidate["_matched_name"] = alt
                            candidate["_endpoint"] = endpoint
                            candidates_gh.append(candidate)
                            break  # org and user for same name can't both exist
                except Exception:
                    pass

        # Widen the pool via GitHub org search. Iris 2026-07-06 self-test:
        # Notion's real org is `makenotion` — no enumerable pattern reaches
        # it, so the wrong `notion` user (63 stars) won by default. Search
        # surfaces naming schemes we can't guess; _is_relevant + blog-match
        # ranking still gate what actually gets picked.
        try:
            sr = await client.get(
                "https://api.github.com/search/users",
                params={"q": f"{brand} type:org", "per_page": 3},
            )
            if sr.status_code == 200:
                seen_logins = {(c.get("login") or "").lower() for c in candidates_gh}
                for item in sr.json().get("items", []):
                    login = (item.get("login") or "")
                    if not login or login.lower() in seen_logins:
                        continue
                    pr = await client.get(f"https://api.github.com/users/{login}")
                    if pr.status_code != 200:
                        continue
                    candidate = pr.json()
                    if _is_relevant(candidate):
                        candidate["_matched_name"] = login
                        candidate["_endpoint"] = (
                            "orgs" if candidate.get("type") == "Organization" else "users"
                        )
                        candidates_gh.append(candidate)
        except Exception:
            pass

        if candidates_gh:
            data = max(candidates_gh, key=_candidate_rank)
            matched_name = data["_matched_name"]
            result["type"] = "organization" if data["_endpoint"] == "orgs" else "user"

        if data:
            result["detected"] = True
            result["url"] = data.get("html_url", "")
            result["public_repos"] = data.get("public_repos", 0)
            result["followers"] = data.get("followers", 0)

            # Get top repos.
            #
            # Iris 2026-07-06 accuracy audit: `?sort=stars` is NOT a valid
            # value for GitHub's list-repos API (valid: created/updated/
            # pushed/full_name) — it was silently ignored, returning the 5
            # OLDEST repos by creation date. For rustfs this reported
            # stars_total=446 while the flagship rustfs/rustfs repo alone
            # has 29,483 stars. Fix: pull up to 100 repos in one call and
            # sort client-side by stargazers_count.
            endpoint_type = 'orgs' if result['type'] == 'organization' else 'users'
            repos_resp = await client.get(
                f"https://api.github.com/{endpoint_type}/{matched_name}/repos?per_page=100"
            )
            if repos_resp.status_code == 200:
                repos = sorted(
                    repos_resp.json(),
                    key=lambda r: r.get("stargazers_count", 0) or 0,
                    reverse=True,
                )
                total_stars = sum(r.get("stargazers_count", 0) or 0 for r in repos)
                for r in repos[:5]:
                    result["top_repos"].append({
                        "name": r.get("name", ""),
                        "stars": r.get("stargazers_count", 0),
                        "language": r.get("language", ""),
                        "description": (r.get("description") or "")[:80],
                    })
                result["stars_total"] = total_stars
        else:
            tried_str = ", ".join(names_to_try[:3])
            result["note"] = _T(f"No exact match found (tried {tried_str}…)", f"未找到精确匹配（尝试了 {tried_str}…）")

    except Exception as e:
        result["note"] = f"Error: {str(e)[:100]}"

    return result


def _check_linkedin(brand: str) -> dict:
    """Legacy guess-URL fallback — kept for when SerpAPI is unavailable."""
    return {
        "platform": "LinkedIn",
        "detected": None,
        "url": f"https://www.linkedin.com/company/{brand}",
        "note": _T("🔍 LinkedIn requires login to verify — manual check recommended", "🔍 LinkedIn 需登录验证，建议手动检查"),
    }


async def _check_linkedin_search(brand: str, name: str, domain: str = "") -> dict:
    """Find the company's LinkedIn page via Google's index (SerpAPI).

    Iris 2026-07-06 accuracy audit: the old _check_linkedin just GUESSED
    linkedin.com/company/{brand} and told the user to verify manually.
    LinkedIn blocks anonymous scraping, but Google indexes the real
    company pages — searching site:linkedin.com/company gives us the
    canonical slug that actually exists, which is a big precision jump
    over string-guessing. Still marked "via Google index" because we
    can't read follower counts without auth.
    """
    key = (os.environ.get("SERPAPI_KEY") or "").strip()
    if not key:
        return _check_linkedin(brand)
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google",
                    "q": f'site:linkedin.com/company "{name}"',
                    "num": 5,
                    "api_key": key,
                },
            )
            if r.status_code != 200:
                return _check_linkedin(brand)
            results = r.json().get("organic_results", []) or []
        brand_l = brand.lower()
        name_l = name.lower()
        for res in results:
            link = (res.get("link") or "").split("?")[0].rstrip("/")
            if "/company/" not in link:
                continue
            slug = link.split("/company/")[-1].lower()
            title = (res.get("title") or "").lower()
            # Relevance: slug or result title must relate to the brand
            if brand_l in slug or name_l in slug.replace("-", "") \
               or brand_l in title or name_l in title:
                return {
                    "platform": "LinkedIn",
                    "detected": True,
                    "url": link,
                    "handle": slug,
                    "note": _T(f"✅ Confirmed via Google index (title: {(res.get('title') or '')[:60]})", f"✅ 经 Google 索引确认（标题: {(res.get('title') or '')[:60]}）"),
                }
        # Indexed pages exist but none match the brand → likely no LinkedIn
        if results:
            return {
                "platform": "LinkedIn",
                "detected": False,
                "url": None,
                "note": _T("No LinkedIn company page matching this brand found in the Google index", "Google 索引中未找到匹配该品牌的 LinkedIn 公司页"),
            }
    except Exception as e:
        log.warning("LinkedIn SerpAPI lookup failed: %s", str(e)[:80])
    return _check_linkedin(brand)


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
        # detected=False means we couldn't verify the account — leave url=None
        # so the renderer doesn't link to a guessed URL that may belong to a
        # totally unrelated TikTok user. Iris 2026-06-18: TikTok page on
        # analook report linked to @analook but note said "not found".
        result["note"] = _T("⚠️ APIFY_API_TOKEN not configured", "⚠️ 未配置 APIFY_API_TOKEN")
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
        result["note"] = _T("✅ TikTok account data fetched via Apify", "✅ 通过 Apify 获取 TikTok 账号数据")
        log.info("TikTok data for @%s fetched via Apify", uid)
        return result

    # No verified match — leave url=None so the share page doesn't link
    # to a guessed URL. Iris 2026-06-18 false-positive fix.
    result["note"] = _T(f"No matching TikTok account found (tried {', '.join(handles[:3])})", f"未找到匹配 TikTok 账号（尝试了 {', '.join(handles[:3])}）")
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
        # detected=False → leave url=None (no guessed URL)
        result["note"] = _T("⚠️ APIFY_API_TOKEN not configured", "⚠️ 未配置 APIFY_API_TOKEN")
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
        result["note"] = _T("✅ Facebook page data fetched via Apify", "✅ 通过 Apify 获取 Facebook 页面数据")
        log.info("Facebook data for %s fetched via Apify", handle)
        return result

    # No verified match — leave url=None (Iris 2026-06-18 false-positive fix)
    result["note"] = _T(f"No matching Facebook page found (tried {', '.join(handles[:2])})", f"未找到匹配 Facebook 页面（尝试了 {', '.join(handles[:2])}）")
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
                    result["note"] = _T("⚠️ Caravo balance insufficient — Instagram data not collected", "⚠️ Caravo 余额不足，Instagram 数据未采集")
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
        result["note"] = _T(f"Instagram not found via Caravo API (tried {', '.join(handles_to_try[:3])}...)", f"未通过 Caravo API 找到 Instagram（尝试了 {', '.join(handles_to_try[:3])}...）")
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
    result["note"] = _T("✅ Account data fetched via Caravo Instagram API", "✅ 通过 Caravo Instagram API 获取到账号数据")

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
        metrics["note"] = _T("⚠️ Could not auto-collect social media data. Manual input recommended.", "⚠️ 未能自动采集到社交媒体数据。建议手动补充。")
    else:
        missing = []
        if not twitter.get("detected"):  missing.append("Twitter/X")
        if not youtube.get("detected"):  missing.append("YouTube")
        if not tiktok.get("detected"):   missing.append("TikTok")
        if not facebook.get("detected"): missing.append("Facebook")
        missing.append("LinkedIn")
        metrics["note"] = _T(f"📊 Collected: {', '.join(metrics['data_sources'])}.", f"📊 已采集: {', '.join(metrics['data_sources'])}。") + (_T(f" Not collected: {', '.join(missing)}.", f" 未采集: {', '.join(missing)}。") if missing else "")
    
    return metrics
