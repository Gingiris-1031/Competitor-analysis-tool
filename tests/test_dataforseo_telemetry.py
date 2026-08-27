import unittest
from unittest.mock import AsyncMock, patch

from modules.dataforseo import _post_with_retry


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


class _Client:
    def __init__(self):
        self.post = AsyncMock(side_effect=[_Response(429), _Response(200)])


class DataForSeoTelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_metadata_distinguishes_supplier_retry_from_cache(self):
        client = _Client()
        with patch("modules.dataforseo.asyncio.sleep", AsyncMock()), \
             patch("modules.dataforseo.track_data_source") as track:
            response = await _post_with_retry(client, "https://api.example", {}, {})

        self.assertEqual(200, response.status_code)
        _, args, kwargs = track.mock_calls[0]
        self.assertEqual("DataForSEO", args[0])
        self.assertEqual("_post_with_retry", args[1])
        self.assertTrue(args[3])
        self.assertEqual(200, kwargs["extra"]["http_status"])
        self.assertEqual(1, kwargs["extra"]["retry_count"])
        self.assertFalse(kwargs["extra"]["cache_hit"])
