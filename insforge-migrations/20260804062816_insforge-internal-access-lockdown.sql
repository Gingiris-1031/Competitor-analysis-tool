-- InsForge cutover guard: these tables are accessed only by the Analook
-- server with the project admin key during the Supabase transition.
-- Browser clients and anonymous callers must never read report JSON, MCP-key
-- hashes, or MCP credit balances directly.

ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mcp_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mcp_api_keys ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.reports FROM anon, authenticated;
REVOKE ALL ON TABLE public.mcp_accounts FROM anon, authenticated;
REVOKE ALL ON TABLE public.mcp_api_keys FROM anon, authenticated;

REVOKE ALL ON FUNCTION public.consume_mcp_credit(TEXT, INTEGER)
    FROM PUBLIC, anon, authenticated;
