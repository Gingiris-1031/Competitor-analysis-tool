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


def test_public_report_route_uses_the_insforge_aware_loader():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    route = source[source.index('@app.get("/api/report/{job_id}")'):]
    route = route[:route.index("# ─── Public reports gallery")]
    assert "await asyncio.to_thread(_load_persisted_report, job_id)" in route


def test_share_route_reads_insforge_before_legacy_supabase():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    route = source[source.index('@app.get("/api/share/{job_id}")'):]
    route = route[:route.index('@app.get("/report/{job_id}")')]
    assert route.index("get_report_record_sync") < route.index("get_supabase")


def test_report_has_sticky_toc_and_collapsed_keyword_details_in_both_languages():
    traffic = (ROOT / "static/js/render-traffic.js").read_text(encoding="utf-8")
    traffic_zh = (ROOT / "static/zh/js/render-traffic.js").read_text(encoding="utf-8")
    assert "Key SEO conclusions" in traffic
    assert "View all ${kwToShow.length} keywords" in traffic
    assert "SEO 关键结论" in traffic_zh
    assert "查看全部 ${kwToShow.length} 个关键词" in traffic_zh
    for relative_path in ("static/index.html", "static/zh/index.html"):
        html = (ROOT / relative_path).read_text(encoding="utf-8")
        assert ".research-map { position: sticky" in html or ".research-map{position:sticky" in html


def test_bilingual_social_and_media_renderers_hide_unverified_evidence():
    for relative_path in ("static/js/render-social.js", "static/zh/js/render-social.js"):
        script = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "verification?.status === 'verified'" in script
        assert "usefulTweets" in script
    for relative_path in ("static/js/render-pr.js", "static/zh/js/render-pr.js"):
        script = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "verification?.status === 'verified'" in script


def test_sample_report_links_use_current_public_report_ids():
    expected_ids = ("76bb0316", "17323774", "b27d47be")
    stale_ids = ("815b183b", "4d329bdd", "37230091")
    for relative_path in ("static/index.html", "static/zh/index.html"):
        html = (ROOT / relative_path).read_text(encoding="utf-8")
        assert all(f'/report/{report_id}' in html for report_id in expected_ids)
        assert all(f'/report/{report_id}' not in html for report_id in stale_ids)


def test_report_rendering_uses_a_shared_module_registry():
    app_script = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    registry = (ROOT / "static/js/report-modules.js").read_text(encoding="utf-8")

    assert "window.AnalookReportModules.renderFull(report)" in app_script
    assert "window.AnalookReportModules?.renderPartial(partial, _partialRendered)" in app_script
    assert "const fullReportModules" in registry
    assert "const partialReportModules" in registry
    assert "renderPlaybooks" in registry
    assert "renderWebsite(report.sections" not in app_script


def test_field_help_is_bilingual_accessible_and_loaded_on_both_homepages():
    glossary = (ROOT / "static/js/report-glossary.js").read_text(encoding="utf-8")
    component = (ROOT / "static/js/report-field-help.js").read_text(encoding="utf-8")
    app_script = (ROOT / "static/js/app.js").read_text(encoding="utf-8")

    for key in ("organic_search_estimate", "twitter_followers", "product_hunt_votes", "first_seen"):
        assert key in glossary
        assert f'data-field-help="{key}"' in app_script
    assert "aria-expanded" in component
    assert "aria-describedby" in component
    assert "report_field_help_opened" in component
    assert "DataForSEO / SEOReviewTools" in glossary

    for relative_path in ("static/index.html", "static/zh/index.html"):
        html = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "/css/report-field-help.css?v=20260829" in html
        assert "/js/report-glossary.js?v=20260829" in html
        assert "/js/report-field-help.js?v=20260829" in html
        assert "/js/report-modules.js?v=20260829" in html


def test_twitter_summary_does_not_use_an_unrelated_social_channel():
    app_script = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    summary = app_script[app_script.index("function renderSummaryCard"):app_script.index("function fmtNum")]
    assert "social.twitter || social.x" in summary
    assert "twitterChannel.verification?.status === 'verified'" in summary
    assert "Object.values(social).filter" in summary
