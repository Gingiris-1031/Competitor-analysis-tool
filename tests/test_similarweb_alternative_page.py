import json
import re
import unittest
from pathlib import Path


PAGE = Path(__file__).parents[1] / "static" / "alternatives" / "similarweb.html"


def _html():
    return PAGE.read_text(encoding="utf-8")


class SimilarwebAlternativePageTest(unittest.TestCase):
    def test_core_search_surface_stays_stable(self):
        html = _html()
        self.assertIn('<link rel="canonical" href="https://www.analook.com/alternatives/similarweb.html">', html)
        self.assertIn("7 Best SimilarWeb Alternatives in 2026 (Free + Paid)", html)
        self.assertIn("Best Free SimilarWeb Alternatives: Quick Verdict", html)

    def test_json_ld_is_valid_and_fresh(self):
        blocks = re.findall(
            r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
            _html(),
            flags=re.DOTALL,
        )
        self.assertGreaterEqual(len(blocks), 5)
        documents = [json.loads(block) for block in blocks]
        article = next(doc for doc in documents if doc.get("@type") == "Article")
        self.assertEqual(article["dateModified"], "2026-09-18")

    def test_evidence_and_cta_regressions(self):
        html = _html()
        self.assertIn("https://account.similarweb.com/packages/marketing", html)
        self.assertIn("https://support.similarweb.com/hc/en-us/articles/33816102143133-Using-AI-Studio", html)
        self.assertIn("https://ahrefs.com/big-data", html)
        self.assertIn("seo_cta_click", html)
        self.assertIn("surface:'similarweb_alternatives'", html)

        stale_or_unverifiable = [
            "Business plan starts at $125/month",
            "only one with a remote MCP server",
            "zero LLM integration",
            "high-upvote comment",
            "r/SaaS, Q3 2026",
            "23% of SimilarWeb's cost",
        ]
        for claim in stale_or_unverifiable:
            self.assertNotIn(claim, html)


if __name__ == "__main__":
    unittest.main()
