import unittest
from unittest.mock import patch
from modules.migration_guard import blocks_path, maintenance_enabled

class MigrationGuardTests(unittest.TestCase):
    def test_blocks_read_side_effects_and_webhooks(self):
        for path in ['/api/webhook/clink', '/api/profile', '/mcp', '/share/audit/a', '/report/a']:
            self.assertTrue(blocks_path(path))
    def test_health_and_static_remain_available(self):
        for path in ['/api/health', '/api/health/strict', '/api/health/live', '/zh/', '/static/a.js']:
            self.assertFalse(blocks_path(path))
    def test_flag_or_environment_enables(self):
        with patch.dict('os.environ', {'ANALOOK_MIGRATION_MAINTENANCE':'1'}):
            self.assertTrue(maintenance_enabled())
        with patch.dict('os.environ', {'ANALOOK_MIGRATION_MAINTENANCE':'0'}), patch('pathlib.Path.exists', return_value=True):
            self.assertTrue(maintenance_enabled())
