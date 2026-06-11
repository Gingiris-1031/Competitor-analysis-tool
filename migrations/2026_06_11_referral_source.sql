-- ════════════════════════════════════════════════════════════════════════
-- Referral source survey — Phase 1
-- Paste into Supabase SQL editor → Run. Idempotent.
-- ════════════════════════════════════════════════════════════════════════

-- Add the 3 fields to profiles:
--   referral_source — one of: twitter, linkedin, google_search, geo, referral, other
--                     NULL until the user answers the survey (which is enforced
--                     client-side on first authenticated page hit).
--   referral_other  — free-text when source = 'other' OR free-text addendum
--   referral_at     — timestamp of when they answered
ALTER TABLE profiles
    ADD COLUMN IF NOT EXISTS referral_source TEXT,
    ADD COLUMN IF NOT EXISTS referral_other  TEXT,
    ADD COLUMN IF NOT EXISTS referral_at     TIMESTAMPTZ;

-- Sanity constraint: source must be one of the known values OR null.
ALTER TABLE profiles DROP CONSTRAINT IF EXISTS profiles_referral_source_check;
ALTER TABLE profiles
    ADD CONSTRAINT profiles_referral_source_check
    CHECK (
        referral_source IS NULL
        OR referral_source IN (
            'twitter', 'linkedin', 'google_search', 'geo', 'referral', 'other'
        )
    );

-- Index for analytics dashboard (group-by source).
CREATE INDEX IF NOT EXISTS idx_profiles_referral_source
    ON profiles(referral_source)
    WHERE referral_source IS NOT NULL;

-- ── Smoke (uncomment to verify) ─────────────────────────────────────────
-- SELECT referral_source, COUNT(*) FROM profiles GROUP BY 1 ORDER BY 2 DESC;
