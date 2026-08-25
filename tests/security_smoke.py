"""
Analook 安全冒烟测试 — 验证生产环境的安全加固(commit b39a8ea)已生效。
零成本、无鉴权、无需 TestSprite credits。部署后跑,全绿才算安全加固上线。

用法:
  python tests/security_smoke.py                         # 默认 https://www.analook.com
  BASE_URL=https://staging... python tests/security_smoke.py

检查项:
  1. /docs /redoc /openapi.json 在生产返回 404(Swagger 不暴露;EXPOSE_API_DOCS 未设时)
  2. 6 个安全响应头存在(HSTS / X-Frame-Options / X-Content-Type-Options / CSP / Referrer-Policy / Permissions-Policy)
  3. GET /mcp → MCP 文档；POST /mcp → 307 保留请求体并进入协议端点
  4. legacy /unlock → 308 到 pricing
"""
import os
import sys
import urllib.request
import urllib.error

BASE = os.environ.get("BASE_URL", "https://www.analook.com").rstrip("/")
GREEN, RED, YEL, RST = "\033[92m", "\033[91m", "\033[93m", "\033[0m"

results = []


def _req(path, method="GET", follow=True):
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    op = urllib.request if follow else urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(BASE + path, method=method,
                                 headers={"User-Agent": "analook-security-smoke"})
    try:
        r = op.urlopen(req, timeout=15) if follow else op.open(req, timeout=15)
        return r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}


def check(name, ok, detail=""):
    results.append(ok)
    mark = f"{GREEN}✓{RST}" if ok else f"{RED}✗{RST}"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))


print(f"\nAnalook 安全冒烟 — {BASE}\n" + "=" * 56)

# 1. API docs 在生产应关闭
print("\n[API docs 关闭]")
for p in ("/docs", "/redoc", "/openapi.json"):
    code, _ = _req(p)
    check(f"{p} 返回 404（不暴露）", code == 404, f"实际 {code}")

# 2. 安全响应头
print("\n[安全响应头]")
_, hdrs = _req("/")
for h in ("strict-transport-security", "x-frame-options", "x-content-type-options",
          "content-security-policy", "referrer-policy", "permissions-policy"):
    check(f"{h} 存在", h in hdrs, hdrs.get(h, "缺")[:40])

# 3. MCP 浏览器落地页与协议重定向
print("\n[MCP]")
code, hdrs = _req("/mcp", method="GET", follow=False)
check("GET /mcp → 308 MCP 文档", code == 308 and "/docs/mcp.html" in (hdrs.get("location", "")),
      f"{code} → {hdrs.get('location', '')}")
code, hdrs = _req("/mcp", method="POST", follow=False)
check("POST /mcp → 307 协议端点", code == 307 and "/mcp/" in (hdrs.get("location", "")),
      f"{code} → {hdrs.get('location', '')}")

# 4. 旧转化路径保留历史链接信号
print("\n[Legacy SEO redirects]")
code, hdrs = _req("/unlock", method="GET", follow=False)
check("/unlock → 308 pricing", code == 308 and "/pricing.html" in (hdrs.get("location", "")),
      f"{code} → {hdrs.get('location', '')}")

# 汇总
passed = sum(results)
total = len(results)
color = GREEN if passed == total else RED
print("\n" + "=" * 56)
print(f"{color}结果: {passed}/{total} 通过{RST}\n")
sys.exit(0 if passed == total else 1)
