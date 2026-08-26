"""Product Hunt API 集成模块"""
import httpx
import os
import re
import json
import logging

from .i18n import _T
from .posthog_track import track_data_source, timeit

PH_API = "https://api.producthunt.com/v2/api/graphql"
PH_PRODUCT_URL = "https://www.producthunt.com/products/{slug}"

log = logging.getLogger(__name__)


def _get_token() -> str:
    token = os.environ.get("PRODUCTHUNT_TOKEN", "").strip()
    if token:
        return token
    for p in ["~/.cola/secrets/producthunt_dev_token", "~/.cola/secrets/producthunt_token"]:
        try:
            return open(os.path.expanduser(p)).read().strip()
        except FileNotFoundError:
            continue
    return ""


def _extract_brand(domain: str) -> str:
    """Extract brand name from domain, stripping www. and all common TLDs."""
    brand = domain.lower().strip()
    brand = re.sub(r'^www\.', '', brand)
    # Strip TLD (handles .com, .io, .dev, .ai, .co, .pro, .app, .xyz, .so, .org, .net, etc.)
    brand = re.sub(r'\.[a-z]{2,6}$', '', brand)
    return brand


def _domain_root(host: str) -> str:
    """Normalize a URL or host to its bare host (no scheme, www, path or query)."""
    host = (host or "").lower().strip()
    host = re.sub(r'^https?://', '', host)
    host = re.split(r'[/?#]', host)[0]
    host = re.sub(r'^www\.', '', host)
    return host


def _verify_match(hit: dict, domain: str, brand: str, product_name: str) -> bool:
    """Guard against fuzzy false positives.

    Discovery happens through Brave search + slug enumeration, which can surface
    an unrelated product that merely *looks* similar (e.g. querying "gingiris"
    returned "Genpire"). Before trusting a hit, require it to actually correspond
    to the queried site — either by its registered website domain OR by product
    name. A hit that matches neither is rejected as a false positive.
    """
    def _norm(s: str) -> str:
        return re.sub(r'[^a-z0-9]', '', (s or '').lower())

    # 1) Website-domain match (strongest signal) ------------------------------
    site = _domain_root(hit.get("website", ""))
    target = _domain_root(domain)
    if site and target:
        if site == target or site.endswith("." + target) or target.endswith("." + site):
            return True
        # Same brand under a different TLD (foo.com vs foo.io)
        site_brand = _extract_brand(site)
        if site_brand and site_brand == _extract_brand(target):
            return True

    # 2) Product-name match ---------------------------------------------------
    n_hit = _norm(hit.get("name", ""))
    n_brand = _norm(brand)
    n_prod = _norm(product_name)
    if n_hit:
        if n_hit in (n_brand, n_prod):
            return True
        # versioned / suffixed names: "Notion 2.0" ⊇ "notion", "ChatGPT-4" ⊇ "chatgpt"
        if (n_brand and n_brand in n_hit) or (n_prod and n_prod in n_hit):
            return True
        # PH name is a prefix of the brand (rare, e.g. brand carries a suffix)
        if n_brand and n_hit in n_brand and len(n_hit) >= 4:
            return True

    return False


async def _discover_launches_via_http(product_slug: str, client: httpx.AsyncClient) -> list:
    """
    Fetch the PH product page over plain HTTP and extract launch slugs from the HTML.
    PH uses SSR so launch links are usually present without JS rendering.
    Returns a list of launch slug strings, or [] on failure.
    """
    url = PH_PRODUCT_URL.format(slug=product_slug)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = await client.get(url, headers=headers, follow_redirects=True, timeout=15)
        if resp.status_code != 200:
            log.debug("PH product page HTTP %s for slug=%s", resp.status_code, product_slug)
            return []
        html = resp.text
        # Extract launch slugs from /products/{slug}/launches/{launchSlug}
        pattern = re.compile(
            r'/products/' + re.escape(product_slug) + r'/launches/([A-Za-z0-9_-]+)',
            re.IGNORECASE,
        )
        slugs = list(dict.fromkeys(pattern.findall(html)))
        log.debug("HTTP discovery found %d launch slugs for %s", len(slugs), product_slug)
        return slugs
    except Exception as exc:
        log.debug("HTTP discovery failed for %s: %s", product_slug, exc)
        return []


