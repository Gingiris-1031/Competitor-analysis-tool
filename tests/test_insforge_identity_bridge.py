import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

import app


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


if __name__ == "__main__":
    unittest.main()
