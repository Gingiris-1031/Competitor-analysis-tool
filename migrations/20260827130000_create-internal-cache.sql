-- Server-only shared cache for small derived payloads. This lets multiple Fly
-- machines reuse the same gallery result without exposing any cache contents
-- to browser roles.

CREATE TABLE IF NOT EXISTS public.internal_cache (
  cache_key TEXT PRIMARY KEY,
  value JSONB NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS internal_cache_expires_at_idx
  ON public.internal_cache (expires_at);

ALTER TABLE public.internal_cache ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.internal_cache FROM PUBLIC;
REVOKE ALL ON TABLE public.internal_cache FROM anon, authenticated;

CREATE OR REPLACE FUNCTION public.public_report_gallery_rows()
RETURNS TABLE (
  id TEXT,
  url TEXT,
  product_name TEXT,
  created_at TIMESTAMPTZ,
  is_partial BOOLEAN
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
  SELECT
    r.id,
    r.url,
    r.product_name,
    r.created_at,
    COALESCE((r.report ->> '_partial')::boolean, FALSE) AS is_partial
  FROM public.reports AS r
  WHERE r.is_public = TRUE
  ORDER BY r.created_at DESC
  LIMIT 150;
$$;

REVOKE ALL ON FUNCTION public.public_report_gallery_rows() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.public_report_gallery_rows() FROM anon, authenticated;
