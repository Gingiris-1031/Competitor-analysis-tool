"""Read-only, paginated rescue export. Never imports or changes production.

Uses the existing linked InsForge config; prints counts, never records/keys.
An export taken while writes continue is NOT a transaction-consistent backup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

SOURCE_HOST = "smk6dawe.us-east.insforge.app"
TABLES = {
    "account_profiles": "legacy_user_id", "account_credit_ledger": "id",
    "mcp_accounts": "owner_id", "mcp_api_keys": "id", "reports": "id",
    "scorecards": "id", "timelines": "id", "internal_cache": "cache_key",
}


def atomic_json(path, value):
    path = Path(path)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".partial-")
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(value, out, ensure_ascii=False, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def exact_count(headers):
    value = headers.get("Content-Range", "").rsplit("/", 1)[-1]
    if not value.isdigit():
        raise ValueError("Server did not return an exact count; completeness is unknown")
    return int(value)


def collect_table(fetch, table, key, page_size):
    _, headers = fetch(table, {"select": key, "limit": "1"})
    expected = exact_count(headers)
    rows, seen, cursor = [], set(), None
    while True:
        params = {"select": "*", "order": key + ".asc", "limit": str(page_size)}
        if cursor is not None:
            params[key] = "gt." + str(cursor)
        batch, _ = fetch(table, params)
        if not isinstance(batch, list):
            raise ValueError("Expected a row array")
        if not batch:
            break
        for row in batch:
            identity = row.get(key)
            if identity is None or identity in seen:
                raise ValueError("Missing or repeated primary key; export stopped")
            seen.add(identity)
            rows.append(row)
        cursor = batch[-1][key]
        # Do not stop on a short page: the server may cap page size.
    _, headers = fetch(table, {"select": key, "limit": "1"})
    final_count = exact_count(headers)
    if expected != len(rows) or expected != final_count:
        raise ValueError("Row count changed or export was incomplete; rerun after quiescing writes")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--page-size", type=int, default=25)
    parser.add_argument("--ca-file", type=str)
    args = parser.parse_args()
    if not 1 <= args.page_size <= 100:
        parser.error("page size must be between 1 and 100")
    cfg = json.loads(args.config.read_text())
    base = cfg["oss_host"].rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or parsed.netloc != SOURCE_HOST or parsed.path:
        parser.error("Source must be the confirmed Analook production InsForge host")
    context = ssl.create_default_context(cafile=args.ca_file)

    def fetch(table, params):
        req = Request(base + "/api/database/records/" + table + "?" + urlencode(params),
                      headers={"Authorization": "Bearer " + cfg["api_key"], "Prefer": "count=exact"})
        with urlopen(req, timeout=30, context=context) as response:
            return json.load(response), response.headers

    # A fresh directory prevents mixing successful files from different runs.
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {"source": SOURCE_HOST, "started_at": datetime.now(timezone.utc).isoformat(),
                "status": "incomplete", "transaction_consistent": False,
                "scope": "public business rows only; excludes Auth, Storage files and schema",
                "tables": {}}
    atomic_json(args.output / "manifest.json", manifest)
    failed = False
    for table, key in TABLES.items():
        try:
            rows = collect_table(fetch, table, key, args.page_size)
            path = args.output / (table + ".json")
            atomic_json(path, rows)
            manifest["tables"][table] = {"status": "exported", "rows": len(rows),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            print(f"{table}: exported {len(rows)} rows", flush=True)
        except Exception as exc:
            failed = True
            # Exception bodies can contain query data; retain only type/status.
            manifest["tables"][table] = {"status": "failed", "error_type": type(exc).__name__,
                                         "http_status": getattr(exc, "code", None)}
            print(f"{table}: failed ({type(exc).__name__})", flush=True)
        atomic_json(args.output / "manifest.json", manifest)
    manifest["status"] = "incomplete" if failed else "rows_exported_requires_final_snapshot"
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(args.output / "manifest.json", manifest)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
