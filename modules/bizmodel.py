"""商业模型分析 + 商业化进展模块 — 整合现有数据"""
from .i18n import _T
import re


def analyze_bizmodel(domain: str, product_name: str,
                     pricing: dict = None, traffic: dict = None,
                     github_oss: dict = None, producthunt: dict = None,
                     funding: dict = None) -> dict:
    """同步分析商业模型：整合定价/流量/开源/融资数据"""
    p  = pricing    or {}
    t  = traffic    or {}
    g  = github_oss or {}
    ph = producthunt or {}
    f  = funding    or {}

    model_type       = _classify_model(p, g, ph)
    revenue_estimate = _estimate_revenue(p, t)
    stage            = _assess_stage(p, t, f, g)
    levers           = _identify_levers(p, g)
    insights         = _gen_insights(model_type, revenue_estimate, stage, p, g, f, ph)

    return {
        "found":               True,
        "model_type":          model_type,
        "revenue_estimate":    revenue_estimate,
        "stage":               stage,
        "monetization_levers": levers,
        "insights":            insights,
    }


def _classify_model(p: dict, g: dict, ph: dict) -> dict:
    has_free        = p.get("free_plan", False)
    has_open_source = g.get("found", False)
    license_        = (g.get("license") or "")
    tiers           = p.get("tiers") or []
    has_enterprise  = any("enterprise" in (t.get("name") or "").lower() for t in tiers)
    has_paid_tiers  = any((t.get("price_monthly") or 0) > 0 for t in tiers)
    stars           = g.get("stars", 0)

    primary   = []
    secondary = []

    if has_open_source and stars > 0:
        if "AGPL" in license_ or "GPL" in license_:
            primary.append(_T("OSS-led / Open Core (AGPL — SaaS needs a commercial license)",
                              "OSS-led / Open Core（AGPL，SaaS 需商业授权）"))
        elif "MIT" in license_ or "Apache" in license_:
            primary.append(_T("OSS-led (permissive license — cloud-hosted / enterprise edition monetization)",
                              "OSS-led（宽松协议，云托管版/企业版变现）"))
        else:
            primary.append(_T("OSS-led (open-source-driven growth)", "OSS-led（开源驱动增长）"))

    if has_free and has_paid_tiers:
        primary.append(_T("PLG — Freemium (free → paid upgrade)", "PLG — Freemium（免费→付费升级）"))
    elif has_paid_tiers and p.get("found"):
        secondary.append("Self-serve SaaS")

    if has_enterprise:
        secondary.append(_T("SLG (enterprise edition + sales team)", "SLG（企业版 + 销售团队）"))

    if not primary and not secondary:
        if ph.get("found"):
            primary = [_T("PLG (community-driven, validated on Product Hunt)", "PLG（社区驱动，Product Hunt 验证）")]
        else:
            primary = [_T("Business model TBD (no public pricing data)", "商业模式待确认（无公开定价数据）")]

    return {
        "primary":          primary,
        "secondary":        secondary,
        "has_free_tier":    has_free,
        "has_open_source":  has_open_source,
        "has_enterprise":   has_enterprise,
        "oss_stars":        stars,
        "license":          license_,
    }


def _estimate_revenue(p: dict, t: dict) -> dict:
    tiers = p.get("tiers") or []
    paid_tiers = [tier for tier in tiers if (tier.get("price_monthly") or 0) > 0]
    if not paid_tiers:
        return {"method": _T("No public paid pricing — cannot estimate", "无公开付费定价，无法估算"),
                "arr_low": None, "arr_high": None}

    rank_data       = (t.get("domain_rank") or {})
    organic_traffic = rank_data.get("organic_traffic") or 0
    if organic_traffic < 500:
        return {"method": _T("Insufficient traffic data — cannot estimate", "流量数据不足，无法估算"),
                "arr_low": None, "arr_high": None}

    # Estimate total monthly visits: organic search ≈ 40-65% of total for SaaS
    # Use 1.6x conservative multiplier to account for direct/referral/social traffic
    monthly_visits = int(organic_traffic * 1.6)

    # Conservative: 1-3% free-to-paid conversion (PLG benchmark)
    low_pct  = 0.01
    high_pct = 0.03
    paying_low  = int(monthly_visits * low_pct)
    paying_high = int(monthly_visits * high_pct)

    # Use lowest paid tier price as baseline
    min_price = min((tier.get("price_monthly") or 0) for tier in paid_tiers if (tier.get("price_monthly") or 0) > 0)

    arr_low  = paying_low  * min_price * 12
    arr_high = paying_high * min_price * 12

    return {
        "method":              _T(f"Est. total monthly visits ~{monthly_visits:,} (organic search {organic_traffic:,} × 1.6) × 1–3% conversion × ${min_price}/mo",
                                   f"月总访问估算 ~{monthly_visits:,}（有机搜索 {organic_traffic:,} × 1.6）× 1–3% 转化 × ${min_price}/月"),
        "arr_low":             arr_low,
        "arr_high":            arr_high,
        "monthly_visits":      monthly_visits,
        "organic_traffic":     organic_traffic,
        "avg_price_monthly":   min_price,
        "paying_users_low":    paying_low,
        "paying_users_high":   paying_high,
        "assumptions":         _T("Conservative: organic traffic × 1.6 for total visits; 1–3% free-to-paid conversion (PLG benchmark)",
                                   "保守估算：有机流量 × 1.6 估算总访问；1–3% 免费→付费转化率（PLG 行业基准）"),
    }


