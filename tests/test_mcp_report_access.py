import unittest
from unittest.mock import AsyncMock, patch

import app
from modules import mcp_app


class McpReportAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_owner_reads_markdown(self):
        app.jobs["mcp-test"] = {
            "user_id": "user-1",
            "status": "completed",
            "markdown": "# OpenMontage\n\n## OSS Growth Channel Attribution\nhttps://news.ycombinator.com/item?id=48616398",
        }
        try:
            with patch("modules.mcp_app._resolve_user", AsyncMock(return_value={"id": "user-1"})):
                result = await mcp_app.get_report_markdown("mcp-test")
        finally:
            app.jobs.pop("mcp-test", None)
        self.assertIn("markdown", result)
        self.assertIn("news.ycombinator.com", result["markdown"])

    async def test_unauthenticated_request_is_rejected(self):
        with patch("modules.mcp_app._resolve_user", AsyncMock(return_value=None)):
            result = await mcp_app.get_report_markdown("missing")
        self.assertEqual("AUTH_REQUIRED", result["error"])

    async def test_authenticated_non_owner_cannot_read_markdown(self):
        app.jobs["mcp-private"] = {
            "user_id": "owner-user",
            "status": "completed",
            "markdown": "# Private report",
        }
        try:
            with patch("modules.mcp_app._resolve_user", AsyncMock(return_value={"id": "other-user"})), \
                 patch("modules.insforge_client.get_report_record", AsyncMock(return_value=None)):
                result = await mcp_app.get_report_markdown("mcp-private")
        finally:
            app.jobs.pop("mcp-private", None)
        self.assertEqual("MARKDOWN_NOT_FOUND", result["error"])


if __name__ == "__main__":
    unittest.main()
