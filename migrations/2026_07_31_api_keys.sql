-- API Keys table for long-lived programmatic access (MCP, automation, etc.)
-- Replaces the need for short-lived Supabase JWT tokens when using MCP clients.

CREATE TABLE IF NOT EXISTS api_keys (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    key_hash    text NOT NULL UNIQUE,       -- sha256(raw_key), never store raw
    key_prefix  text NOT NULL,              -- first 8 chars, e.g. "ak_live_" for display
    name        text NOT NULL DEFAULT 'Default key',
    created_at  timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    revoked_at  timestamptz                 -- NULL = active
);

-- Index for fast lookup during auth
CREATE INDEX IF NOT EXISTS api_keys_key_hash_idx ON api_keys (key_hash);
CREATE INDEX IF NOT EXISTS api_keys_user_id_idx  ON api_keys (user_id);

-- RLS: users can only see/manage their own keys
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own api_keys"
    ON api_keys FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Service role can read all (for auth verification in backend)
-- No explicit policy needed: service_role bypasses RLS.
