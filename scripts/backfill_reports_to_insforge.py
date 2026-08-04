"""Backfill legacy Supabase reports into InsForge without exposing records.

Run inside the production container so credentials remain server-side:
    python scripts/backfill_reports_to_insforge.py --dry-run
    python scripts/backfill_reports_to_insforge.py --execute

The operation is idempotent: report IDs are preserved and each destination
write replaces only the matching ID. It never deletes from Supabase.
"""
import argparse
import asyncio
import sys
from pathlib import Path

# Fly SSH starts in a home directory rather than /app. Make the operational
# script independent of the caller's working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.insforge_client import enabled as insforge_enabled
from modules.insforge_client import save_report
from modules.supabase_client import get_supabase

PAGE_SIZE = 50
CONCURRENCY = 5


def _load_source(limit: int | None) -> list[dict]:
    client = get_supabase()
    if not client:
        raise RuntimeError("Supabase service client is unavailable")
    rows: list[dict] = []
    offset = 0
    fields = "id,user_id,url,product_name,report,markdown,is_public,status"
    while True:
        batch = client.table("reports").select(fields).order("created_at").range(
            offset, offset + PAGE_SIZE - 1
        ).execute().data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE or (limit and len(rows) >= limit):
            return rows[:limit] if limit else rows
        offset += PAGE_SIZE


async def _copy_all(rows: list[dict]) -> tuple[int, int]:
    gate = asyncio.Semaphore(CONCURRENCY)

    async def _copy(row: dict) -> bool:
        async with gate:
            return await save_report(
                job_id=str(row["id"]),
                user_id=row.get("user_id"),
                url=row.get("url") or "",
                product_name=row.get("product_name") or "",
                report=row.get("report") or {},
                markdown=row.get("markdown") or "",
                is_public=bool(row.get("is_public", True)),
                status=row.get("status") or "completed",
            )

    outcomes = await asyncio.gather(*(_copy(row) for row in rows), return_exceptions=True)
    ok = sum(result is True for result in outcomes)
    return ok, len(rows) - ok


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Perform writes; default is read-only.")
    parser.add_argument("--limit", type=int, default=0, help="Optional bounded batch size.")
    args = parser.parse_args()

    if not insforge_enabled():
        print("ERROR: INSFORGE_URL and INSFORGE_API_KEY must be configured", file=sys.stderr)
        return 2
    rows = await asyncio.to_thread(_load_source, args.limit or None)
    print(f"source_reports={len(rows)} mode={'execute' if args.execute else 'dry-run'}")
    if not args.execute:
        return 0
    ok, failed = await _copy_all(rows)
    print(f"copied={ok} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