async def _discover_launches_via_api(
    product_slug: str, brand: str, client: httpx.AsyncClient, headers: dict,
) -> list:
    """
    Use PH GraphQL API to discover post slugs belonging to this product.
    Strategy: query posts by website URL variants, then deduplicate.
    """
    launch_slugs: list[str] = []

    # Query by multiple website URL variants to find all related posts
    url_variants = [
        f"https://{brand}.com", f"https://{brand}.io", f"https://{brand}.ai",
        f"https://{brand}.pro", f"https://{brand}.dev", f"https://{brand}.co",
        f"https://{brand}.app", f"https://{brand}.so", f"https://{brand}.org",
        f"https://www.{brand}.com", f"https://www.{brand}.pro",
        f"https://get{brand}.com", f"https://use{brand}.com",
    ]
    query = """query($url: String!) {
        posts(url: $url, first: 10, order: VOTES) {
            edges { node { slug url } }
        }
    }"""
    for url_var in url_variants:
        try:
            resp = await client.post(
                PH_API, headers=headers,
                json={"query": query, "variables": {"url": url_var}},
            )
            data = resp.json()
            edges = (data.get("data") or {}).get("posts", {}).get("edges", [])
            for edge in edges:
                s = edge.get("node", {}).get("slug", "")
                if s and s not in launch_slugs:
                    launch_slugs.append(s)
        except Exception:
            continue

    log.debug("API discovery found %d launch slugs for brand=%s", len(launch_slugs), brand)
    return launch_slugs


async def analyze_producthunt(domain: str, product_name: str) -> dict:
    """查询产品在 Product Hunt 上的表现。

    Thin wrapper around the discovery implementation that applies a final
    correctness gate: any matched product must actually correspond to the
    queried domain/brand (see ``_verify_match``). This prevents fuzzy
    discovery from confidently attributing an unrelated launch (e.g. showing
    "Genpire" for gingiris.tools) to the site under analysis.
    """
    result = await _analyze_producthunt_impl(domain, product_name)
    if result.get("found"):
        brand = _extract_brand(domain)
        if not _verify_match(result, domain, brand, product_name):
            log.info(
                "PH match rejected for %s: '%s' (%s) matches neither domain nor name",
                domain, result.get("name"), result.get("website"),
            )
            return {
                "found": False,
                "rejected_match": {
                    "name": result.get("name"),
                    "url": result.get("url"),
                    "website": result.get("website"),
                },
                "note": _T(
                    "No product matching this domain/brand was found on Product Hunt "
                    "(filtered out a likely mismatch whose name and domain both differed). "
                    "Manual search: producthunt.com/search?q=" + brand,
                    "未在 Product Hunt 上找到与该域名/品牌匹配的产品"
                    "（已过滤一个名称与域名都不匹配的疑似误匹配结果）。"
                    "可手动搜索：producthunt.com/search?q=" + brand
                ),
            }
    return result


