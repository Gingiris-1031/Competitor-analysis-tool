"""定价页分析模块 — 自动抓取定价结构、功能矩阵、定价策略"""
import asyncio
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from . import tinyfish
from .i18n import _T

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# Common pricing page paths to probe
_PRICING_PATHS = [
    "/pricing", "/plans", "/pricing/", "/plans/",
    "/upgrade", "/subscribe", "/#pricing", "/#plans",
]

# Price regex: $9.99, $2,100/mo, €12, free, etc.  Supports comma-separated thousands.
_PRICE_RE = re.compile(
    r'(?:free|\$\s*\d[\d,]*(?:\.\d{1,2})?|€\s*\d[\d,]*(?:\.\d{1,2})?|£\s*\d[\d,]*(?:\.\d{1,2})?|\d[\d,]*\s*(?:USD|EUR|GBP))',
    re.IGNORECASE,
)
_DOLLAR_RE = re.compile(r'\$\s*(\d[\d,]*(?:\.\d{1,2})?)')


def _parse_price(s: str) -> float:
    """Parse a price string like '2,100.00' or '19' into a float."""
    return float(s.replace(',', ''))


async def analyze_pricing(url: str, product_name: str) -> dict:
    """抓取定价页，提取定价结构"""
    base = url.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base

    # Try pricing paths + homepage as fallback
    candidates = [base + p for p in _PRICING_PATHS] + [base]

    # Strategy 0: TinyFish first (Chromium-rendered, handles JS-heavy pages).
    # Batch top candidates in a single API call (free tier, 10 URLs/request).
    # Falls through to httpx if TinyFish unavailable, returns no pricing
    # signal, or returns an empty result set.
    if tinyfish.is_available():
        try:
            batch = await tinyfish.fetch_batch_html(candidates[:6], timeout=25.0)
            for pricing_url in candidates:
                r = batch.get(pricing_url)
                if not r:
                    continue
                html = r.get("text") or ""
                if not html:
                    continue
                soup = BeautifulSoup(html, "html.parser")
                plain = soup.get_text(separator="\n", strip=True)
                lower = plain.lower()
                has_price = any(x in lower for x in [
                    "$", "€", "£", "/month", "/mo", "/year", "/yr",
                    "free plan", "pro plan", "enterprise", "pricing", "subscribe",
                ])
                if not has_price:
                    continue
                result = _extract_pricing(soup, plain, pricing_url, product_name)
                if result.get("tiers"):
                    return result
        except Exception:
            pass  # fall through to httpx

    async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=_HEADERS) as client:
        for pricing_url in candidates:
            try:
                resp = await client.get(pricing_url)
                if resp.status_code != 200:
                    continue
                text = resp.text
                soup = BeautifulSoup(text, "html.parser")
                plain = soup.get_text(separator="\n", strip=True)

                # Check if page has pricing signals
                lower = plain.lower()
                has_price = any(x in lower for x in [
                    "$", "€", "£", "/month", "/mo", "/year", "/yr",
                    "free plan", "pro plan", "enterprise", "pricing", "subscribe",
                ])
                if not has_price:
                    continue

                result = _extract_pricing(soup, plain, pricing_url, product_name)
                if result.get("tiers"):
                    return result
            except Exception:
                continue

    return {"found": False, "source_url": None, "tiers": [], "model": "unknown"}


def _extract_pricing(soup: BeautifulSoup, plain: str, source_url: str, product_name: str) -> dict:
    """从 HTML 提取定价结构"""
    tiers = []
    
    # Strategy 1: find price cards / plan sections
    # Look for elements that contain a price amount
    price_cards = _find_price_cards(soup)
    if price_cards:
        tiers = price_cards

    # Strategy 2: regex scan the full text for price patterns
    if not tiers:
        tiers = _regex_extract_tiers(plain)

    # Determine pricing model
    lower = plain.lower()
    if "open source" in lower or "self-host" in lower or "self host" in lower:
        model = "open-source"
    elif "usage" in lower and ("credit" in lower or "token" in lower or "api call" in lower):
        model = "usage-based"
    elif any(t.get("price_monthly") == 0 for t in tiers) and len(tiers) > 1:
        model = "freemium"
    elif tiers and all(t.get("price_monthly", 1) > 0 for t in tiers):
        model = "subscription"
    else:
        model = "freemium"

    free_plan = any(
        t.get("price_monthly") == 0 or "free" in t.get("name", "").lower()
        for t in tiers
    )
    free_trial = any(
        kw in plain.lower() for kw in ["free trial", "try free", "14-day", "30-day", "day free"]
    )

    # Extract annual discount if present
    annual_discount = None
    annual_match = re.search(r'save\s+(\d+)%|(\d+)%\s+off.*?annual|annual.*?save\s+(\d+)%', plain, re.IGNORECASE)
    if annual_match:
        pct = next(g for g in annual_match.groups() if g)
        annual_discount = f"{pct}% off with annual billing"

    # Key pricing signals
    insights = []
    prices = [t["price_monthly"] for t in tiers if t.get("price_monthly") and t["price_monthly"] > 0]
    if prices:
        if min(prices) < 10:
            insights.append(_T(f"Entry price ${min(prices):.0f}/mo — below the category average, good for acquisition",
                               f"入门定价 ${min(prices):.0f}/月，低于行业均价，利于获客"))
        if max(prices) > 50:
            insights.append(_T(f"Top tier ${max(prices):.0f}/mo — clear enterprise-customer positioning",
                               f"高端套餐 ${max(prices):.0f}/月，有明确企业客户定位"))
        if len(prices) >= 3:
            insights.append(_T(f"{len(tiers)} pricing tiers — a classic 'sandwich' structure nudging users to the middle plan",
                               f"共 {len(tiers)} 个定价层级，典型'三明治'结构引导用户选中间档"))
    if free_plan:
        insights.append(_T("Has a free plan — clear PLG strategy", "有免费套餐，PLG 策略明显"))
    if free_trial:
        insights.append(_T("Offers a free trial — lowers the payment barrier", "提供免费试用，降低付费门槛"))
    if annual_discount:
        insights.append(annual_discount)

    return {
        "found": bool(tiers),
        "source_url": source_url,
        "model": model,
        "free_plan": free_plan,
        "free_trial": free_trial,
        "annual_discount": annual_discount,
        "tiers": tiers,
        "insights": insights,
    }


