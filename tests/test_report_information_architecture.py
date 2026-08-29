from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _report_fragment(path: Path) -> str:
    html = path.read_text(encoding="utf-8")
    return html[html.index('id="report-section"'):html.index('id="post-report-cta"')]


def test_decision_chapter_is_first_and_only_open_chapter_in_both_languages():
    for relative_path in ("static/index.html", "static/zh/index.html"):
        report = _report_fragment(ROOT / relative_path)
        first_details = report.index('<details class="report-chapter" open>')
        first_action = report.index('id="chapter-actions"')
        first_positioning = report.index('id="chapter-positioning"')

        assert first_details < first_action < first_positioning
        assert report.count('<details class="report-chapter" open>') == 1


def test_research_map_uses_decision_first_order():
    script = (ROOT / "static/js/render-research-map.js").read_text(encoding="utf-8")
    assert script.index("['chapter-actions', '01'") < script.index("['chapter-positioning', '02'")
    assert "['chapter-evidence', '05'" in script


def test_summary_card_uses_light_brand_components():
    script = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    summary = script[script.index("function renderSummaryCard"):]
    assert 'class="card-cream p-5 mb-6"' in summary
    assert 'class="card-cream-subtle p-3"' in summary
    assert 'class="bg-gray-900' not in summary


def test_thesis_card_uses_light_brand_palette():
    script = (ROOT / "static/js/render-thesis.js").read_text(encoding="utf-8")
    assert "var(--warm-border)" in script
    assert "var(--ink)" in script
    assert "#16161A" not in script
