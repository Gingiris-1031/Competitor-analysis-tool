"""Product Hunt API 集成模块"""
import httpx
import os
import re
import json
import logging

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
    """查询产品在 Product Hunt 上的表现"""
    brand = _extract_brand(domain)
    name_slug = product_name.lower().replace(" ", "-")

    # ── Step 0: Use Brave Search to find the canonical PH slug ──
    try:
        from .web_search import brave_find_ph_slug
    except ImportError:
        try:
            from web_search import brave_find_ph_slug
        except ImportError:
            brave_find_ph_slug = None

    brave_slug = None
    if brave_find_ph_slug:
        try:
            brave_slug = await brave_find_ph_slug(brand, product_name)
            log.debug("Brave found PH slug: %s for %s", brave_slug, brand)
        except Exception:
            pass

    token = _get_token()
    if not token:
        return {"found": False, "error": "No PH token"}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=15) as client:
        # ── Step 1: Use API to find at least one post and extract product_slug ──
        product_slug = None
        seed_hit = None

        # Brave slug gets tried first — it's the most reliable pointer
        seed_slugs = list(dict.fromkeys(filter(None, [brave_slug, brand, name_slug])))

        for slug in seed_slugs:
            hit = await _query_post(client, headers, slug)
            if hit.get("found"):
                seed_hit = hit
                # Extract product_slug from PH url  e.g. /products/lovable/launches/lovable
                m = re.search(r'/products/([^/]+)/', hit.get("url", ""))
                if m:
                    product_slug = m.group(1).lower()
                break

        # If API gave nothing, use brave_slug or brand as product_slug
        if not product_slug:
            product_slug = brave_slug or brand

        # ── Step 2: Discover all launch slugs via HTTP scrape + API in parallel ──
        import asyncio as _aio
        http_slugs_task = _discover_launches_via_http(product_slug, client)
        api_slugs_task = _discover_launches_via_api(product_slug, brand, client, headers)
        http_slugs_result, api_slugs_result = await _aio.gather(
            http_slugs_task, api_slugs_task, return_exceptions=True,
        )
        launch_slugs = http_slugs_result if isinstance(http_slugs_result, list) else []
        api_slugs = api_slugs_result if isinstance(api_slugs_result, list) else []
        # Merge: HTTP results first, then API results, deduped
        for s in api_slugs:
            if s not in launch_slugs:
                launch_slugs.append(s)

        # Also add the product_slug itself (sometimes the post slug == product slug)
        if product_slug not in launch_slugs:
            launch_slugs.insert(0, product_slug)
        # And deduplicate
        launch_slugs = list(dict.fromkeys(launch_slugs))

        if launch_slugs:
            # ── Step 3: Query API for each launch slug ──
            all_hits = []
            for ls in launch_slugs:
                hit = await _query_post(client, headers, ls)
                if hit.get("found"):
                    all_hits.append(hit)

            # Include seed_hit if not already captured
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

    return {
        "found": False,
        "slugs_tried": [brand, name_slug],
        "note": "未在 Product Hunt 上找到该产品。可手动搜索：producthunt.com/search?q=" + brand
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

    # Pick the best matching group
    best_group = None
    target_slugs = {product_slug, brand, product_name.lower().replace(" ", "-")}
    for ps, hits in product_groups.items():
        if ps in target_slugs:
            best_group = hits
            break
    if not best_group:
        best_group = max(product_groups.values(), key=lambda g: max(h.get("votes", 0) for h in g))

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
        return _format_post(post)
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


async def _query_by_url(client, headers, url) -> dict:
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
        return _format_post(edges[0]["node"])
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


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
