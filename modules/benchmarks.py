"""增长诊断基准线 + 评分引擎 — 把 Knowhow 总库 §2 的基准判断产品化。

对外只暴露数字 + 品类说明，内部文档不上库。核心用法：

    from modules import benchmarks
    card = benchmarks.score_growth(
        inputs={"uv": 20000, "signups": 1800, "paid": 54},
        category="pro_c",
        seo_score=72,          # 复用现有 audit 的站内 SEO 分（可选）
        cac={"signup": 6.5, "paid": 61},  # 可选，投流红线判断
    )

评分口径（「离钱近」优先）：付费转化 > 注册转化 > 获客成本 > SEO 基建。
"""
from __future__ import annotations

from typing import Optional

# ── 品类基准表（来源：Knowhow 总库 §2）───────────────────────────────────
# 每个品类给注册→付费的「合格线 / 优秀线」；UV→注册与 SEO 基建跨品类通用。
# 品类说明：
#   pro_c  = 专业型 2C（付费意愿介于纯消费与 B2B 之间，Pro-Consumer）
#   smb    = 中小企业工具（客单价低、决策短，付费转化天然更高）
#   b2b    = 企业/销售驱动（转化看 SQL→成单，不吃这套自助漏斗，仅给参考）
#   default= 未识别品类时的通用兜底
_PAID_CONVERSION = {
    "pro_c":   {"pass": 0.05, "good": 0.08},   # Pro-C 5-8%
    "smb":     {"pass": 0.10, "good": 0.15},   # SMB 10-15%
    "b2b":     {"pass": 0.02, "good": 0.05},   # 自助漏斗参考值
    "default": {"pass": 0.05, "good": 0.10},   # 合格线 5%
}

# UV→注册：最低 10% / 优秀 30-40%（跨品类通用）
_SIGNUP_CONVERSION = {"pass": 0.10, "good": 0.30}

# 站内 SEO 分：≥85 才「配铺内容」；Ahrefs 类成熟站点基准 80
_SEO_ONSITE = {"pass": 80, "good": 85}

# 投流红线（获客成本上限，USD）：注册 CAC $5-8，付费 CAC < $50
_CAC_LIMIT = {
    "signup": {"pass": 8.0, "good": 5.0},    # 注册 CAC ≤ $8 及格、≤ $5 优秀
    "paid":   {"pass": 50.0, "good": 30.0},  # 付费 CAC < $50 及格
}

# 综合分权重（离钱近）：付费转化 35 / 注册转化 25 / 获客成本 20 / SEO 20
_WEIGHTS = {
    "paid_conversion":   35,
    "signup_conversion": 25,
    "cac":               20,
    "seo_onsite":        20,
}

# 修复优先级排序（数字越小越优先，「离钱近」）
_FIX_PRIORITY = {
    "paid_conversion":   1,
    "signup_conversion": 2,
    "cac":               3,
    "seo_onsite":        4,
}

_VALID_CATEGORIES = set(_PAID_CONVERSION.keys())

# 品类中文展示名（用于失分文案）
_CATEGORY_LABEL = {
    "pro_c": "专业型 2C",
    "smb": "中小企业工具",
    "b2b": "企业/销售驱动",
    "default": "通用",
}


def normalize_category(category: Optional[str]) -> str:
    """把外部传入的品类归一到已知 key，未知一律 default。"""
    if not category:
        return "default"
    c = str(category).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "proc": "pro_c", "pro_consumer": "pro_c", "prosumer": "pro_c",
        "consumer": "pro_c", "2c": "pro_c",
        "smb": "smb", "sme": "smb",
        "b2b": "b2b", "enterprise": "b2b", "sales_led": "b2b",
        "plg": "default", "saas": "default",
    }
    if c in _VALID_CATEGORIES:
        return c
    return aliases.get(c, "default")


def _grade(value: float, pass_line: float, good_line: float,
           higher_is_better: bool = True) -> str:
    """三档红黄绿：达到 good=green，达到 pass=yellow，否则 red。"""
    if higher_is_better:
        if value >= good_line:
            return "green"
        if value >= pass_line:
            return "yellow"
        return "red"
    # 越低越好（如 CAC）
    if value <= good_line:
        return "green"
    if value <= pass_line:
        return "yellow"
    return "red"


