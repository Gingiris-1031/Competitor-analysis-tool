-- Bind a verified InsForge identity to its existing legacy account by exact,
-- normalized email.  The Analook server calls this function with its project
-- admin key only; browser roles are explicitly denied execution.
--
-- This intentionally does not create auth.users records or copy passwords.
-- InsForge owns identity creation through its Auth product, while this mapping
-- preserves legacy credits, reports, subscriptions, and API-key ownership.

ALTER TABLE public.account_profiles
  ADD COLUMN IF NOT EXISTS auth_linked_at TIMESTAMPTZ;

CREATE OR REPLACE FUNCTION public.link_insforge_identity(
  p_insforge_user_id UUID,
  p_email TEXT
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_email TEXT;
  v_legacy_user_id UUID;
  v_linked_user_id UUID;
BEGIN
  v_email := lower(btrim(coalesce(p_email, '')));
  IF p_insforge_user_id IS NULL OR v_email = '' THEN
    RAISE EXCEPTION 'verified InsForge user id and email are required';
  END IF;

  SELECT legacy_user_id, insforge_user_id
  INTO v_legacy_user_id, v_linked_user_id
  FROM public.account_profiles
  WHERE lower(email) = v_email
  FOR UPDATE;

  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

  IF v_linked_user_id IS NOT NULL AND v_linked_user_id <> p_insforge_user_id THEN
    RAISE EXCEPTION 'legacy account already linked to another InsForge identity';
  END IF;

  UPDATE public.account_profiles
  SET insforge_user_id = p_insforge_user_id,
      auth_linked_at = COALESCE(auth_linked_at, NOW())
  WHERE legacy_user_id = v_legacy_user_id;

  RETURN v_legacy_user_id;
END;
$$;

REVOKE ALL ON FUNCTION public.link_insforge_identity(UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.link_insforge_identity(UUID, TEXT) FROM anon, authenticated;
