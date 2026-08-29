import unittest

from bs4 import BeautifulSoup

from modules.pricing import _extract_pricing
from modules.report import _build_references


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


if __name__ == "__main__":
    unittest.main()
