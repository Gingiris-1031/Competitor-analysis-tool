import unittest

from bs4 import BeautifulSoup

from modules.pricing import _extract_pricing
from modules.report import _build_references
from modules.benchmarks import extract_public_signals
from modules.pr_news import _filter_mentions_by_identity
from modules.website import _extract_social_links


class ReportTrustTests(unittest.TestCase):
    def test_pricing_does_not_treat_generic_free_copy_as_a_plan(self):
        html = "<main><h1>Build better software</h1><p>Start for free today.</p></main>"
        result = _extract_pricing(BeautifulSoup(html, "html.parser"), "Build better software\nStart for free today.", "https://example.com", "Example")
        self.assertFalse(result["found"])
        self.assertFalse(result["tiers"])
        self.assertFalse(result["free_plan"])

    def test_references_include_only_real_original_links(self):
        refs = _build_references({
            "website_analysis": {"deep_timeline": [{"archive_url": "https://web.archive.org/web/20200101/https://example.com"}]},
            "social_media": {"channels": {"twitter": {"detected": True, "url": "https://x.com/example"}}},
            "pricing": {"found": True, "source_url": "https://example.com/pricing"},
            "github_oss": {"stars": 1, "repo_url": "https://github.com/example/repo"},
        }, "2026-08-29T00:00:00", "en")
        self.assertEqual({r["url"] for r in refs if r.get("url")}, {
            "https://web.archive.org/web/20200101/https://example.com",
            "https://x.com/example",
            "https://example.com/pricing",
            "https://github.com/example/repo",
        })

    def test_social_scoring_counts_only_verified_detected_channels(self):
        signals = extract_public_signals({
            "social": {"channels": {
                "twitter": {"detected": True, "verification": {"status": "unverified"}},
                "linkedin": {"detected": None, "url": "https://linkedin.com/company/guess"},
                "github": {"detected": True, "verification": {"status": "verified"}},
                "tiktok": {"detected": False},
            }}
        })
        self.assertEqual(signals["social_channels"], 1)

    def test_short_brand_media_requires_domain_or_full_dotted_name(self):
        items = [
            {"title": "Soku launches a cosmetics collection", "url": "https://news.example/cosmetics"},
            {"title": "How soku.ai helps creators", "url": "https://news.example/soku-ai"},
            {"title": "Launch notes", "url": "https://soku.ai/blog/launch"},
        ]
        kept = _filter_mentions_by_identity(items, "soku.ai", "soku.ai")
        self.assertEqual(len(kept), 2)
        self.assertTrue(all(i["verification"]["status"] == "verified" for i in kept))

    def test_social_link_extractor_preserves_provenance_and_rejectable_body_weight(self):
        soup = BeautifulSoup('''
            <html><body>
                <a href="https://x.com/customer">Customer story</a>
                <footer><a href="https://x.com/producthq">X</a></footer>
            </body></html>
        ''', "html.parser")
        links = _extract_social_links(soup, "https://example.com")
        self.assertEqual(links["twitter"]["handle"], "producthq")
        self.assertEqual(links["twitter"]["weight"], 2)
        self.assertEqual(links["twitter"]["source"], "footer_link")


if __name__ == "__main__":
    unittest.main()
