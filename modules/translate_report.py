"""Report translation module — one-click EN⇄ZH toggle for generated reports.

Iris 2026-07-07 feature request: an English report should switch to Chinese
(and back) with one click, without re-running the whole analysis pipeline.

Design:
- Translate-not-regenerate: a full re-run costs ~2 min + API spend; a
  DeepSeek translation pass costs ~$0.01 and ~15s per document.
- Persist-once: translations are stored under report["_translations"][lang]
  and written back to disk + Supabase, so each report is translated at most
  once per language. Subsequent toggles are instant cache hits.
- Markdown-safe: the prompt pins down everything that must NOT change —
  links, numbers, code spans, emoji, [fact:*] citation tags, <sup> badges.
"""
from __future__ import annotations

import asyncio
import logging
import re

log = logging.getLogger(__name__)

_MAX_DOC_CHARS = 24000  # per-document guard; reports are typically 8-20K


def _translate_prompt(md: str, target: str) -> str:
    lang_name = "Simplified Chinese (简体中文)" if target == "zh" else "fluent natural English"
    return f"""You are a professional technical translator. Translate the Markdown report below into {lang_name}.

STRICT RULES — violating any of these corrupts the report:
1. Preserve ALL Markdown structure exactly: heading levels, tables (same number of columns/rows), lists, blockquotes, horizontal rules, bold/italic markers.
2. Do NOT translate or alter: URLs, links targets, code spans/blocks, numbers, prices, dates, product names, brand names, @handles, r/subreddit names, emoji, HTML tags (e.g. <sup ...>...</sup>), citation tags like [fact:traffic.monthly_organic_visits].
3. Translate ONLY the natural-language prose: headings text, sentences, table cell text (keep numeric cells untouched).
4. Keep the translation faithful — no summarizing, no additions, no opinions.
5. Output ONLY the translated Markdown. No preamble, no ``` fences around the whole document.

--- DOCUMENT START ---
{md}
--- DOCUMENT END ---"""


async def translate_markdown(md: str, target: str) -> str:
    """Translate one markdown document. Returns translated text, or raises."""
    if not md or not md.strip():
        return md
    from .ai_summary import _call_llm
    clipped = md[:_MAX_DOC_CHARS]
    result = await _call_llm(_translate_prompt(clipped, target))
    if not (isinstance(result, dict) and result.get("success") and result.get("content")):
        raise RuntimeError(f"translation LLM call failed: {str(result)[:200]}")
    out = result["content"].strip()
    # Strip a stray wrapping code fence if the model added one anyway
    if out.startswith("```") and out.endswith("```"):
        out = re.sub(r"^```[a-zA-Z]*\n?", "", out)
        out = re.sub(r"\n?```$", "", out)
    return out


async def translate_docs(docs: dict, target: str) -> dict:
    """Translate a dict of {key: markdown} concurrently. Missing/empty docs
    pass through unchanged. Raises if ANY translation fails (partial
    translations would leave the toggle in a confusing half-state)."""
    keys = [k for k, v in docs.items() if isinstance(v, str) and v.strip()]
    results = await asyncio.gather(*(translate_markdown(docs[k], target) for k in keys))
    out = dict(docs)
    for k, translated in zip(keys, results):
        out[k] = translated
    return out
