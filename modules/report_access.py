"""Protect persisted report payloads even when served from a warm cache."""
import re

PATTERN = re.compile(r'^/(?:api/(?:v1/(?:report|status)|report|status|export|share(?:/audit)?|growth-audit|audit/qa|cancel|og/audit)|share/audit|(?:zh/)?report)/([^/]+)(?:/markdown|/translate)?$')


def report_id_for_path(path):
    match = PATTERN.fullmatch(path)
    if not match:
        return None
    value = match.group(1)
    return value[:-4] if path.startswith('/api/og/audit/') and value.endswith('.png') else value


def owner_can_read(row, user):
    if not row or row.get('is_public') is not False:
        return True
    return bool(user and row.get('user_id') and user.get('id') == row['user_id'])
