"""Report-language context for analysis modules.

Modules that generate user-facing report text (funding, bizmodel, traffic_peaks,
growth_strategy, github_oss, ...) run during the analysis phase, BEFORE report.py
assembles the report. Threading a `lang` argument through every one of their
functions is invasive, so instead we stash the active report language in a
ContextVar that app.py sets once at the start of _run_analysis. Each module wraps
its user-facing strings in _T(en, zh), which reads that ContextVar.

ContextVars propagate across asyncio tasks (asyncio.gather copies the parent
context into each child), so a single set() at the task root covers the whole
parallel analysis fan-out.

Default is "zh" so nothing changes for Chinese reports; English reports get the
English branch and stop leaking Chinese into EN output (TAAFT-style purity).
"""
import contextvars

_report_lang: contextvars.ContextVar = contextvars.ContextVar(
    "analook_report_lang", default="zh"
)


def set_report_lang(lang) -> None:
    """Call once at the start of an analysis run with the report's language."""
    _report_lang.set("en" if (lang or "").lower().startswith("en") else "zh")


def report_lang() -> str:
    return _report_lang.get()


def _T(en: str, zh: str) -> str:
    """Return `en` for English reports, `zh` otherwise."""
    return en if _report_lang.get() == "en" else zh