def _assess_stage(p: dict, t: dict, f: dict, g: dict) -> str:
    monthly_visits = ((t.get("domain_rank") or {}).get("organic_traffic") or 0)
    stars          = g.get("stars", 0)
    has_paid       = p.get("found") and any((tier.get("price_monthly") or 0) > 0
                                            for tier in (p.get("tiers") or []))
    latest_round   = (f.get("latest_round") or "").lower()
    has_series     = "series" in latest_round

    if monthly_visits > 500_000 or stars > 30_000:
        return _T("Scale-up (PMF proven, monetization scaling)", "规模扩张期（PMF 已验证，商业化扩张）")
    if monthly_visits > 100_000 or stars > 10_000:
        if has_paid:
            return _T("PMF-validation (traffic solid, monetization landing)", "PMF 验证期（流量稳健，商业化落地中）")
        return _T("Growth (high traffic/stars, monetization not yet started)", "增长期（高流量/Star，商业化待启动）")
    if monthly_visits > 20_000 or stars > 1_000:
        if has_paid or has_series:
            return _T("Early monetization (paying users / institutional funding)", "早期商业化期（有付费用户/机构融资）")
        return _T("Early growth (has a user base, exploring the model)", "早期增长期（有用户基础，商业模式探索）")
    return _T("0→1 stage (early product, building a user base)", "0→1 阶段（产品早期，建立用户基础）")


def _identify_levers(p: dict, g: dict) -> list:
    levers = []
    tiers    = p.get("tiers") or []
    has_free = p.get("free_plan")
    license_ = (g.get("license") or "")

    paid = [(t.get("name", ""), t.get("price_monthly") or 0)
            for t in tiers if (t.get("price_monthly") or 0) > 0]

    if has_free and paid:
        name, price = paid[0]
        levers.append(_T(f"Freemium upgrade: free → {name} (${price}/mo)", f"Freemium 升级：免费 → {name}（${price}/月）"))

    if any("enterprise" in (t.get("name") or "").lower() for t in tiers):
        levers.append(_T("Enterprise contracts (annual + self-hosting + SLA)", "Enterprise 合同（年付 + 私有部署 + SLA）"))

    if g.get("found"):
        if "AGPL" in license_ or "GPL" in license_:
            levers.append(_T("Commercial license for the OSS (SaaS / self-hosting must buy a commercial license)",
                             "开源协议商业授权（SaaS/私有部署需购买 Commercial License）"))
        levers.append(_T("Cloud-hosted edition (SaaS — lowers self-hosting friction, lifts conversion)",
                         "云托管版（SaaS，降低自部署门槛，提升转化）"))

    if p.get("annual_discount"):
        levers.append(_T(f"Annual-plan discount to lock in users: {p['annual_discount']}", f"年付折扣锁定用户：{p['annual_discount']}"))

    if p.get("free_trial"):
        levers.append(_T("Free trial (lowers the purchase-decision barrier)", "免费试用期（降低付费决策门槛）"))

    return levers or [_T("No clear monetization-lever data yet", "暂无明确变现杠杆数据")]


def _fmt_money(n) -> str:
    if not n:
        return "—"
    n = int(n)
    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n / 1_000:.0f}K"
    return f"${n}"


def _gen_insights(model_type, revenue, stage, p, g, f, ph) -> list:
    insights = []

    primary = model_type.get("primary") or []
    if primary:
        insights.append(_T(f"🏗 Business model: {' + '.join(primary)}", f"🏗 商业模式：{' + '.join(primary)}"))
    secondary = model_type.get("secondary") or []
    if secondary:
        insights.append(_T(f"➕ Secondary model: {' / '.join(secondary)}", f"➕ 辅助模式：{' / '.join(secondary)}"))

    insights.append(_T(f"📊 Monetization stage: **{stage}**", f"📊 商业化阶段：**{stage}**"))

    arr_low  = revenue.get("arr_low")
    arr_high = revenue.get("arr_high")
    if arr_low and arr_high:
        insights.append(_T(
            f"💰 Conservative ARR estimate: **{_fmt_money(arr_low)} – {_fmt_money(arr_high)}** ({revenue.get('method', '')})",
            f"💰 保守 ARR 估算：**{_fmt_money(arr_low)} – {_fmt_money(arr_high)}**（{revenue.get('method', '')}）"
        ))

    total_raised = f.get("total_raised")
    if f.get("found") and total_raised:
        insights.append(_T(f"💵 Raised {_fmt_money(total_raised)} ({f.get('latest_round', '')})",
                           f"💵 已融资 {_fmt_money(total_raised)}（{f.get('latest_round', '')}）"))
    elif f.get("found"):
        insights.append(_T(f"💵 Completed {f.get('latest_round', '')} round (amount undisclosed)",
                           f"💵 已完成 {f.get('latest_round', '')} 融资（金额未公开）"))

    stars = g.get("stars", 0)
    forks = g.get("forks", 0)
    if stars > 1_000 and forks:
        fork_ratio = forks / stars
        if fork_ratio > 0.08:
            insights.append(_T(f"🍴 Fork ratio {fork_ratio:.0%} ({forks:,} forks) — active community forking",
                               f"🍴 Fork 率 {fork_ratio:.0%}（{forks:,} forks），社区二次开发活跃"))

    if ph.get("found"):
        votes = ph.get("votes", 0)
        other = ph.get("other_launches") or []
        launch_count = 1 + len(other)
        if launch_count > 1:
            insights.append(_T(f"🚀 {launch_count} Product Hunt launches, top {votes:,} votes (PLG community validation)",
                               f"🚀 {launch_count} 次 Product Hunt 发布，最高 {votes:,} votes（PLG 社区验证）"))

    return insights
