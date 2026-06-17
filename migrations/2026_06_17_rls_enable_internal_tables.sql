-- ════════════════════════════════════════════════════════════════════════
-- Enable RLS on server-internal tables to silence Supabase Security Advisor.
--
-- Both audit_cache and audit_qa are accessed ONLY via service-role client
-- (never via PostgREST anon/authenticated direct queries). Enabling RLS
-- with NO additional policies means:
--   - anon role: zero access (blocked by RLS, no policy grants it)
--   - authenticated role: zero access (same)
--   - service_role: bypasses RLS entirely (Postgres superuser privilege)
--
-- This matches the original intent of the DISABLE RLS comments in the
-- creation migrations — "service-role only" — but satisfies the advisor.
-- ════════════════════════════════════════════════════════════════════════

ALTER TABLE public.audit_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_qa    ENABLE ROW LEVEL SECURITY;

-- No POLICY statements needed: service_role bypasses RLS automatically.
-- If in the future a policy is added for authenticated users to read
-- their own audit_qa rows, add it here.
