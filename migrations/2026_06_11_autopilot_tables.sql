-- ════════════════════════════════════════════════════════════════════════
-- Growth Autopilot — Phase 1 schema
-- Paste into Supabase SQL editor (Dashboard → SQL Editor → New query),
-- click Run. Idempotent: re-running is safe.
-- ════════════════════════════════════════════════════════════════════════

-- 1) Subscriptions — one row per tracked product per user.
CREATE TABLE IF NOT EXISTS autopilot_subscriptions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    target_url      TEXT        NOT NULL,
    product_name    TEXT,
    frequency       TEXT        NOT NULL DEFAULT 'weekly'
                                CHECK (frequency IN ('weekly', 'daily', 'monthly')),
    -- Competitive Lens add-on: track up to N competitors as benchmark.
    competitor_urls TEXT[]      NOT NULL DEFAULT '{}',
    status          TEXT        NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'paused', 'cancelled')),
    -- When the cron should next pick this up. We initialize to "1 min from now"
    -- so the first audit fires almost immediately after signup.
    next_run_at     TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '1 minute',
    last_run_at     TIMESTAMPTZ,
    -- Failure tracking — if 3 consecutive runs fail, status auto-flips to paused.
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_autopilot_subs_user
    ON autopilot_subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_autopilot_subs_next_run
    ON autopilot_subscriptions(next_run_at)
    WHERE status = 'active';

-- One sub per user-URL pair (don't double-track same product).
CREATE UNIQUE INDEX IF NOT EXISTS uniq_autopilot_sub_user_url
    ON autopilot_subscriptions(user_id, target_url);


-- 2) Snapshots — each scheduled audit run persists one row.
CREATE TABLE IF NOT EXISTS autopilot_snapshots (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID        NOT NULL REFERENCES autopilot_subscriptions(id) ON DELETE CASCADE,
    -- Links back to the reports table that growth_audit.py already writes.
    audit_job_id    TEXT        NOT NULL,
    -- Snapshot of the fetched site (homepage / robots / sitemap / pricing).
    -- We diff successive snapshots to surface what changed.
    site_data       JSONB,
    -- Structured findings parsed from the diagnosis markdown so the diff
    -- engine can identify "resolved", "new", "persistent" categories without
    -- re-running an LLM.
    findings        JSONB       DEFAULT '[]'::jsonb,
    -- Optional GA/GSC/Plausible numbers, if user enabled those integrations.
    metrics         JSONB       DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_autopilot_snapshots_sub
    ON autopilot_snapshots(subscription_id, created_at DESC);


-- 3) Diffs — comparison of two successive snapshots.
CREATE TABLE IF NOT EXISTS autopilot_diffs (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id     UUID        NOT NULL REFERENCES autopilot_subscriptions(id) ON DELETE CASCADE,
    -- prev_snapshot_id is NULL on the FIRST diff (no previous to compare against).
    prev_snapshot_id    UUID        REFERENCES autopilot_snapshots(id),
    curr_snapshot_id    UUID        NOT NULL REFERENCES autopilot_snapshots(id),
    -- Findings that disappeared since prev (user fixed them — celebrate).
    resolved_findings   JSONB       NOT NULL DEFAULT '[]'::jsonb,
    -- Findings newly appearing in curr — what user should look at next.
    new_findings        JSONB       NOT NULL DEFAULT '[]'::jsonb,
    -- Findings still present in both — the "open todos".
    persistent_findings JSONB       NOT NULL DEFAULT '[]'::jsonb,
    -- LLM-written email-ready summary (e.g. "本周修复 3 项 / 新发现 1 项 / 仍待处理 5 项").
    summary_md          TEXT,
    -- Net score (resolved - new): positive = progress, negative = regression.
    progress_score      INTEGER     NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_autopilot_diffs_sub
    ON autopilot_diffs(subscription_id, created_at DESC);


-- 4) Digest log — record of each email sent.
CREATE TABLE IF NOT EXISTS autopilot_digests (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id     UUID        NOT NULL REFERENCES autopilot_subscriptions(id) ON DELETE CASCADE,
    diff_id             UUID        REFERENCES autopilot_diffs(id),
    -- Resend's message id, lets us check delivery status later.
    resend_email_id     TEXT,
    recipient           TEXT        NOT NULL,
    -- Updated by Resend webhook (delivered / bounced / opened / spamreported).
    last_event          TEXT,
    sent_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_autopilot_digests_sub
    ON autopilot_digests(subscription_id, sent_at DESC);


-- ── Row-Level Security ────────────────────────────────────────────────────
-- All four tables are user-scoped. Service-role bypasses RLS so the cron
-- worker has full access; end-users only see their own data.

ALTER TABLE autopilot_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE autopilot_snapshots     ENABLE ROW LEVEL SECURITY;
ALTER TABLE autopilot_diffs         ENABLE ROW LEVEL SECURITY;
ALTER TABLE autopilot_digests       ENABLE ROW LEVEL SECURITY;

-- Subscriptions: users can do anything to their own rows.
DROP POLICY IF EXISTS "sub_self_select"  ON autopilot_subscriptions;
DROP POLICY IF EXISTS "sub_self_insert"  ON autopilot_subscriptions;
DROP POLICY IF EXISTS "sub_self_update"  ON autopilot_subscriptions;
DROP POLICY IF EXISTS "sub_self_delete"  ON autopilot_subscriptions;

CREATE POLICY "sub_self_select" ON autopilot_subscriptions
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "sub_self_insert" ON autopilot_subscriptions
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "sub_self_update" ON autopilot_subscriptions
    FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "sub_self_delete" ON autopilot_subscriptions
    FOR DELETE USING (auth.uid() = user_id);

-- Snapshots / diffs / digests: read-only via subscription ownership.
DROP POLICY IF EXISTS "snap_self_select"   ON autopilot_snapshots;
DROP POLICY IF EXISTS "diff_self_select"   ON autopilot_diffs;
DROP POLICY IF EXISTS "digest_self_select" ON autopilot_digests;

CREATE POLICY "snap_self_select" ON autopilot_snapshots
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM autopilot_subscriptions s
             WHERE s.id = subscription_id AND s.user_id = auth.uid()
        )
    );
CREATE POLICY "diff_self_select" ON autopilot_diffs
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM autopilot_subscriptions s
             WHERE s.id = subscription_id AND s.user_id = auth.uid()
        )
    );
CREATE POLICY "digest_self_select" ON autopilot_digests
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM autopilot_subscriptions s
             WHERE s.id = subscription_id AND s.user_id = auth.uid()
        )
    );


-- ── Convenience trigger: auto-bump updated_at on subscription updates ────
CREATE OR REPLACE FUNCTION autopilot_touch_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS autopilot_subs_touch ON autopilot_subscriptions;
CREATE TRIGGER autopilot_subs_touch
    BEFORE UPDATE ON autopilot_subscriptions
    FOR EACH ROW EXECUTE FUNCTION autopilot_touch_updated_at();


-- ── Smoke test (uncomment to verify install) ─────────────────────────────
-- SELECT 'autopilot_subscriptions' AS table_name, COUNT(*) FROM autopilot_subscriptions
-- UNION ALL SELECT 'autopilot_snapshots', COUNT(*) FROM autopilot_snapshots
-- UNION ALL SELECT 'autopilot_diffs', COUNT(*) FROM autopilot_diffs
-- UNION ALL SELECT 'autopilot_digests', COUNT(*) FROM autopilot_digests;
