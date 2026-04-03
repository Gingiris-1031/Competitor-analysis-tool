"""
Analook 冒烟测试 — 每次推代码前自动运行
用法:
  python tests/smoke_test.py                        # 默认测 localhost:8000
  BASE_URL=https://analook.com python tests/smoke_test.py
  python tests/smoke_test.py --url https://analook.com --domain affine.pro
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

# ── 配置 ─────────────────────────────────────────────────────────────────────
DEFAULT_BASE_URL  = os.environ.get("BASE_URL", "http://localhost:8000")
DEFAULT_DOMAIN    = "affine.pro"
POLL_INTERVAL_S   = 5
JOB_TIMEOUT_S     = 300   # 5 min max

# ── ANSI colors ───────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):   print(f"  {GREEN}✓{RESET} {msg}")
def fail(msg): print(f"  {RED}✗{RESET} {msg}"); return False
def warn(msg): print(f"  {YELLOW}⚠{RESET} {msg}")
def info(msg): print(f"  {CYAN}→{RESET} {msg}")


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


# ── Individual checks ─────────────────────────────────────────────────────────
RESULTS = []

def check(name: str, passed: bool, detail: str = ""):
    RESULTS.append((name, passed, detail))
    if passed:
        ok(f"{name}" + (f"  ({detail})" if detail else ""))
    else:
        fail(f"{name}" + (f"  → {detail}" if detail else ""))


def run_checks(report: dict, domain: str):
    sections = report.get("sections", {})
    meta     = report.get("meta", {})

    # ── Meta ──────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}[Meta]{RESET}")
    pname = meta.get("product_name", "")
    check("product_name 非空", bool(pname), pname)
    check("product_name 非全小写（大小写正确）",
          pname != pname.lower() or len(pname) <= 3,
          pname)

    # ── GitHub OSS ────────────────────────────────────────────────────────────
    print(f"\n{BOLD}[GitHub OSS]{RESET}")
    gh = sections.get("github_oss", {})
    check("github_oss.found = true", gh.get("found") is True)
    if gh.get("found"):
        stars = gh.get("stars", 0)
        check(f"Stars > 1,000", stars > 1000, f"{stars:,} stars")
        check("有 repo_url", bool(gh.get("repo_url")), gh.get("repo_url", ""))
        check("有 star_history", bool(gh.get("star_history")))

    # ── SEO / Traffic ─────────────────────────────────────────────────────────
    print(f"\n{BOLD}[SEO]{RESET}")
    tr  = sections.get("traffic_analysis", {})
    kw  = tr.get("top_keywords", {})
    branded     = kw.get("branded_keywords", [])
    product_kw  = kw.get("product_keywords", [])
    content_kw  = kw.get("content_keywords", [])
    check("有品牌词", len(branded) > 0, f"{len(branded)} 个")
    check("有产品相关非品牌词", len(product_kw) > 0, f"{len(product_kw)} 个")
    if content_kw:
        warn(f"内容SEO词 {len(content_kw)} 个（已单独归类）: "
             + ", ".join(c["keyword"] for c in content_kw[:3]))

    organic = tr.get("domain_rank", {}).get("organic_traffic", 0)
    check("有机流量 > 0", organic > 0, f"{organic:,}/月")

    # ── Pricing ───────────────────────────────────────────────────────────────
    print(f"\n{BOLD}[Pricing]{RESET}")
    pr = sections.get("pricing", {})
    tiers = pr.get("tiers", [])
    check("找到定价 tiers", len(tiers) > 0, f"{len(tiers)} 个")
    for t in tiers:
        name = t.get("name", "")
        words = name.split()
        check(f"Tier 名称合理（≤4词）: {name!r}",
              1 <= len(words) <= 4 and len(name) <= 30, name)

    # ── Social / Twitter ──────────────────────────────────────────────────────
    print(f"\n{BOLD}[Social]{RESET}")
    soc     = sections.get("social_media", {})
    twitter = soc.get("channels", {}).get("twitter", {})
    check("Twitter detected", twitter.get("detected") is True,
          twitter.get("handle", "未检测到"))
    if twitter.get("detected"):
        check("Twitter 有粉丝数", twitter.get("followers") is not None,
              str(twitter.get("followers", "None")))

    youtube = soc.get("channels", {}).get("youtube", {})
    check("YouTube detected", youtube.get("detected") is True,
          youtube.get("handle", "未检测到"))

    # ── PR / News ─────────────────────────────────────────────────────────────
    print(f"\n{BOLD}[PR/News]{RESET}")
    pr_news = sections.get("pr_news", {})
    if pr_news.get("_timed_out"):
        warn("PR/News 超时（非致命，UI 已显示提示）")
    else:
        check("PR/News 有数据或明确 not found",
              "found" in pr_news or "error" in pr_news,
              str(pr_news.get("total_mentions", "—")))

    # ── Funding ───────────────────────────────────────────────────────────────
    print(f"\n{BOLD}[Funding]{RESET}")
    fund = sections.get("funding", {})
    if fund.get("found"):
        check("Funding 找到数据", True,
              fund.get("latest_round", "") + " " + str(fund.get("total_raised_usd", "")))
    else:
        warn("Funding 未找到公开信息（可能 Bootstrapped）")

    # ── Bizmodel ──────────────────────────────────────────────────────────────
    print(f"\n{BOLD}[Bizmodel]{RESET}")
    biz = sections.get("bizmodel", {})
    check("Bizmodel 有数据", biz.get("found") or biz.get("stage"))
    model_type = biz.get("model_type", {})
    if model_type.get("has_open_source"):
        check("has_open_source = true（开源产品识别正确）", True)
    else:
        # Not all products are OSS — only warn if github_oss.found is true
        if gh.get("found"):
            check("has_open_source = true（开源产品识别正确）", False,
                  "GitHub OSS 已找到但 bizmodel 未识别为开源")
        else:
            warn("has_open_source = false（非开源产品或数据未采集）")

    # ── Website first_seen ────────────────────────────────────────────────────
    print(f"\n{BOLD}[Website]{RESET}")
    ws = sections.get("website_analysis", {})
    first_seen = ws.get("first_seen", "N/A")
    check("first_seen 非注册商页面",
          not any(p in str(ws.get("deep_timeline", [{}])[0]).lower()
                  for p in ["dondominio", "godaddy", "parked", "for sale"]),
          f"first_seen = {first_seen}")

    # ── AI Summary ────────────────────────────────────────────────────────────
    print(f"\n{BOLD}[AI Summary]{RESET}")
    ai = sections.get("ai_insights") or sections.get("ai_summary", {})
    check("AI Summary 生成成功",
          bool(ai.get("content") or ai.get("sections")),
          "✓" if ai.get("content") else str(list(ai.keys())[:3]))


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url",    default=DEFAULT_BASE_URL)
    parser.add_argument("--domain", default=DEFAULT_DOMAIN)
    parser.add_argument("--cached", action="store_true",
                        help="跳过分析，直接读已有报告（需提供 --job-id）")
    parser.add_argument("--job-id", default="")
    parser.add_argument("--quick", action="store_true",
                        help="快速模式：仅检查 API 可达性 + 能否启动 job（~5s，用于 pre-push hook）")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    domain = args.domain

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  Analook 冒烟测试{RESET}")
    print(f"  BASE_URL : {base}")
    print(f"  Domain   : {domain}")
    print(f"{BOLD}{'='*60}{RESET}")

    # ── Quick mode: health check only ─────────────────────────────────────────
    if args.quick:
        info("快速模式：检查 API 可达性…")
        try:
            resp = _post(f"{base}/api/analyze", {"url": f"https://{domain}"})
            job_id = resp.get("job_id")
            if job_id:
                print(f"\n{GREEN}{BOLD}  ✅ API 可达，job 已启动（{job_id}）— 推送继续{RESET}\n")
                sys.exit(0)
            else:
                print(f"\n{RED}{BOLD}  ❌ API 响应异常: {resp}{RESET}\n")
                sys.exit(1)
        except Exception as e:
            print(f"\n{RED}{BOLD}  ❌ API 不可达: {e}{RESET}\n")
            sys.exit(1)

    # ── Step 1: 启动分析 or 用已有 job ────────────────────────────────────────
    if args.job_id:
        job_id = args.job_id
        info(f"使用已有 job_id: {job_id}")
    else:
        info(f"POST /api/analyze → {domain}")
        try:
            resp = _post(f"{base}/api/analyze", {"url": f"https://{domain}"})
        except Exception as e:
            print(f"\n{RED}❌ 无法连接到 {base}: {e}{RESET}")
            sys.exit(1)
        job_id = resp.get("job_id")
        if not job_id:
            print(f"\n{RED}❌ 未收到 job_id: {resp}{RESET}")
            sys.exit(1)
        info(f"job_id = {job_id}")

    # ── Step 2: 轮询直到完成 ──────────────────────────────────────────────────
    print()
    elapsed = 0
    report  = None
    while elapsed < JOB_TIMEOUT_S:
        try:
            status = _get(f"{base}/api/status/{job_id}")
        except Exception as e:
            warn(f"轮询失败: {e}")
            time.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S
            continue

        state = status.get("status", "")
        prog  = status.get("progress", {})
        done  = sum(1 for v in prog.values() if v == "done")
        total = len(prog)
        print(f"\r  ⏳ {state} [{done}/{total}] {elapsed}s elapsed   ", end="", flush=True)

        if state in ("completed", "error"):
            print()
            report = status.get("report") or status.get("results")
            break

        time.sleep(POLL_INTERVAL_S)
        elapsed += POLL_INTERVAL_S

    if not report:
        print(f"\n{RED}❌ 超时或无报告 (elapsed={elapsed}s){RESET}")
        sys.exit(1)

    info(f"分析完成，耗时 {elapsed}s")

    # ── Step 3: 运行检查 ──────────────────────────────────────────────────────
    run_checks(report, domain)

    # ── Step 4: 汇总 ─────────────────────────────────────────────────────────
    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = sum(1 for _, p, _ in RESULTS if not p)
    total  = len(RESULTS)

    print(f"\n{BOLD}{'='*60}{RESET}")
    if failed == 0:
        print(f"{GREEN}{BOLD}  ✅ 全部通过 {passed}/{total}{RESET}")
    else:
        print(f"{RED}{BOLD}  ❌ {failed} 项失败，{passed}/{total} 通过{RESET}")
        print(f"\n  失败项：")
        for name, p, detail in RESULTS:
            if not p:
                print(f"    {RED}✗{RESET} {name}" + (f": {detail}" if detail else ""))
    print(f"{BOLD}{'='*60}{RESET}\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
