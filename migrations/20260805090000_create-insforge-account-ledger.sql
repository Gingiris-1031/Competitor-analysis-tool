-- Private account and credit mirror for the staged Supabase -> InsForge cutover.
-- `legacy_user_id` stays the stable identity key until each account signs in to
-- InsForge through a password reset or OAuth. Runtime roles have no direct
-- access: the Analook server is the only caller during the transition.

CREATE TABLE IF NOT EXISTS public.account_profiles (
  legacy_user_id UUID PRIMARY KEY,
  insforge_user_id UUID UNIQUE,
  email TEXT NOT NULL,
  plan_type TEXT NOT NULL DEFAULT 'free',
  credits_balance INTEGER NOT NULL DEFAULT 0 CHECK (credits_balance >= 0),
  credits_used INTEGER NOT NULL DEFAULT 0 CHECK (credits_used >= 0),
  credits_monthly_quota INTEGER NOT NULL DEFAULT 0 CHECK (credits_monthly_quota >= 0),
  reports_public_default BOOLEAN NOT NULL DEFAULT TRUE,
  referral_source TEXT,
  source_created_at TIMESTAMPTZ,
  source_updated_at TIMESTAMPTZ,
  migrated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS account_profiles_email_unique_idx
  ON public.account_profiles (LOWER(email));
CREATE INDEX IF NOT EXISTS account_profiles_insforge_user_idx
  ON public.account_profiles (insforge_user_id)
  WHERE insforge_user_id IS NOT NULL;

-- Future credit changes are append-only, so reconciliation can compare a
-- balance with its source event without mutating user-owned history.
CREATE TABLE IF NOT EXISTS public.account_credit_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  legacy_user_id UUID NOT NULL REFERENCES public.account_profiles(legacy_user_id)
    ON DELETE CASCADE,
  delta INTEGER NOT NULL CHECK (delta <> 0),
  reason TEXT NOT NULL,
  source_event_id TEXT UNIQUE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS account_credit_ledger_user_created_idx
  ON public.account_credit_ledger (legacy_user_id, created_at DESC);

ALTER TABLE public.account_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.account_credit_ledger ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.account_profiles FROM anon, authenticated;
REVOKE ALL ON TABLE public.account_credit_ledger FROM anon, authenticated;

DROP TRIGGER IF EXISTS account_profiles_updated_at ON public.account_profiles;
CREATE TRIGGER account_profiles_updated_at
  BEFORE UPDATE ON public.account_profiles
  FOR EACH ROW
  EXECUTE FUNCTION system.update_updated_at();
