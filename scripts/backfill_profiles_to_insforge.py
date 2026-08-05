"""Mirror legacy Supabase profiles into InsForge without changing the source.

Run only inside the production container, where both service credentials stay
server-side:
    python scripts/backfill_profiles_to_insforge.py --dry-run
    python scripts/backfill_profiles_to_insforge.py --execute --limit 25 --offset 0
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.insforge_client import enabled as insforge_enabled
from modules.insforge_client import save_account_profile
from modules.supabase_client import get_supabase

PAGE_SIZE = 50
CONCURRENCY = 4
FIELDS = (
    "id,email,plan_type,credits_balance,credits_used,credits_monthly_quota,"
    "reports_public_default,referral_source,created_at,updated_at"
)


def _source_count() -> int:
    client = get_supabase()
    if not client:
        raise RuntimeError("Supabase service client is unavailable")
    result = client.table("profiles").select("id", count="exact").limit(1).execute()
    return int(result.count or 0)


def _load_source(limit: int | None, offset: int = 0) -> list[dict]:
    client = get_supabase()
    if not client:
        raise RuntimeError("Supabase service client is unavailable")
    rows: list[dict] = []
    offset = max(0, offset)
    while True:
        batch = client.table("profiles").select(FIELDS).order("created_at").range(
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
            return await save_account_profile(row)

    outcomes = await asyncio.gather(*(_copy(row) for row in rows), return_exceptions=True)
    ok = sum(result is True for result in outcomes)
    return ok, len(rows) - ok


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Perform writes; default is read-only.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit alias for the default read-only mode.")
    parser.add_argument("--limit", type=int, default=0, help="Optional bounded batch size.")
    parser.add_argument("--offset", type=int, default=0, help="Source offset for resumable execute batches.")
    args = parser.parse_args()

    if not insforge_enabled():
        print("ERROR: INSFORGE_URL and INSFORGE_API_KEY must be configured", file=sys.stderr)
        return 2
    if not args.execute:
        print(f"source_profiles={await asyncio.to_thread(_source_count)} mode=dry-run")
        return 0
    rows = await asyncio.to_thread(_load_source, args.limit or None, args.offset)
    print(f"source_profiles={len(rows)} offset={max(0, args.offset)} mode=execute")
    ok, failed = await _copy_all(rows)
    print(f"copied={ok} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