async def _analyze_producthunt_impl(domain: str, product_name: str) -> dict:
    """查询产品在 Product Hunt 上的表现（discovery only — see analyze_producthunt）"""
    brand = _extract_brand(domain)
    name_slug = product_name.lower().replace(" ", "-")

    # ── Step 0: Use Brave Search to find candidate PH slugs (fuzzy, multi) ──
    try:
        from .web_search import brave_find_ph_slugs
    except ImportError:
        try:
            from web_search import brave_find_ph_slugs
        except ImportError:
            brave_find_ph_slugs = None

    brave_slugs: list = []
    if brave_find_ph_slugs:
        try:
            brave_slugs = await brave_find_ph_slugs(brand, product_name, domain=domain, limit=5)
            log.debug("Brave found PH slugs: %s for %s", brave_slugs, brand)
        except Exception:
            brave_slugs = []
    brave_slug = brave_slugs[0] if brave_slugs else None

    token = _get_token()
    if not token:
        return {"found": False, "error": "No PH token"}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Build expanded URL variants for fuzzy match: strip/add www,
    # strip subdomain, try http scheme. Covers PH posts that registered
    # with a slightly different URL (subdomain, http, trailing slash).
    _domain_bare = domain[4:] if domain.startswith("www.") else domain
    # Known two-level TLDs where the "root" would be a public suffix
    # (e.g. co.uk → https://co.uk). Skip root-extraction for those.
    _TWO_LEVEL_TLDS = {"co.uk", "co.jp", "com.au", "com.br", "com.cn", "com.mx",
                       "com.tw", "co.nz", "co.in", "co.za", "co.kr", "com.sg"}
    _parts = _domain_bare.split(".")
    _root_candidate = None
    if len(_parts) >= 3:
        _tail2 = ".".join(_parts[-2:])
        if _tail2 in _TWO_LEVEL_TLDS:
            # e.g. foo.co.uk → foo.co.uk (already root, skip)
            _root_candidate = None if len(_parts) == 3 else ".".join(_parts[-3:])
        else:
            _root_candidate = _tail2
    url_variants = list(dict.fromkeys(filter(None, [
        f"https://{domain}",
        f"https://www.{_domain_bare}",
        f"https://{_domain_bare}",
        f"http://{_domain_bare}",
        f"https://{_root_candidate}" if _root_candidate else None,
    ])))

    async with httpx.AsyncClient(timeout=30) as client:
        # ── Step 0: URL-based search FIRST (most reliable for exact domain match) ──
        for url_variant in url_variants:
            try:
                result = await _query_by_url(client, headers, url_variant)
                if result.get("found"):
                    return result
            except Exception:
                pass

        # ── Step 1: Use API to find at least one post and extract product_slug ──
        product_slug = None
        seed_hit = None

        # Core slugs first (most likely), then version/variant slugs.
        # brave_slugs (multi) go first — widest net for fuzzy matches like
        # "chatgpt" → "chatgpt-4", or brand-name mismatches.
        core_slugs = list(dict.fromkeys(filter(None, [
            *brave_slugs, brand, name_slug,
            f"{brand}-2", f"{brand}-2-0", f"{brand}-ai",
        ])))
        variant_slugs = list(dict.fromkeys(filter(None, [
            f"{brand}-3", f"{brand}-3-0", f"{brand}-4", f"{brand}-4-0",
            f"{brand}-ai-2", f"{brand}-open-source", f"get-{brand}",
        ])))

        all_hits = []
        # Query core slugs in parallel for speed
        import asyncio as _aio2
        core_tasks = [_query_post(client, headers, s) for s in core_slugs]
        core_results = await _aio2.gather(*core_tasks, return_exceptions=True)
        for i, r in enumerate(core_results):
            if isinstance(r, dict) and r.get("found"):
                all_hits.append(r)
                if seed_hit is None:
                    seed_hit = r
                    m = re.search(r'/products/([^/]+)/', r.get("url", ""))
                    if m:
                        product_slug = m.group(1).lower()

        # If core didn't find enough, try variants (also parallel)
        if len(all_hits) < 2:
            var_tasks = [_query_post(client, headers, s) for s in variant_slugs]
            var_results = await _aio2.gather(*var_tasks, return_exceptions=True)
            for r in var_results:
                if isinstance(r, dict) and r.get("found"):
                    all_hits.append(r)

        # If we found launches via slug, filter to the correct product
        if all_hits:
            if not product_slug:
                product_slug = brave_slug or brand
            # Multiple products may share the same name (e.g., "Notion" smart sensors
            # vs "Notion" note-taking app). Group by PH product slug and pick the
            # group with the highest total votes — that's the real product.
            name_lower = product_name.lower()
            # Use startswith to match versioned names: "Notion 2.0" starts with "Notion"
            name_matched = [h for h in all_hits
                            if h.get("name", "").lower() == name_lower
                            or h.get("name", "").lower().startswith(name_lower + " ")]
            if name_matched and len(name_matched) > 1:
                # Group by PH product slug, pick group with most total votes
                from collections import defaultdict
                groups = defaultdict(list)
                for h in name_matched:
                    ps = ""
                    m = re.search(r'/products/([^/]+)/', h.get("url", ""))
                    if m:
                        ps = m.group(1).lower()
                    groups[ps or h.get("slug", "")].append(h)
                best_group = max(groups.values(), key=lambda g: sum(h.get("votes", 0) for h in g))
                return _build_result(best_group, product_slug, brand, product_name)
            elif name_matched:
                best = name_matched[0]
                if best.get("votes", 0) >= 10:
                    return _build_result(name_matched, product_slug, brand, product_name)
            # No reliable name match — fall through

        # If API gave nothing, use brave_slug or brand as product_slug
        if not product_slug:
            product_slug = brave_slug or brand

        # ── Step 2: HTTP scrape only (skip slow _discover_launches_via_api) ──
        import asyncio as _aio
        http_slugs_result = await _discover_launches_via_http(product_slug, client)
        launch_slugs = http_slugs_result if isinstance(http_slugs_result, list) else []

        # Also try URL-based search with just the actual domain (fast, 2 calls)
        for url_variant in [f"https://{domain}", f"https://www.{domain}"]:
            try:
                result = await _query_by_url(client, headers, url_variant)
                if result.get("found"):
                    return result
            except Exception:
                pass

        if product_slug and product_slug not in launch_slugs:
            launch_slugs.insert(0, product_slug)
        launch_slugs = list(dict.fromkeys(launch_slugs))

        if launch_slugs:
            # ── Step 3: Query API for each launch slug ──
            for ls in launch_slugs:
                hit = await _query_post(client, headers, ls)
                if hit.get("found"):
                    all_hits.append(hit)

            if seed_hit and seed_hit.get("found"):
                existing_slugs = {h.get("slug") for h in all_hits}
                if seed_hit.get("slug") not in existing_slugs:
                    all_hits.append(seed_hit)

            if all_hits:
                return _build_result(all_hits, product_slug, brand, product_name)

        # ── Step 4: Fallback — original slug enumeration logic ──
        all_hits = []
        slugs = _build_slug_list(brand, name_slug)

        for slug in slugs:
            hit = await _query_post(client, headers, slug)
            if hit.get("found"):
                all_hits.append(hit)

        if all_hits:
            return _build_result(all_hits, product_slug, brand, product_name)

        # Try by URL
        for url_variant in [f"https://{domain}", f"https://www.{domain}"]:
            result = await _query_by_url(client, headers, url_variant)
            if result.get("found"):
                return result

        # Fallback: domain variant search
        result = await _search_posts(client, headers, product_name, brand)
        if result.get("found"):
            return result

        # Final fuzzy fallback: probe every brave-discovered slug individually
        # (covers cases where brave found "foo-launch-2024" but our slug
        # enumeration never generated it).
        for bs in brave_slugs:
            hit = await _query_post(client, headers, bs)
            if hit.get("found"):
                return _build_result([hit], bs, brand, product_name)

    return {
        "found": False,
        "slugs_tried": [brand, name_slug, *brave_slugs],
        "note": _T("This product was not found on Product Hunt. Manual search: producthunt.com/search?q=" + brand,
                   "未在 Product Hunt 上找到该产品。可手动搜索：producthunt.com/search?q=" + brand) + ""
    }


