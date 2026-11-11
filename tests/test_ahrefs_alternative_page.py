import json
import re
import unittest
from pathlib import Path


PAGE = Path(__file__).parents[1] / "static" / "alternatives" / "ahrefs.html"


def _html():
    return PAGE.read_text(encoding="utf-8")


class AhrefsAlternativePageTest(unittest.TestCase):
    def test_core_search_surface_stays_stable(self):
        html = _html()
        self.assertIn(
            '<link rel="canonical" href="https://www.analook.com/alternatives/ahrefs.html">',
            html,
        )
        self.assertIn("7 Best Ahrefs Alternatives in 2026 (Free + Paid)", html)
        self.assertIn("How we evaluated these Ahrefs alternatives", html)
        self.assertIn('href="/alternatives/"', html)

    def test_article_author_uses_current_gingiris_host(self):
        blocks = re.findall(
            r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
            _html(),
            flags=re.DOTALL,
        )
        documents = [json.loads(block) for block in blocks]
        article = next(doc for doc in documents if doc.get("@type") == "Article")
        self.assertEqual(article["author"]["url"], "https://tools.gingiris.com")

    def test_ctas_have_campaign_and_event_attribution(self):
        html = _html()
        self.assertIn("utm_campaign=seo-ahrefs-alternative", html)
        self.assertIn("surface:'ahrefs_alternatives'", html)
        for placement in (
            "quick_verdict",
            "analook_review",
            "bottom_primary",
            "bottom_pricing",
        ):
            self.assertIn(f"placement:'{placement}'", html)


if __name__ == "__main__":
    unittest.main()
