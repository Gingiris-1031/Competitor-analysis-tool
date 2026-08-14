"""PostHog tracking for Analook — single shared client + helpers.

One module-level PostHog client is shared by:
  - modules/mcp_app.py (MCP tool-call instrumentation via posthog.mcp)
  - data-source modules (``data_source_queried`` events)
so there is exactly one background flush queue per process.

Configured purely from environment (``POSTHOG_API_KEY`` / ``POSTHOG_HOST``),
which on Fly are set via ``flyctl secrets set`` — matching the rest of the app,
which reads config exclusively via ``os.environ.get``.
"""
import os
import time

from posthog import Posthog

_posthog = Posthog(
    # ``project_api_key`` is the supported constructor argument in the
    # PostHog Python SDK.  ``api_key`` is an instance attribute, not a
    # constructor keyword, in the currently resolved SDK version.
    project_api_key=os.environ.get("POSTHOG_API_KEY", ""),
    host=os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com"),
)


def get_client():
    """Return the shared PostHog client (used by posthog.mcp.instrument)."""
    return _posthog


def track_data_source(source, fn_name, latency_ms, success, extra=None):
    """Fire-and-forget ``data_source_queried`` event. No-op when no API key.

    The ``source`` property is what powers the "which external API do clients
    actually rely on" dashboard panel.
    """
    if not _posthog.api_key:
        return
    props = {
        "source": source,
        "fn_name": fn_name,
        "latency_ms": latency_ms,
        "success": success,
        "$lib": "analook-backend",
    }
    if extra:
        props.update(extra)
    try:
        _posthog.capture(
            distinct_id="analook-backend",
            event="data_source_queried",
            properties=props,
        )
    except Exception:
        # Tracking must never break the analysis pipeline.
        pass


def timeit():
    """Return an ``elapsed_ms()`` callable.

    Usage::

        elapsed = timeit()
        ... do work ...
        track_data_source("DataForSEO", "foo", elapsed(), True)
    """
    start = time.monotonic()
    return lambda: int((time.monotonic() - start) * 1000)


def shutdown():
    """Flush + stop the shared client on app shutdown."""
    try:
        _posthog.shutdown()
    except Exception:
        pass
