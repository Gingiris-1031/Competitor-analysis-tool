import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EN = ROOT / "static/open-source-growth-attribution.html"
ZH = ROOT / "static/zh/open-source-growth-attribution.html"


class OssAttributionLandingTests(unittest.TestCase):
    def test_bilingual_landing_pages_have_matching_product_flow(self):
        for path, lang, alternate in (
            (EN, "en", "/zh/open-source-growth-attribution.html"),
            (ZH, "zh-CN", "/open-source-growth-attribution.html"),
        ):
            html = path.read_text(encoding="utf-8")
            self.assertIn(f'<html lang="{lang}">', html)
            self.assertIn('id="repo-form"', html)
            self.assertIn('id="repo-input"', html)
            self.assertIn("oss-attribution-landing.js", html)
            self.assertIn(alternate, html)
            self.assertIn("growth-audit.html", html)
            self.assertIn("pricing.html", html)

    def test_landing_pages_include_valid_webapp_and_faq_schema(self):
        pattern = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
        for path in (EN, ZH):
            payload = json.loads(pattern.search(path.read_text(encoding="utf-8")).group(1))
            types = {item["@type"] for item in payload["@graph"]}
            self.assertTrue({"WebApplication", "FAQPage"} <= types)

    def test_openmontage_preview_uses_original_evidence_links(self):
        for path in (EN, ZH):
            html = path.read_text(encoding="utf-8")
            self.assertIn("https://news.ycombinator.com/item?id=48616398", html)
            self.assertIn("reddit.com/r/ClaudeCode", html)
            self.assertIn("youtube.com/watch", html)

    def test_sitemap_and_social_card_include_landing_page(self):
        sitemap = (ROOT / "static/sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("https://www.analook.com/open-source-growth-attribution.html", sitemap)
        self.assertIn("https://www.analook.com/zh/open-source-growth-attribution.html", sitemap)
        self.assertGreater((ROOT / "static/assets/og/oss-attribution.png").stat().st_size, 10_000)

    def test_conversion_events_and_source_handoff_are_present(self):
        landing_js = (ROOT / "static/js/oss-attribution-landing.js").read_text(encoding="utf-8")
        app_js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
        self.assertIn("oss_lp_viewed", landing_js)
        self.assertIn("oss_repo_submitted", landing_js)
        self.assertIn("oss_repo=", landing_js)
        self.assertIn("params.get('repo') || params.get('oss_repo')", landing_js)
        self.assertIn("candidate = `https://github.com/${value}`", landing_js)
        self.assertIn("document.querySelectorAll('.faq-action')", landing_js)
        self.assertIn("url.searchParams.set('oss_repo', repo)", landing_js)
        self.assertIn("normalizeGithubRepo", app_js)
        self.assertIn("Analyze OSS growth", app_js)
        self.assertIn("正在还原开源项目增长证据", app_js)
        for event in (
            "oss_main_product_arrived",
            "oss_preview_completed",
            "oss_full_report_unlocked",
            "oss_single_report_checkout_started",
            "oss_pro_checkout_started",
            "oss_to_growth_audit_clicked",
        ):
            self.assertIn(event, app_js)

    def test_homepages_feature_prominent_bilingual_entry(self):
        en_home = (ROOT / "static/index.html").read_text(encoding="utf-8")
        zh_home = (ROOT / "static/zh/index.html").read_text(encoding="utf-8")
        self.assertIn('href="/open-source-growth-attribution.html"', en_home)
        self.assertIn("New · Open-source Growth Attribution", en_home)
        self.assertIn('href="/zh/open-source-growth-attribution.html"', zh_home)
        self.assertIn("新功能 · 开源项目增长归因", zh_home)
        self.assertIn("oss_homepage_entry_clicked", en_home)
        self.assertIn("oss_homepage_entry_clicked", zh_home)
        for html in (en_home, zh_home):
            self.assertIn('id="hero-title"', html)
            self.assertIn('id="hero-copy"', html)
            self.assertIn('id="hero-note"', html)
            self.assertIn('id="oss-homepage-entry"', html)

    def test_first_oss_value_is_not_blocked_by_account_or_referral_modals(self):
        auth_js = (ROOT / "static/js/auth.js").read_text(encoding="utf-8")
        referral_js = (ROOT / "static/js/referral-modal.js").read_text(encoding="utf-8")
        self.assertIn("ossRepo && ossValueCompleted !== ossRepo", auth_js)
        self.assertIn("new URLSearchParams(window.location.search).get('oss_repo')", referral_js)
        self.assertIn("你是从哪里", referral_js)
        self.assertIn("继续 →", referral_js)

    def test_faq_next_steps_have_bilingual_ctas_and_tracking(self):
        en = EN.read_text(encoding="utf-8")
        zh = ZH.read_text(encoding="utf-8")
        self.assertIn("Run full competitor analysis →", en)
        self.assertIn("Build a 30-day growth plan →", en)
        self.assertIn("生成完整竞品报告 →", zh)
        self.assertIn("生成 30 天增长计划 →", zh)
        for html in (en, zh):
            self.assertIn("oss_to_competitor_analysis_clicked", html)
            self.assertIn("oss_to_growth_audit_clicked", html)
            self.assertIn("utm_campaign=faq_next_step", html)


if __name__ == "__main__":
    unittest.main()
