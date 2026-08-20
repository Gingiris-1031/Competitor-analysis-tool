import os
import unittest
from unittest.mock import AsyncMock, patch

from modules.github_oss import _gh_get, _parse_gh_url, analyze_github_oss


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {}

    def json(self):
        return self._payload


class GithubOssInputTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_direct_repository_url(self):
        self.assertEqual(("calesthio", "OpenMontage"), _parse_gh_url("https://github.com/calesthio/OpenMontage"))

    async def test_explicit_repo_skips_discovery(self):
        repo = {"stars": 100, "forks": 2, "created_at": "2026-01-01"}
        with patch("modules.github_oss._resolve_repo", AsyncMock()) as resolve, \
             patch("modules.github_oss._fetch_repo_info", AsyncMock(return_value=repo)), \
             patch("modules.github_oss._fetch_latest_release", AsyncMock(return_value=None)), \
             patch("modules.github_oss._sample_star_history", AsyncMock(return_value=[])):
            result = await analyze_github_oss("github.com", "OpenMontage", explicit_repo=("calesthio", "OpenMontage"))
        resolve.assert_not_awaited()
        self.assertTrue(result["found"])
        self.assertEqual("calesthio", result["owner"])

    async def test_invalid_token_retries_anonymously(self):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[_Response(401), _Response(200, {"ok": True})])
        with patch.dict(os.environ, {"GITHUB_TOKEN": "stale-token"}):
            response = await _gh_get(client, "https://api.github.com/repos/o/r")
        self.assertEqual(200, response.status_code)
        first_headers = client.get.await_args_list[0].kwargs["headers"]
        second_headers = client.get.await_args_list[1].kwargs["headers"]
        self.assertIn("Authorization", first_headers)
        self.assertNotIn("Authorization", second_headers)


if __name__ == "__main__":
    unittest.main()
