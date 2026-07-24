-- Dual-write destination for Analook reports. It is intentionally private:
-- the FastAPI service (project admin) remains the only access path during
-- migration, preserving existing Supabase auth and public-share behaviour.
CREATE TABLE IF NOT EXISTS public.reports (
  id TEXT PRIMARY KEY,
  user_id UUID,
  url TEXT NOT NULL,
  product_name TEXT NOT NULL DEFAULT '',
  report JSONB NOT NULL DEFAULT '{}'::jsonb,
  markdown TEXT NOT NULL DEFAULT '',
  is_public BOOLEAN NOT NULL DEFAULT TRUE,
  status TEXT NOT NULL DEFAULT 'completed'
    CHECK (status IN ('running', 'completed', 'failed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Supabase user IDs are retained without an auth.users foreign key until the
-- authentication migration has a verified identity-mapping plan.
COMMENT ON COLUMN public.reports.user_id IS
  'Legacy Supabase user UUID; application-admin access only during dual write.';

CREATE INDEX IF NOT EXISTS reports_user_created_idx
  ON public.reports (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS reports_public_created_idx
  ON public.reports (is_public, created_at DESC);

ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.reports FROM anon, authenticated;

DROP TRIGGER IF EXISTS reports_updated_at ON public.reports;
CREATE TRIGGER reports_updated_at
  BEFORE UPDATE ON public.reports
  FOR EACH ROW
  EXECUTE FUNCTION system.update_updated_at();
