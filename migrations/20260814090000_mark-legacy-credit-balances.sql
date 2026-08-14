-- Preserve historical credit balances while making their provenance explicit.
-- This migration is classification-only: it never adjusts a user's balance,
-- plan, quota, or entitlement.

ALTER TABLE public.account_profiles
  ADD COLUMN IF NOT EXISTS credit_balance_source TEXT NOT NULL DEFAULT 'migration_snapshot';

UPDATE public.account_profiles
SET credit_balance_source = 'legacy_unattributed_bonus'
WHERE plan_type = 'free'
  AND credits_balance > credits_monthly_quota
  AND credit_balance_source = 'migration_snapshot';

CREATE INDEX IF NOT EXISTS account_profiles_credit_balance_source_idx
  ON public.account_profiles (credit_balance_source)
  WHERE credit_balance_source = 'legacy_unattributed_bonus';
