import unittest
from unittest.mock import AsyncMock, patch

import app


class PublicReportsCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        app._public_reports_cache["ts"] = 0.0
        app._public_reports_cache["data"] = None

    async def test_shared_cache_bypasses_database_projection(self):
        cached = {"reports": [{"id": "cached-1", "domain": "cached.example"}]}
        with patch("modules.insforge_client.get_internal_cache", AsyncMock(return_value=cached)), \
             patch("modules.insforge_client.get_public_report_gallery_rows", AsyncMock()) as rows:
            result = await app._public_reports_data()

        self.assertEqual(cached["reports"], result)
        rows.assert_not_awaited()

    async def test_insforge_rows_are_filtered_deduped_and_persisted(self):
        rows = [
            {"id": "new", "url": "https://www.example.com/a", "product_name": "Example", "created_at": "2026-08-27T10:00:00Z", "is_partial": False},
            {"id": "partial", "url": "https://partial.example", "product_name": "Partial", "created_at": "2026-08-27T09:00:00Z", "is_partial": True},
            {"id": "old", "url": "https://example.com/old", "product_name": "Old", "created_at": "2026-08-27T08:00:00Z", "is_partial": False},
        ]
        with patch("modules.insforge_client.get_internal_cache", AsyncMock(return_value=None)), \
             patch("modules.insforge_client.get_public_report_gallery_rows", AsyncMock(return_value=rows)), \
             patch("modules.insforge_client.set_internal_cache", AsyncMock(return_value=True)) as write:
            result = await app._public_reports_data()

        self.assertEqual(["new"], [row["id"] for row in result])
        write.assert_awaited_once()
