-- ════════════════════════════════════════════════════════════════════════
-- Audit cache — TTL cache for expensive fetchers (DataForSEO, Wayback,
-- GitHub, etc.). Per-source TTL so each data freshness profile is
-- respected: Wayback rarely changes (7d), DataForSEO updates daily
-- (24h), Homepage / TinyFish are short (1h).
--
-- Paste into Supabase SQL editor → Run. Idempotent.
-- ════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS audit_cache (
    -- Composite key: which data source × which URL (or domain or query).
    source       TEXT        NOT NULL,
    cache_key    TEXT        NOT NULL,
    -- The cached payload — anything the fetcher returns. Stored as JSONB
    -- so PostgreSQL can index/filter inside it if we ever need to.
    value        JSONB       NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL,
    -- How long the entry was set to live for, in seconds. Lets us know
    -- "was this a 24h fetch or a 7d fetch" without recomputing.
    ttl_seconds  INTEGER     NOT NULL,
    -- Track hit count for observability. Each get() increments this.
    hit_count    INTEGER     NOT NULL DEFAULT 0,
    PRIMARY KEY (source, cache_key)
);

-- Fast eviction sweep: "delete where expires_at < now()"
CREATE INDEX IF NOT EXISTS idx_audit_cache_expires
    ON audit_cache (expires_at);

-- Convenience: the cron worker we may add later for cleanup can run
--   DELETE FROM audit_cache WHERE expires_at < NOW();
-- to garbage-collect. Without it, the table grows but lookups stay
-- correct because the helper rejects expired rows on read.


-- ── RLS off: service-role only ────────────────────────────────────────────
-- This table is server-internal — end users should never see it directly.
-- We keep RLS DISABLED so the service-role client can read+write freely
-- (anon role has no privileges by default).
ALTER TABLE audit_cache DISABLE ROW LEVEL SECURITY;


-- ── Smoke test (uncomment to verify) ─────────────────────────────────────
-- INSERT INTO audit_cache (source, cache_key, value, expires_at, ttl_seconds)
-- VALUES ('test', 'hello', '{"a":1}'::jsonb, NOW() + INTERVAL '1 day', 86400)
-- ON CONFLICT (source, cache_key) DO UPDATE SET hit_count = audit_cache.hit_count + 1;
-- SELECT * FROM audit_cache WHERE source = 'test';
-- DELETE FROM audit_cache WHERE source = 'test';