def _find_price_cards(soup: BeautifulSoup) -> list:
    """尝试从 HTML 结构中识别定价卡片"""
    tiers = []
    
    # Look for common pricing card patterns
    # Many sites use aria-labels or headings near price elements
    price_elements = soup.find_all(string=_PRICE_RE)
    
    seen_prices = set()
    for el in price_elements[:20]:
        parent = el.parent
        if not parent:
            continue
        
        # Walk up to find a "card" container (up to 5 levels)
        card = parent
        for _ in range(5):
            if card.parent and card.parent.name in ("div", "section", "article", "li"):
                card = card.parent
                card_text = card.get_text(separator=" ", strip=True)
                # Card should have a plan name-ish heading
                headings = card.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "b"])
                if headings:
                    break
            else:
                break
        
        card_text = card.get_text(separator="\n", strip=True)
        if len(card_text) < 20 or len(card_text) > 3000:
            continue
        
        # Extract price from card
        dollar_match = _DOLLAR_RE.search(card_text)
        if not dollar_match:
            if "free" not in card_text.lower():
                continue
            price = 0.0
        else:
            price = _parse_price(dollar_match.group(1))
        
        # Extract name from headings — prefer short, plan-name-like headings
        headings = card.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "b"])
        plan_name = "Plan"
        _marketing_words = {
            "start", "try", "get", "write", "draw", "plan", "build", "launch",
            "create", "discover", "explore", "connect", "learn", "collaborate",
            "everything", "unlimited", "all", "once", "today", "now", "join",
        }
        for h in headings:
            txt = h.get_text(strip=True)
            words = txt.split()
            # Good plan name: short (1–4 words), no marketing copy keywords
            if 1 <= len(words) <= 4 and len(txt) <= 30:
                first_word_lower = words[0].lower()
                if first_word_lower not in _marketing_words:
                    plan_name = txt
                    break
        else:
            # Fallback: use first heading truncated
            if headings:
                plan_name = headings[0].get_text(strip=True)[:30]
        
        if plan_name in seen_prices:
            continue
        seen_prices.add(plan_name)
        
        # Extract feature bullets
        features = []
        for li in card.find_all("li")[:10]:
            txt = li.get_text(strip=True)
            if txt and len(txt) < 100 and txt not in features:
                features.append(txt)
        
        # Determine if annual price mentioned
        annual_match = _DOLLAR_RE.findall(card_text)
        prices_in_card = [_parse_price(p) for p in annual_match]
        
        tier = {
            "name": plan_name,
            "price_monthly": price,
            "price_annual_monthly": None,
            "features": features[:8],
            "highlight": "free" in plan_name.lower() or price == 0,
        }
        
        # If two prices, smaller one is likely annual/mo
        if len(prices_in_card) >= 2:
            prices_in_card_sorted = sorted(set(prices_in_card))
            if len(prices_in_card_sorted) >= 2:
                tier["price_annual_monthly"] = prices_in_card_sorted[0]
                tier["price_monthly"] = prices_in_card_sorted[-1]
        
        tiers.append(tier)
    
    # Dedupe by price
    seen = set()
    deduped = []
    for t in tiers:
        key = (t["name"], t["price_monthly"])
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    
    return deduped[:6]  # max 6 tiers


def _regex_extract_tiers(plain: str) -> list:
    """Fallback: regex scan for plan+price patterns in plain text"""
    plan_keywords = ["free", "starter", "basic", "pro", "plus", "premium", "business",
                     "team", "enterprise", "growth", "scale", "ultimate", "individual"]
    
    tiers = []
    lines = plain.split("\n")
    
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        if not line_lower or len(line_lower) > 80:
            continue
        
        # Check if line looks like a plan name
        is_plan = any(kw == line_lower or line_lower.startswith(kw) for kw in plan_keywords)
        if not is_plan:
            continue
        
        # Look for a price in surrounding lines (±5)
        window = lines[max(0, i-2):i+8]
        window_text = " ".join(window)
        dollar_match = _DOLLAR_RE.search(window_text)
        
        price = 0.0 if "free" in line_lower else None
        if dollar_match:
            price = _parse_price(dollar_match.group(1))
        
        if price is None:
            continue
        
        tiers.append({
            "name": line.strip()[:40],
            "price_monthly": price,
            "price_annual_monthly": None,
            "features": [],
            "highlight": price == 0,
        })
    
    return tiers[:5]
