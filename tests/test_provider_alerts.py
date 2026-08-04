"""Fast, network-free checks for provider monitoring and report fallbacks."""
import unittest
from unittest.mock import AsyncMock, patch

from modules import provider_alerts
from modules.dataforseo import _analyze_domain_uncached
from modules.traffic import _fetch_dataforseo_metrics, _fetch_seoreviewtools


class ProviderAlertsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        provider_alerts._MEMORY_STATE.clear()

    async def test_critical_alert_is_sent_once_then_deduplicated(self):
        report = {
            "providers": [
                {"provider": "DataForSEO", "status": "exhausted", "note": "balance below zero"},
                {"provider": "GitHub PAT", "status": "missing", "note": "Env var not set"},
            ],
            "summary": {},
        }
        with patch("modules.api_balances.check_all", AsyncMock(return_value=report)), \
             patch("modules.provider_alerts._store", return_value=None), \
             patch("modules.provider_alerts._send_email", AsyncMock(return_value=True)) as send:
            first = await provider_alerts.check_and_alert(force=True)
            second = await provider_alerts.check_and_alert(force=True)

        self.assertTrue(first["email_sent"])
        self.assertEqual(["DataForSEO"], [x["provider"] for x in first["alert_candidates"]])
        self.assertFalse(second["email_sent"])
        self.assertEqual([], second["alert_candidates"])
        self.assertEqual(1, send.await_count)

    async def test_dry_run_never_sends_or_persists(self):
        report = {"providers": [{"provider": "DataForSEO", "status": "exhausted", "note": "balance below zero"}], "summary": {}}
        with patch("modules.api_balances.check_all", AsyncMock(return_value=report)), \
             patch("modules.provider_alerts._store", return_value=None), \
             patch("modules.provider_alerts._send_email", AsyncMock(return_value=True)) as send:
            result = await provider_alerts.check_and_alert(force=True, dry_run=True)

        self.assertEqual("DataForSEO", result["alert_candidates"][0]["provider"])
        send.assert_not_awaited()
        self.assertEqual({}, provider_alerts._MEMORY_STATE)

    async def test_critical_provider_state_stops_paid_seo_calls(self):
        provider_alerts._MEMORY_STATE["DataForSEO"] = {"severity": "critical"}
        provider_alerts._MEMORY_STATE["SEOReviewTools"] = {"severity": "critical"}

        seo = await _analyze_domain_uncached("example.com")
        traffic = await _fetch_dataforseo_metrics("example.com")
        srt = await _fetch_seoreviewtools("example.com")

        self.assertIn("temporarily unavailable", seo["error"])
        self.assertIn("temporarily unavailable", traffic["error"])
        self.assertIn("temporarily unavailable", srt["error"])


if __name__ == "__main__":
    unittest.main()
