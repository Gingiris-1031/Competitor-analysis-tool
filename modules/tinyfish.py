"""TinyFish Fetch API integration — managed browser rendering for analook.

Production-grade web fetching for AI agents: Chromium-rendered, stealth
profiles, rotating proxies. Drop-in replacement for httpx.get when the
target page is JS-heavy (pricing pages, SPAs, modern SaaS landing pages).

Free Fetch endpoint (no credit card). Auth via X-API-Key header.

Graceful degradation: if TINYFISH_API_KEY is not set, all functions return
None / empty so callers can fall back to existing scraping. No exceptions
bubble out unless the network layer itself is broken.

Docs: https://docs.tinyfish.ai/
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

_API_KEY = os.environ.get("TINYFISH_API_KEY", "").strip()
_FETCH_URL = "https://api.fetch.tinyfish.ai"
_BATCH_LIMIT = 10  # API hard limit per request


def is_available() -> bool:
    """Whether TINYFISH_API_KEY is configured. Use to gate calls in callers."""
    return bool(_API_KEY)


async def fetch_html(url: str, timeout: float = 20.0) -> Optional[dict]:
    """Fetch a single URL and return Chromium-rendered HTML + metadata.

    Returns a dict with keys: url, final_url, title, description, language,
    text (HTML), format. None if the API is unavailable or the fetch failed.
    """
    if not _API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                _FETCH_URL,
                headers={
                    "X-API-Key": _API_KEY,
                    "Content-Type": "application/json",
                },
                json={"urls": [url], "format": "html"},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            results = data.get("results") or []
            if not results:
                return None
            r = results[0]
            if not r.get("text"):
                return None
            return r
    except Exception:
        return None


async def fetch_markdown(url: str, timeout: float = 20.0) -> Optional[str]:
    """Fetch a single URL and return clean markdown text. None on failure."""
    if not _API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                _FETCH_URL,
                headers={
                    "X-API-Key": _API_KEY,
                    "Content-Type": "application/json",
                },
                json={"urls": [url]},  # default format is markdown
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            results = data.get("results") or []
            if not results:
                return None
            text = results[0].get("text", "")
            return text or None
    except Exception:
        return None


async def fetch_batch_html(urls: list, timeout: float = 30.0) -> dict:
    """Batch fetch up to 10 URLs in parallel. Returns {url: html_dict}.

    URLs that failed are simply omitted from the result. Empty dict if
    the API key is missing or the whole request failed.
    """
    if not _API_KEY or not urls:
        return {}
    urls = urls[:_BATCH_LIMIT]
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                _FETCH_URL,
                headers={
                    "X-API-Key": _API_KEY,
                    "Content-Type": "application/json",
                },
                json={"urls": urls, "format": "html"},
            )
            if resp.status_code != 200:
                return {}
            data = resp.json()
            out = {}
            for r in data.get("results") or []:
                if r.get("text"):
                    # Index by the requested URL (not final_url after redirects)
                    out[r.get("url", "")] = r
            return out
    except Exception:
        return {}
