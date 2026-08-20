import unittest

from modules.oss_growth_attribution import (
    _classify_channel,
    _evidence_score,
    _normalize_result,
    _published_date,
)
from modules.report import _oss_attribution_markdown


class OssGrowthAttributionTests(unittest.TestCase):
    def test_channel_classification(self):
        self.assertEqual(_classify_channel("https://www.reddit.com/r/test/1"), "reddit")
        self.assertEqual(_classify_channel("https://youtu.be/demo"), "youtube")
        self.assertEqual(_classify_channel("https://qiita.com/a/items/1"), "developer_media")

    def test_date_normalization(self):
        self.assertEqual(_published_date("Published 2026/6/22"), "2026-06-22")
        self.assertEqual(_published_date("2026年7月5日"), "2026-07-05")

    def test_rejects_unrelated_result(self):
        row = {"title": "Another project", "url": "https://example.com/post", "description": "nothing relevant"}
        self.assertIsNone(_normalize_result(row, "OpenMontage", "editorial"))

    def test_normalizes_original_content(self):
        row = {
            "title": "OpenMontage install guide",
            "url": "https://www.youtube.com/watch?v=abc",
            "description": "Published 2026-06-22",
        }
        item = _normalize_result(row, "OpenMontage", "video")
        self.assertEqual(item["channel"], "youtube")
        self.assertEqual(item["format"], "tutorial")
        self.assertGreaterEqual(_evidence_score(item, "OpenMontage"), 6)

    def test_rejects_same_name_content_from_a_different_github_repo(self):
        row = {
            "title": "OpenAgents platform",
            "url": "https://github.com/xlang-ai/openagents",
            "description": "OpenAgents install guide",
        }
        self.assertIsNone(
            _normalize_result(
                row,
                "openagents",
                "community",
                canonical_owner="openagents-org",
                canonical_repo="openagents",
            )
        )

    def test_keeps_content_from_the_canonical_github_repo(self):
        row = {
            "title": "OpenAgents release notes",
            "url": "https://github.com/openagents-org/openagents/releases/tag/v1",
            "description": "OpenAgents release",
        }
        item = _normalize_result(
            row,
            "openagents",
            "community",
            canonical_owner="openagents-org",
            canonical_repo="openagents",
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["channel"], "github")

    def test_markdown_export_includes_original_link_and_caveat(self):
        attribution = {
            "available": True,
            "source_note": "Observed links; inferred impact.",
            "uncertainty": "±10–15 pp",
            "stages": [{"period": "2026-06", "label": "Breakout", "signal": "Peak", "confidence": "high"}],
            "key_content": [{"channel": "reddit", "title": "Demo", "url": "https://reddit.com/demo", "hook": "Free OSS", "evidence_score": 7, "confidence": "high"}],
            "unsupported_channels": ["product_hunt"],
        }
        markdown = _oss_attribution_markdown(attribution, "en")
        self.assertIn("https://reddit.com/demo", markdown)
        self.assertIn("±10–15 pp", markdown)
        self.assertIn("product_hunt", markdown)


if __name__ == "__main__":
    unittest.main()
