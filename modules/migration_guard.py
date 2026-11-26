"""Per-machine maintenance switch used while taking the final migration copy."""
import os
from pathlib import Path

FLAG = Path('/tmp/analook-migration-maintenance')


def maintenance_enabled():
    return os.environ.get('ANALOOK_MIGRATION_MAINTENANCE') == '1' or FLAG.exists()


def blocks_path(path):
    # Even read handlers may write caches or provision profiles.
    if path in {'/api/health', '/api/health/strict', '/api/health/live'}:
        return False
    return path.startswith(('/api/', '/mcp', '/share/', '/report/'))