def _build_slug_list(brand: str, name_slug: str) -> list:
    """Build the full fallback slug enumeration list.

    Covers common PH slug patterns:
      base, base-ai, base-2..base-10, base-{tld}, get-/use- prefixes,
      and stripped-hyphen variants (e.g. "notion-ai" -> "notionai").
    """
    base_names = list(dict.fromkeys([brand, name_slug]))
    slugs = []
    for base in base_names:
        slugs.append(base)
    for base in base_names:
        slugs.append(f"{base}-ai")
    # Numeric suffixes — PH appends -2, -3 … for repeated launches
    for suffix in range(2, 11):
        for base in base_names:
            slugs.append(f"{base}-{suffix}")
    # Version-style slugs: notion-2-0, notion-3-0 (common for major product updates)
    for major in range(2, 6):
        for base in base_names:
            slugs.append(f"{base}-{major}-0")
    # AI-specific: notion-ai-2, notion-ai-3
    for base in base_names:
        slugs.extend([f"{base}-ai-2", f"{base}-ai-3"])
    for base in base_names:
        for variant in ["dev", "app", "io", "pro", "hq", "so", "xyz", "co"]:
            slugs.append(f"{base}-{variant}")
    for base in base_names:
        slugs.extend([f"get-{base}", f"use-{base}", f"try-{base}", f"hey-{base}"])
    # Hyphen-stripped variants: "my-tool" -> "mytool"
    for base in base_names:
        no_hyphen = base.replace("-", "")
        if no_hyphen != base:
            slugs.append(no_hyphen)
    return list(dict.fromkeys(slugs))


