"""OrcaRouter client — free-tier-first LLM plan shared by all call chains.

OrcaRouter (api.orcarouter.ai) is OpenAI-compatible. Its `orcarouter/free`
aggregate model currently routes to deepseek-v4-flash (the exact model our
paid OpenRouter/DeepSeek plans use) at ZERO cost — verified 2026-07-14:
identical calls left paid_balance untouched on free, billed on deepseek/*.

Every chain keeps its existing paid plans as fallback, so if the free tier
gets rate-limited or discontinued we degrade to today's behavior untouched.
Set ORCAROUTER_API_KEY to enable; unset = this plan is skipped entirely.
"""
import logging
import os

import httpx

log = logging.getLogger(__name__)

_BASE = "https://api.orcarouter.ai/v1/chat/completions"
_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def _key() -> str:
    return (os.environ.get("ORCAROUTER_API_KEY") or "").strip()


def _model() -> str:
    # orcarouter/free = $0 tier (routes to deepseek-v4-flash as of 2026-07).
    # Paid model ids (deepseek/*, anthropic/*, ...) also work via env override.
    return (os.environ.get("ORCAROUTER_MODEL") or "orcarouter/free").strip()


async def try_orca(messages: list, max_tokens: int = 4000,
                   temperature: float = 0.5, title: str = "Analook") -> dict | None:
    """One attempt against OrcaRouter's free tier. Returns
    {"success": True, "content": str, "source": "OrcaRouter (<model>)"}
    or None so the caller fails over to its existing paid plans."""
    key = _key()
    if not key:
        return None
    model = _model()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.post(
                _BASE,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json",
                         "HTTP-Referer": "https://www.analook.com",
                         "X-Title": title},
                json={"model": model, "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens},
            )
            if resp.status_code != 200:
                log.warning("OrcaRouter %s: HTTP %d (%s)", model,
                            resp.status_code, resp.text[:150])
                return None
            data = resp.json()
            # Final answer only — deepseek-v4-flash puts chain-of-thought in a
            # separate reasoning_content field, which we deliberately ignore.
            msg = ((data.get("choices") or [{}])[0] or {}).get("message", {}) or {}
            content = (msg.get("content") or "").strip()
            if content:
                return {"success": True, "content": content,
                        "source": f"OrcaRouter ({data.get('model', model)})"}
            log.warning("OrcaRouter %s: empty content", model)
    except Exception as e:
        log.warning("OrcaRouter %s failed, failing over: %s", model, str(e)[:120])
    return None
