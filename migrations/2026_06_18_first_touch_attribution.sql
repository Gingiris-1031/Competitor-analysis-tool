-- ════════════════════════════════════════════════════════════════════════
-- First-touch attribution — Phase 2 (objective, complements the self-report
-- referral_source survey added in 2026_06_11_referral_source.sql)
--
-- Why: the referral survey only gets ~28% response and is coarse (twitter vs
-- "which tweet?"). This captures utm_* + document.referrer + landing path on
-- the user's VERY FIRST pageview (locked in localStorage before the SPA can
-- strip the query string), then writes it ONCE at signup. That's what finally
-- explains bursts like the 2026-06-18 +19 signups.
--
-- Paste into Supabase SQL editor → Run. Idempotent. Write-once is enforced
-- server-side (POST /api/profile/attribution only fills NULLs).
-- ════════════════════════════════════════════════════════════════════════

ALTER TABLE profiles
    ADD COLUMN IF NOT EXISTS first_utm_source   TEXT,
    ADD COLUMN IF NOT EXISTS first_utm_medium   TEXT,
    ADD COLUMN IF NOT EXISTS first_utm_campaign TEXT,
    ADD COLUMN IF NOT EXISTS first_utm_content  TEXT,
    ADD COLUMN IF NOT EXISTS first_utm_term     TEXT,
    ADD COLUMN IF NOT EXISTS first_referrer     TEXT,
    ADD COLUMN IF NOT EXISTS first_landing_path TEXT,
    ADD COLUMN IF NOT EXISTS first_touch_at     TIMESTAMPTZ;

-- group-by source for the attribution dashboard
CREATE INDEX IF NOT EXISTS idx_profiles_first_utm_source
    ON profiles(first_utm_source)
    WHERE first_utm_source IS NOT NULL;

-- "explain the burst on day X" — group-by first_touch day
CREATE INDEX IF NOT EXISTS idx_profiles_first_touch_at
    ON profiles(first_touch_at)
    WHERE first_touch_at IS NOT NULL;

-- ── Smoke (uncomment to verify) ─────────────────────────────────────────
-- SELECT first_utm_source, first_referrer, COUNT(*)
--   FROM profiles WHERE first_touch_at IS NOT NULL
--   GROUP BY 1,2 ORDER BY 3 DESC;
