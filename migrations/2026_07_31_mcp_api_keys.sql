-- MCP credentials and credit ledger.
-- These tables are server-admin only: MCP callers authenticate at the Analook
-- service boundary; no browser receives direct table access.

CREATE TABLE IF NOT EXISTS public.mcp_accounts (
    owner_id UUID PRIMARY KEY,
    credits_balance INTEGER NOT NULL DEFAULT 3 CHECK (credits_balance >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.mcp_api_keys (
    id TEXT PRIMARY KEY,
    owner_id UUID NOT NULL,
    name TEXT NOT NULL DEFAULT 'MCP key',
    key_prefix TEXT NOT NULL UNIQUE,
    secret_hash TEXT NOT NULL,
    scopes JSONB NOT NULL DEFAULT '["analysis:read", "analysis:write"]'::jsonb,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS mcp_api_keys_owner_created_idx
    ON public.mcp_api_keys (owner_id, created_at DESC);

ALTER TABLE public.mcp_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mcp_api_keys ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.mcp_accounts FROM anon, authenticated;
REVOKE ALL ON public.mcp_api_keys FROM anon, authenticated;

CREATE OR REPLACE FUNCTION public.consume_mcp_credit(
    p_key_id TEXT,
    p_amount INTEGER DEFAULT 1
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_owner_id UUID;
    v_remaining INTEGER;
BEGIN
    IF p_amount IS NULL OR p_amount < 1 THEN
        RAISE EXCEPTION 'credit amount must be positive';
    END IF;

    SELECT owner_id INTO v_owner_id
    FROM public.mcp_api_keys
    WHERE id = p_key_id
      AND revoked_at IS NULL
      AND (expires_at IS NULL OR expires_at > NOW());

    IF v_owner_id IS NULL THEN
        RETURN NULL;
    END IF;

    UPDATE public.mcp_accounts
    SET credits_balance = credits_balance - p_amount,
        updated_at = NOW()
    WHERE owner_id = v_owner_id
      AND credits_balance >= p_amount
    RETURNING credits_balance INTO v_remaining;

    RETURN v_remaining;
END;
$$;

REVOKE ALL ON FUNCTION public.consume_mcp_credit(TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
