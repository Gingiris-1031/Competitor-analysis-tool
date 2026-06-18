-- ════════════════════════════════════════════════════════════════════════
-- Backfill: seed the new first-touch columns from the existing self-report
-- survey (referral_source), so the ~35 users who answered "where did you hear
-- about us" get a coarse channel in the attribution report instead of showing
-- as unknown(pre-infra).
--
-- Run AFTER 2026_06_18_first_touch_attribution.sql.
-- Paste into Supabase SQL editor → Run. Idempotent + write-once safe.
--
-- Design notes:
--   • first_utm_medium = 'self_report' marks these as survey-derived, NOT an
--     objective capture — so the report's "objective capture %" stays honest.
--   • We deliberately do NOT set first_touch_at, so the capture-rate metric
--     and the landing-page / campaign sections remain objective-only. The
--     channel funnel (which reads first_utm_source) still credits these users.
--   • WHERE first_utm_source IS NULL → never clobbers a real first-touch that
--     attribution.js may have already written.
-- ════════════════════════════════════════════════════════════════════════

UPDATE profiles
SET
    first_utm_source   = referral_source,
    first_utm_medium   = 'self_report',
    first_utm_campaign = CASE
                             WHEN referral_source = 'other' THEN LEFT(referral_other, 200)
                             ELSE NULL
                         END
WHERE referral_source IS NOT NULL
  AND first_utm_source IS NULL;

-- ── Verify (uncomment) ──────────────────────────────────────────────────
-- SELECT first_utm_source, first_utm_medium, COUNT(*)
--   FROM profiles WHERE first_utm_medium = 'self_report'
--   GROUP BY 1,2 ORDER BY 3 DESC;