def _build_result(all_hits: list, product_slug: str, brand: str, product_name: str) -> dict:
    """Filter hits to the correct product group, sort by votes, return structured result."""
    def _extract_product_slug(hit):
        ph_url = hit.get("url", "")
        m = re.search(r'/products/([^/]+)/', ph_url)
        return m.group(1).lower() if m else ""

    # Group hits by PH product slug
    product_groups: dict = {}
    for hit in all_hits:
        ps = _extract_product_slug(hit)
        if ps:
            product_groups.setdefault(ps, []).append(hit)
        else:
            product_groups.setdefault("_unknown", []).append(hit)

    # Pick the best group — always prefer highest total votes when multiple groups exist
    # (e.g., "notion" 76 votes vs "notion-2" 2027 votes — pick the bigger one)
    best_group = max(product_groups.values(), key=lambda g: sum(h.get("votes", 0) for h in g))

    # Sort by votes descending
    best_group_sorted = sorted(best_group, key=lambda r: r.get("votes", 0), reverse=True)
    best = best_group_sorted[0]
    others = best_group_sorted[1:]

    if others:
        best["other_launches"] = [
            {
                "name": r["name"],
                "slug": r["slug"],
                "votes": r["votes"],
                "launch_date": r.get("launch_date", ""),
                "url": r.get("url", ""),
                "tagline": r.get("tagline", ""),
            }
            for r in others
        ]

    return best


async def _query_post(client, headers, slug) -> dict:
    elapsed = timeit()
    success = False
    query = """query($slug: String!) {
        post(slug: $slug) {
            id name tagline description votesCount commentsCount
            createdAt featuredAt url website slug
            reviewsCount reviewsRating
            topics(first: 5) { edges { node { name slug } } }
            makers { name username headline }
        }
    }"""
    try:
        resp = await client.post(PH_API, headers=headers, json={"query": query, "variables": {"slug": slug}})
        data = resp.json()
        # Handle rate limiting
        if data.get("errors"):
            err = data["errors"][0]
            if err.get("error") == "rate_limit_reached":
                import asyncio
                reset_in = err.get("details", {}).get("reset_in", 60)
                await asyncio.sleep(min(reset_in + 1, 30))
                resp = await client.post(PH_API, headers=headers, json={"query": query, "variables": {"slug": slug}})
                data = resp.json()
        post = (data.get("data") or {}).get("post")
        if not post:
            return {"found": False}
        success = True
        return _format_post(post)
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}
    finally:
        track_data_source("ProductHunt", "_query_post", elapsed(), success, {"slug": slug})


async def _query_by_url(client, headers, url) -> dict:
    elapsed = timeit()
    success = False
    query = """query($url: String!) {
        posts(url: $url, first: 3, order: VOTES) {
            edges { node {
                id name tagline votesCount commentsCount
                createdAt featuredAt url website slug
                reviewsCount reviewsRating
                topics(first: 5) { edges { node { name slug } } }
                makers { name username headline }
            } }
        }
    }"""
    try:
        resp = await client.post(PH_API, headers=headers, json={"query": query, "variables": {"url": url}})
        data = resp.json()
        edges = data.get("data", {}).get("posts", {}).get("edges", [])
        if not edges:
            return {"found": False}
        success = True
        return _format_post(edges[0]["node"])
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}
    finally:
        track_data_source("ProductHunt", "_query_by_url", elapsed(), success, {"url": url})


async def _search_posts(client, headers, product_name, brand) -> dict:
    """Fallback: try domain variants to find the post."""
    domain_variants = [
        f"https://{brand}.pro", f"https://{brand}.com", f"https://{brand}.io",
        f"https://{brand}.ai", f"https://{brand}.dev", f"https://{brand}.co",
        f"https://www.{brand}.com", f"https://www.{brand}.pro",
        f"https://get{brand}.com", f"https://use{brand}.com",
    ]
    for url in domain_variants:
        result = await _query_by_url(client, headers, url)
        if result.get("found"):
            return result

    return {"found": False}


def _format_post(post: dict) -> dict:
    topics = [t["node"]["name"] for t in post.get("topics", {}).get("edges", [])]
    makers = [
        {"name": m.get("name", ""), "username": m.get("username", ""), "headline": m.get("headline", "")}
        for m in post.get("makers", [])
    ]
    return {
        "found": True,
        "name": post.get("name", ""),
        "tagline": post.get("tagline", ""),
        "description": (post.get("description") or "")[:300],
        "votes": post.get("votesCount", 0),
        "comments": post.get("commentsCount", 0),
        "launch_date": post.get("createdAt", "")[:10],
        "featured_date": (post.get("featuredAt") or "")[:10],
        "url": post.get("url", ""),
        "website": post.get("website", ""),
        "slug": post.get("slug", ""),
        "reviews_count": post.get("reviewsCount", 0),
        "reviews_rating": post.get("reviewsRating", 0),
        "topics": topics,
        "makers": makers,
    }
