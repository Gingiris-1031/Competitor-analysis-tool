import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

import app
from modules import insforge_client


def _request(token: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/me",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    })


class InsForgeIdentityBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_token_keeps_legacy_identity(self):
        with patch("app.verify_token_and_get_user", AsyncMock(return_value={"id": "legacy-1", "email": "a@example.com"})) as legacy, \
             patch("modules.insforge_client.verify_user_token", AsyncMock()) as insforge:
            user = await app._extract_user(_request("legacy-token"))

        self.assertEqual("legacy-1", user["id"])
        legacy.assert_awaited_once()
        insforge.assert_not_awaited()

    async def test_insforge_token_requires_linked_legacy_account(self):
        with patch("app.verify_token_and_get_user", AsyncMock(return_value=None)), \
             patch("modules.insforge_client.verify_user_token", AsyncMock(return_value={"id": "if-1", "email": "a@example.com"})), \
             patch("modules.insforge_client.link_insforge_identity", AsyncMock(return_value={"id": "legacy-1", "email": "a@example.com", "insforge_user_id": "if-1"})):
            user = await app._extract_user(_request("insforge-token"))

        self.assertEqual("legacy-1", user["id"])
        self.assertEqual("if-1", user["insforge_user_id"])

    async def test_unlinked_insforge_token_fails_closed(self):
        with patch("app.verify_token_and_get_user", AsyncMock(return_value=None)), \
             patch("modules.insforge_client.verify_user_token", AsyncMock(return_value={"id": "if-1", "email": "a@example.com"})), \
             patch("modules.insforge_client.link_insforge_identity", AsyncMock(return_value=None)):
            user = await app._extract_user(_request("insforge-token"))

        self.assertIsNone(user)


class InsForgeAuthCanaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_canary_config_is_hidden_when_rollout_is_off(self):
        from fastapi.testclient import TestClient
        with patch.dict("os.environ", {
            "ANALOOK_INSFORGE_AUTH_ROLLOUT": "off",
            "INSFORGE_URL": "https://example.insforge.app",
            "INSFORGE_ANON_KEY": "public-anon-key",
        }, clear=False):
            response = TestClient(app.app).get("/api/auth/canary-config")
        self.assertEqual(404, response.status_code)

    async def test_canary_allowlist_is_fail_closed(self):
        with patch.dict("os.environ", {
            "ANALOOK_INSFORGE_AUTH_ROLLOUT": "canary",
            "ANALOOK_INSFORGE_AUTH_CANARY_EMAILS": "approved@example.com",
        }, clear=False):
            self.assertTrue(insforge_client.identity_linking_allowed("APPROVED@example.com"))
            self.assertFalse(insforge_client.identity_linking_allowed("other@example.com"))

    async def test_verify_user_token_accepts_verified_camel_case_identity(self):
        response = unittest.mock.Mock()
        response.status_code = 200
        response.json.return_value = {
            "user": {"id": "if-1", "email": "a@example.com", "emailVerified": True}
        }
        client = AsyncMock()
        client.get.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.dict("os.environ", {
            "INSFORGE_URL": "https://example.insforge.app",
            "INSFORGE_API_KEY": "server-key",
        }, clear=False), patch("modules.insforge_client.httpx.AsyncClient", return_value=context):
            user = await insforge_client.verify_user_token("token")
        self.assertEqual({
            "id": "if-1", "email": "a@example.com", "email_verified": True
        }, user)

    async def test_unverified_session_is_rejected(self):
        response = unittest.mock.Mock()
        response.status_code = 200
        response.json.return_value = {
            "user": {"id": "if-1", "email": "approved@example.com", "email_verified": False}
        }
        client = AsyncMock()
        client.get.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        context.__aexit__.return_value = None
        with patch.dict("os.environ", {
            "INSFORGE_URL": "https://example.insforge.app",
            "INSFORGE_API_KEY": "server-key",
        }, clear=False), patch("modules.insforge_client.httpx.AsyncClient", return_value=context):
            user = await insforge_client.verify_user_token("token")
        self.assertIsNone(user)


if __name__ == "__main__":
    unittest.main()