def _subscore(value: float, pass_line: float, good_line: float,
              higher_is_better: bool = True) -> int:
    """把单指标线性映射到 0-100 子分（good 及以上=100，0=0，pass 处约 60）。"""
    if pass_line == good_line:
        return 100 if _grade(value, pass_line, good_line, higher_is_better) == "green" else 40
    if higher_is_better:
        if value >= good_line:
            return 100
        if value <= 0:
            return 0
        if value >= pass_line:
            # pass..good → 60..100
            return int(60 + 40 * (value - pass_line) / (good_line - pass_line))
        # 0..pass → 0..60
        return int(60 * value / pass_line)
    # 越低越好
    if value <= good_line:
        return 100
    if value >= pass_line * 2:
        return 0
    if value <= pass_line:
        # good..pass → 100..60
        return int(60 + 40 * (pass_line - value) / (pass_line - good_line))
    # pass..2*pass → 60..0
    return int(60 * (pass_line * 2 - value) / pass_line)


def _pct(numer: float, denom: float) -> Optional[float]:
    if not denom or denom <= 0:
        return None
    return numer / denom


def score_growth(inputs: dict,
                 category: Optional[str] = None,
                 seo_score: Optional[float] = None,
                 cac: Optional[dict] = None) -> dict:
    """核心评分。返回三列对照 + 红黄绿灯 + 综合分 + 按「离钱近」排序的修复优先级。

    inputs: {"uv": int, "signups": int, "paid": int}  — 用户手填三漏斗数
    category: 见 normalize_category
    seo_score: 站内 SEO 分（0-100，复用现有 audit），None 则该项不计分
    cac: {"signup": float, "paid": float}（USD），None 则不计分

    返回:
      {
        "overall_score": 0-100,
        "category": "...",
        "metrics": [ {key,label,value,benchmark_pass,benchmark_good,grade,subscore}, ... ],
        "fixes": [ {key, priority, grade, message}, ... ],   # 只含 yellow/red，已按离钱近排序
      }
    """
    cat = normalize_category(category)
    cac = cac or {}
    uv = float(inputs.get("uv") or 0)
    signups = float(inputs.get("signups") or 0)
    paid = float(inputs.get("paid") or 0)

    metrics: list[dict] = []
    weighted_sum = 0.0
    weight_total = 0.0

    # ① 付费转化（注册→付费）— 最离钱
    p2p_bench = _PAID_CONVERSION[cat]
    signup_to_paid = _pct(paid, signups)
    if signup_to_paid is not None:
        g = _grade(signup_to_paid, p2p_bench["pass"], p2p_bench["good"])
        s = _subscore(signup_to_paid, p2p_bench["pass"], p2p_bench["good"])
        metrics.append({
            "key": "paid_conversion", "label": "注册 → 付费",
            "value": round(signup_to_paid, 4),
            "benchmark_pass": p2p_bench["pass"], "benchmark_good": p2p_bench["good"],
            "grade": g, "subscore": s,
        })
        weighted_sum += s * _WEIGHTS["paid_conversion"]
        weight_total += _WEIGHTS["paid_conversion"]

    # ② 注册转化（UV→注册）
    uv_to_signup = _pct(signups, uv)
    if uv_to_signup is not None:
        g = _grade(uv_to_signup, _SIGNUP_CONVERSION["pass"], _SIGNUP_CONVERSION["good"])
        s = _subscore(uv_to_signup, _SIGNUP_CONVERSION["pass"], _SIGNUP_CONVERSION["good"])
        metrics.append({
            "key": "signup_conversion", "label": "UV → 注册",
            "value": round(uv_to_signup, 4),
            "benchmark_pass": _SIGNUP_CONVERSION["pass"], "benchmark_good": _SIGNUP_CONVERSION["good"],
            "grade": g, "subscore": s,
        })
        weighted_sum += s * _WEIGHTS["signup_conversion"]
        weight_total += _WEIGHTS["signup_conversion"]

    # ③ 获客成本（投流红线）— 取付费 CAC 优先，无则注册 CAC
    cac_val = cac.get("paid")
    cac_kind = "paid"
    if cac_val is None:
        cac_val = cac.get("signup")
        cac_kind = "signup"
    if cac_val is not None:
        limit = _CAC_LIMIT[cac_kind]
        g = _grade(float(cac_val), limit["pass"], limit["good"], higher_is_better=False)
        s = _subscore(float(cac_val), limit["pass"], limit["good"], higher_is_better=False)
        metrics.append({
            "key": "cac", "label": f"获客成本（{'付费' if cac_kind == 'paid' else '注册'} CAC）",
            "value": round(float(cac_val), 2),
            "benchmark_pass": limit["pass"], "benchmark_good": limit["good"],
            "grade": g, "subscore": s, "lower_is_better": True,
        })
        weighted_sum += s * _WEIGHTS["cac"]
        weight_total += _WEIGHTS["cac"]

    # ④ SEO 站内基建
    if seo_score is not None:
        g = _grade(float(seo_score), _SEO_ONSITE["pass"], _SEO_ONSITE["good"])
        s = _subscore(float(seo_score), _SEO_ONSITE["pass"], _SEO_ONSITE["good"])
        metrics.append({
            "key": "seo_onsite", "label": "SEO 站内基建分",
            "value": round(float(seo_score), 1),
            "benchmark_pass": _SEO_ONSITE["pass"], "benchmark_good": _SEO_ONSITE["good"],
            "grade": g, "subscore": s,
        })
        weighted_sum += s * _WEIGHTS["seo_onsite"]
        weight_total += _WEIGHTS["seo_onsite"]

    overall = int(round(weighted_sum / weight_total)) if weight_total else 0

    # 修复优先级：只列没满分（yellow/red）的项，按「离钱近」排序
    fixes = []
    for m in metrics:
        if m["grade"] == "green":
            continue
        fixes.append({
            "key": m["key"],
            "priority": _FIX_PRIORITY.get(m["key"], 99),
            "grade": m["grade"],
            "message": _fix_message(m, cat),
        })
    fixes.sort(key=lambda x: x["priority"])

    return {
        "overall_score": overall,
        "category": cat,
        "metrics": metrics,
        "fixes": fixes,
    }


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fix_message(metric: dict, category: str) -> str:
    """给单个失分项生成一句人话结论（免费层用；付费层再挂详细修复方案 + skill）。"""
    key = metric["key"]
    grade = metric["grade"]
    sev = "严重低于" if grade == "red" else "略低于"
    cat_label = _CATEGORY_LABEL.get(category, "通用")
    if key == "paid_conversion":
        return (f"注册→付费 {_fmt_pct(metric['value'])}，{sev}"
                f"{cat_label}合格线 {_fmt_pct(metric['benchmark_pass'])}"
                f"（优秀 {_fmt_pct(metric['benchmark_good'])}）——这是最离钱的漏水点。")
    if key == "signup_conversion":
        return (f"UV→注册 {_fmt_pct(metric['value'])}，{sev}"
                f"最低线 {_fmt_pct(metric['benchmark_pass'])}"
                f"（优秀 {_fmt_pct(metric['benchmark_good'])}）。")
    if key == "cac":
        if grade == "red":
            return (f"获客成本 ${metric['value']}，已超红线 ${metric['benchmark_pass']}"
                    f"——投流前先修转化。")
        return (f"获客成本 ${metric['value']}，在红线 ${metric['benchmark_pass']} 内"
                f"但高于优秀线 ${metric['benchmark_good']}。")
    if key == "seo_onsite":
        return (f"站内 SEO 分 {metric['value']}，未达 {metric['benchmark_good']} "
                f"的「配铺内容」门槛（成熟站基准 {metric['benchmark_pass']}）。")
    return ""


# 便于前端/API 直接取用的基准快照（只读，不含内部文档）
def benchmark_snapshot(category: Optional[str] = None) -> dict:
    cat = normalize_category(category)
    return {
        "category": cat,
        "signup_conversion": _SIGNUP_CONVERSION,
        "paid_conversion": _PAID_CONVERSION[cat],
        "seo_onsite": _SEO_ONSITE,
        "cac_limit": _CAC_LIMIT,
        "source": "Knowhow 总库 §2",
    }
