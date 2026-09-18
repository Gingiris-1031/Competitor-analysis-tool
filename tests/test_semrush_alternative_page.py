import json
import re
import unittest
from pathlib import Path


PAGE = Path(__file__).parents[1] / "static" / "alternatives" / "semrush.html"


def _html():
    return PAGE.read_text(encoding="utf-8")


class SemrushAlternativePageTest(unittest.TestCase):
    def test_core_search_surface_stays_stable(self):
        html = _html()
        self.assertIn(
            '<link rel="canonical" href="https://www.analook.com/alternatives/semrush.html">',
            html,
        )
        self.assertIn("7 Best SEMrush Alternatives in 2026 (Free + Paid)", html)
        self.assertIn("Best Free SEMrush Alternatives: Quick Verdict", html)

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
        self.assertEqual(article["author"]["url"], "https://tools.gingiris.com")

    def test_evidence_and_cta_regressions(self):
        html = _html()
        self.assertIn(
            "https://www.semrush.com/kb/1547-seo-toolkit-pricing-and-plans", html
        )
        self.assertIn("https://www.semrush.com/mcp/", html)
        self.assertIn("seo_cta_click", html)
        self.assertIn("surface:'semrush_alternatives'", html)

        stale_or_unverifiable = [
            "SEMrush has no MCP server",
            "No LLM / MCP integration",
            "Community consensus",
            "community-validated",
            "$125+/mo",
            "~80% of what a lean founder team",
            "60% of SEMrush features at 35% price",
        ]
        for claim in stale_or_unverifiable:
            self.assertNotIn(claim, html)


if __name__ == "__main__":
    unittest.main()
