import unittest

from app import _detect_report_lang


class AnalysisLanguageTests(unittest.TestCase):
    def test_explicit_english_and_chinese_are_independent(self):
        self.assertEqual("en", _detect_report_lang("en", None, "/zh/", "zh-CN"))
        self.assertEqual("zh", _detect_report_lang("zh", None, "/", "en-US"))

    def test_route_and_header_fallbacks(self):
        self.assertEqual("zh", _detect_report_lang(None, None, "https://analook.com/zh/", "en-US"))
        self.assertEqual("en", _detect_report_lang(None, None, "https://analook.com/", "en-US"))
        self.assertEqual("en", _detect_report_lang(None, None, None, None))


if __name__ == "__main__":
    unittest.main()
