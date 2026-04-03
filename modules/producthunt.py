"""Product Hunt API 集成模块"""
import httpx
import os
import re
import json
import subprocess

PH_API = "https://api.producthunt.com/v2/api/graphql"
NODE_BIN = "/Users/iriscarrot/.ship/bin/node"
PLAYWRIGHT_PATH = "/Applications/Cola.app/Contents/Resources/server/node_modules/playwright-core"


def _get_token() -> str:
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


def _discover_launches_via_browser(product_slug: str) -> list:
    """
    Use Playwright (via CDP) to scrape the PH product page and return all launch slugs.
    Writes the Node.js script to a temp file to avoid shell/inline escaping issues.
    Returns a list of launch slug strings, or [] on failure.
    """
    import tempfile

    script_content = (
        "const { chromium } = require('" + PLAYWRIGHT_PATH + "');\n"
        "(async () => {\n"
        "    let browser;\n"
        "    let page;\n"
        "    try {\n"
        "        browser = await chromium.connectOverCDP('http://localhost:19542');\n"
        "        const contexts = browser.contexts();\n"
        "        const ctx = contexts[0];\n"
        "        page = await ctx.newPage();\n"
        "\n"
        "        const productSlug = process.argv[2];\n"
        "        const url = `https://www.producthunt.com/products/${productSlug}`;\n"
        "        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 });\n"
        "\n"
        "        // Wait for JS to render launch links\n"
        "        await page.waitForTimeout(3000);\n"
        "\n"
        "        // Click 'More' / 'Show more' buttons if present (up to 3 times)\n"
        "        for (let i = 0; i < 3; i++) {\n"
        "            try {\n"
        "                const moreBtn = await page.$('button:has-text(\"More\"), a:has-text(\"More launches\"), button:has-text(\"Show more\")');\n"
        "                if (moreBtn) { await moreBtn.click(); await page.waitForTimeout(1500); } else { break; }\n"
        "            } catch (e) { break; }\n"
        "        }\n"
        "\n"
        "        // Extract all /products/{slug}/launches/{launchSlug} hrefs\n"
        "        const hrefs = await page.$$eval('a[href]', (anchors, ps) => {\n"
        "            const pattern = new RegExp(`/products/${ps}/launches/([^/?#]+)`);\n"
        "            const found = [];\n"
        "            for (const a of anchors) {\n"
        "                const href = a.getAttribute('href') || '';\n"
        "                const m = href.match(pattern);\n"
        "                if (m && !found.includes(m[1])) found.push(m[1]);\n"
        "            }\n"
        "            return found;\n"
        "        }, productSlug);\n"
        "\n"
        "        await page.close();\n"
        "        console.log(JSON.stringify(hrefs));\n"
        "    } catch (err) {\n"
        "        if (page) { try { await page.close(); } catch(_) {} }\n"
        "        console.error(err.message);\n"
        "        console.log(JSON.stringify([]));\n"
        "    }\n"
        "    // Do NOT close the browser — connected over CDP to existing instance\n"
        "    process.exit(0);\n"
        "})();\n"
    )

    try:
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.js', delete=False, prefix='ph_scrape_'
        ) as f:
            f.write(script_content)
            tmp_path = f.name

        result = subprocess.run(
            [NODE_BIN, tmp_path, product_slug],
            capture_output=True, text=True, timeout=35
        )
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        if not result.stdout.strip():
            return []
        return json.loads(result.stdout.strip())
    except Exception:
        return []


async def analyze_producthunt(domain: str, product_name: str) -> dict:
    """查询产品在 Product Hunt 上的表现"""
    token = _get_token()
    if not token:
        return {"found": False, "error": "No PH token"}

    brand = _extract_brand(domain)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=15) as client:
        # ── Step 1: Use API to find at least one post and extract product_slug ──
        product_slug = None
        seed_hit = None

        name_slug = product_name.lower().replace(" ", "-")
        seed_slugs = list(dict.fromkeys([brand, name_slug]))

        for slug in seed_slugs:
            hit = await _query_post(client, headers, slug)
            if hit.get("found"):
                seed_hit = hit
                # Extract product_slug from PH url  e.g. /products/lovable/launches/lovable
                m = re.search(r'/products/([^/]+)/', hit.get("url", ""))
                if m:
                    product_slug = m.group(1).lower()
                break

        # If API gave nothing, fall back to brand as product_slug
        if not product_slug:
            product_slug = brand

        # ── Step 2: Discover all launch slugs via browser ──
        launch_slugs = _discover_launches_via_browser(product_slug)

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
    """Build the full fallback slug enumeration list."""
    base_names = list(dict.fromkeys([brand, name_slug]))
    slugs = []
    for base in base_names:
        slugs.append(base)
    for base in base_names:
        slugs.append(f"{base}-ai")
    for suffix in range(2, 7):
        for base in base_names:
            slugs.append(f"{base}-{suffix}")
    for base in base_names:
        for variant in ["dev", "app", "io", "pro", "hq"]:
            slugs.append(f"{base}-{variant}")
    for base in base_names:
        slugs.extend([f"get-{base}", f"use-{base}"])
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
