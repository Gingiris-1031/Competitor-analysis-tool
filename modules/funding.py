"""融资信息分析模块 — Brave Search 结构化解析 + Crunchbase 公开页"""
import httpx
import re
import asyncio


def _extract_brand(domain: str) -> str:
    brand = re.sub(r'^www\.', '', domain.lower().strip())
    return re.sub(r'\.[a-z]{2,6}$', '', brand)


async def analyze_funding(domain: str, product_name: str) -> dict:
    """分析产品融资历史：轮次、金额、投资方"""
    brand = _extract_brand(domain)

    brave_task = _brave_funding_search(product_name, brand, domain)
    cb_task    = _scrape_crunchbase(brand)

    results = await asyncio.gather(brave_task, cb_task, return_exceptions=True)

    brave_data = results[0] if isinstance(results[0], dict) else {}
    cb_data    = results[1] if isinstance(results[1], dict) else {}

    # Crunchbase structured data takes priority; Brave fills gaps
    merged = {**brave_data}
    for k, v in cb_data.items():
        if v and not merged.get(k):
            merged[k] = v
    if cb_data.get("found"):
        merged["found"] = True
    if cb_data.get("crunchbase_url"):
        merged["crunchbase_url"] = cb_data["crunchbase_url"]

    if not merged.get("found"):
        return {
            "found": False,
            "note": "未找到公开融资信息（可能为 Bootstrapped 或未公开融资）",
        }

    merged["insights"] = _gen_insights(merged)
    return merged


async def _brave_funding_search(product_name: str, brand: str, domain: str) -> dict:
    try:
        from .web_search import brave_search
    except ImportError:
        try:
            from web_search import brave_search
        except ImportError:
            return {"found": False}

    # Patterns for parsing funding info from snippets
    round_re = re.compile(
        r'(pre-seed|seed|series [a-e]|series [a-z]+|angel|growth|venture)\s*(?:round|funding)?\s*'
        r'(?:of\s*)?\$?\s*([\d,.]+)\s*(million|m\b|billion|b\b)',
        re.I,
    )
    money_re = re.compile(r'\$\s*([\d,.]+)\s*(million|m\b|billion|b\b)', re.I)
    investor_re = re.compile(
        r'(?:led by|backed by|from|investors?[:：]\s*)([A-Z][A-Za-z0-9 ,&\-]+?)(?:\.|,\s*and|\s+in\s|\s+to\s|$)',
        re.M,
    )

    found_rounds = []
    investors = []

    queries = [
        f'"{product_name}" funding raise series million',
        f'"{brand}" investment valuation crunchbase',
        f'"{domain}" investors backed',
    ]

    for q in queries:
        try:
            hits = await brave_search(q, count=5)
        except Exception:
            continue
        for h in hits:
            text = (h.get("title") or "") + " " + (h.get("description") or "")

            # Try structured round parsing first
            for m in round_re.finditer(text):
                raw_amount = m.group(2).replace(",", "")
                multiplier = 1_000_000_000 if m.group(3).lower().startswith("b") else 1_000_000
                try:
                    amount = int(float(raw_amount) * multiplier)
                    round_name = _normalize_round(m.group(1))
                    if not any(r["round"] == round_name for r in found_rounds):
                        found_rounds.append({
                            "round":  round_name,
                            "amount": amount,
                            "source": h.get("url", ""),
                        })
                except (ValueError, OverflowError):
                    pass

            # Extract investor names
            for inv in investor_re.finditer(text):
                raw = inv.group(1).strip()
                names = [n.strip() for n in re.split(r",\s*| and ", raw) if len(n.strip()) > 2]
                investors.extend(names)

    if not found_rounds:
        return {"found": False}

    found_rounds.sort(key=lambda x: _round_order(x["round"]))
    latest = found_rounds[-1]
    total  = sum(r.get("amount", 0) for r in found_rounds)
    unique_investors = list(dict.fromkeys(investors))[:8]

    return {
        "found":         True,
        "source":        "brave_search",
        "latest_round":  latest.get("round", ""),
        "latest_amount": latest.get("amount", 0),
        "total_raised":  total,
        "rounds":        found_rounds,
        "investors":     unique_investors,
    }


async def _scrape_crunchbase(brand: str) -> dict:
    """尝试从 Crunchbase 公开页面抓取融资摘要（JSON-LD / script data）"""
    url = f"https://www.crunchbase.com/organization/{brand}"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html",
            })
        if resp.status_code != 200:
            return {"found": False}

        text = resp.text
        # Crunchbase embeds structured data in various script tags
        total_m  = re.search(r'"funding_total"[^}]*"value_usd"\s*:\s*([\d.]+)', text)
        round_m  = re.search(r'"last_funding_type"\s*:\s*"([^"]+)"', text)
        date_m   = re.search(r'"last_funding_at"\s*:\s*"([^"]+)"', text)
        raised_m = re.search(r'Total Funding Amount.*?\$([\d,.]+[MBK])', text)

        if total_m or round_m or raised_m:
            total = None
            if total_m:
                try:
                    total = int(float(total_m.group(1)))
                except ValueError:
                    pass
            return {
                "found":          True,
                "source":         "crunchbase",
                "total_raised":   total,
                "latest_round":   _normalize_round(round_m.group(1)) if round_m else None,
                "latest_date":    date_m.group(1)[:10] if date_m else None,
                "crunchbase_url": url,
            }
        return {"found": False}
    except Exception:
        return {"found": False}


def _normalize_round(raw: str) -> str:
    r = raw.strip().lower().replace("_", " ")
    mapping = {
        "pre seed": "Pre-Seed", "pre-seed": "Pre-Seed",
        "seed": "Seed", "angel": "Angel",
        "series a": "Series A", "series b": "Series B",
        "series c": "Series C", "series d": "Series D",
        "series e": "Series E", "growth": "Growth",
        "venture": "Venture",
    }
    return mapping.get(r, raw.title())


_ROUND_ORDER = ["Pre-Seed", "Angel", "Seed", "Series A", "Series B",
                "Series C", "Series D", "Series E", "Growth"]


def _round_order(r: str) -> int:
    try:
        return _ROUND_ORDER.index(r)
    except ValueError:
        return 99


def _fmt_money(n: int) -> str:
    if not n:
        return "—"
    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n / 1_000:.0f}K"
    return f"${n}"


def _gen_insights(data: dict) -> list:
    insights = []
    total  = data.get("total_raised", 0)
    latest = data.get("latest_round", "")
    investors = data.get("investors", [])

    if total:
        insights.append(f"💰 累计融资 **{_fmt_money(total)}**（最近轮次：{latest}）")
    elif latest:
        insights.append(f"📋 已完成 **{latest}** 轮融资（金额未公开）")

    if investors:
        insights.append(f"🤝 已知投资方：{', '.join(investors[:5])}")

    rounds = data.get("rounds", [])
    if len(rounds) >= 2:
        insights.append(f"📈 共 {len(rounds)} 轮融资记录，显示持续获得机构认可")

    source = data.get("source", "")
    if source == "crunchbase":
        cb_url = data.get("crunchbase_url", "")
        if cb_url:
            insights.append(f"🔗 数据来源：Crunchbase（{cb_url}）")

    return insights
