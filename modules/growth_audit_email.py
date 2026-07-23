"""Transactional notification for completed Growth Audits."""
import html
import logging
import os

import httpx

log = logging.getLogger(__name__)

# The verified Resend sending domain is mail.analook.com. Keep the sender
# aligned with that domain so completion notifications are accepted by Resend.
_FROM = "Analook <notify@mail.analook.com>"


def _copy(product_name: str, report_url: str, lang: str) -> tuple[str, str]:
    product = html.escape(product_name or "your product")
    url = html.escape(report_url, quote=True)
    if lang == "zh":
        subject = f"你的 Analook 增长诊断报告已完成：{product_name}"
        title = "你的增长诊断报告已准备好"
        body = f"{product} 的执行摘要、完整诊断和 30 天行动计划现已生成。"
        cta = "查看完整报告"
    else:
        subject = f"Your Analook Growth Audit is ready: {product_name}"
        title = "Your Growth Audit is ready"
        body = f"The executive summary, full diagnosis, and 30-day action plan for {product} are ready to review."
        cta = "Open your report"
    email_html = f"""<!doctype html><html><body style=\"margin:0;background:#f7f4ec;font-family:-apple-system,Arial,sans-serif;color:#1d2b25\">
<main style=\"max-width:560px;margin:32px auto;padding:36px;background:#fffdfa;border:1px solid #d7ded4;border-radius:20px\">
  <p style=\"margin:0 0 24px;font:italic 28px Georgia,serif\">Analook</p>
  <h1 style=\"font-size:25px;margin:0 0 12px\">{title}</h1>
  <p style=\"color:#5c6e63;line-height:1.65\">{body}</p>
  <a href=\"{url}\" style=\"display:inline-block;margin-top:14px;padding:13px 22px;background:#183b2a;border-radius:999px;color:#fff;text-decoration:none;font-weight:700\">{cta} →</a>
  <p style=\"margin:28px 0 0;color:#87958b;font-size:12px\">Analook · Gingiris Growth Framework</p>
</main></body></html>"""
    return subject, email_html


async def send_growth_audit_ready_email(
    *, to_email: str, product_name: str, job_id: str, lang: str = "zh"
) -> bool:
    """Best-effort only: report delivery must never depend on email delivery."""
    key = (os.environ.get("RESEND_API_KEY") or "").strip()
    if not key or not to_email:
        return False
    report_url = f"https://www.analook.com/share/audit/{job_id}"
    subject, email_html = _copy(product_name, report_url, lang)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "from": _FROM,
                    "to": [to_email],
                    "subject": subject,
                    "html": email_html,
                    "tags": [
                        {"name": "campaign", "value": "growth_audit_complete"},
                        {"name": "audit_id", "value": job_id},
                    ],
                },
            )
        if response.status_code not in (200, 201):
            log.warning("Growth audit email failed: HTTP %s", response.status_code)
            return False
        return True
    except Exception as exc:
        log.warning("Growth audit email failed: %s", exc)
        return False
