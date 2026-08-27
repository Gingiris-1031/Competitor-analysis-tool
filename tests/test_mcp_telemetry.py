import unittest
from unittest.mock import patch

from modules.mcp_app import _track_mcp_tool


class McpTelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_validation_result_is_classified_without_arguments(self):
        @_track_mcp_tool("analyze_competitor")
        async def tool():
            return {"error": "INVALID_URL", "hint": "contains user input but must not be tracked"}

        with patch("modules.posthog_track.track_mcp_tool_outcome") as track:
            result = await tool()

        self.assertEqual("INVALID_URL", result["error"])
        _, args, kwargs = track.mock_calls[0]
        self.assertEqual("analyze_competitor", args[1])
        self.assertEqual("validation_error", args[2])
        self.assertEqual("rejected", args[3])
        self.assertEqual("INVALID_URL", kwargs["error_class"])
        self.assertNotIn("hint", repr(track.call_args))

    async def test_exception_is_classified_as_execution_failure(self):
        @_track_mcp_tool("browse_public_reports")
        async def tool():
            raise RuntimeError("private report content")

        with patch("modules.posthog_track.track_mcp_tool_outcome") as track:
            with self.assertRaises(RuntimeError):
                await tool()

        _, args, kwargs = track.mock_calls[0]
        self.assertEqual("execution_failure", args[2])
        self.assertEqual("exception", args[3])
        self.assertEqual("RuntimeError", kwargs["error_class"])
        self.assertNotIn("private report content", repr(track.call_args))
